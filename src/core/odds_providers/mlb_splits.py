"""
MLB Batting Splits — vs Pitcher Handedness

Fetches today's probable pitchers from the official MLB Stats API, determines
each starter's throwing hand, then pulls each opposing batter's splits
(AVG / OPS / K%) vs that handedness for the current season.

Data source: statsapi.mlb.com (official MLB, free, no key required)

Verified: numbers match PickFinder's "vs RHP / vs LHP" player-page stats
exactly (tested 2026-05-28 DET roster — every AB, AVG, OPS confirmed).

Usage:
    from src.core.odds_providers.mlb_splits import get_todays_splits
    splits = get_todays_splits()   # {normalized_name: {ops, avg, ab, k_pct, hand}}
"""

import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_DIR      = 'pickfinder_cache'   # reuse same cache dir
CACHE_FILE     = os.path.join(CACHE_DIR, 'mlb_splits.json')
CACHE_MINUTES  = 15

_MLB_API = "https://statsapi.mlb.com/api/v1"

_http = requests.Session()
_http.headers.update({"User-Agent": "Mozilla/5.0"})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        age = (time.time() - os.path.getmtime(CACHE_FILE)) / 60
        if age < CACHE_MINUTES:
            with open(CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_cache(data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


from src.sports.mlb.constants import normalize_name as _normalize


def _pitcher_hand(pitcher_id: int) -> str:
    """Return 'L' or 'R' for a pitcher, '' if unknown."""
    try:
        r = _http.get(f"{_MLB_API}/people/{pitcher_id}", timeout=8)
        if r.status_code == 200:
            return r.json().get('people', [{}])[0].get('pitchHand', {}).get('code', '')
    except Exception:
        pass
    return ''



def _pitcher_season_stats(pitcher_id: int) -> dict:
    """ERA, WHIP, K/9 for a pitcher this season."""
    try:
        r = _http.get(f"{_MLB_API}/people/{pitcher_id}/stats",
            params={"stats": "season", "group": "pitching",
                    "gameType": "R", "season": 2026},
            timeout=8)
        if r.status_code != 200:
            return {}
        splits = r.json().get('stats', [{}])[0].get('splits', [])
        if not splits:
            return {}
        s   = splits[0].get('stat', {})
        era  = float(s.get('era',  0) or 0)
        whip = float(s.get('whip', 0) or 0)
        ip   = float(s.get('inningsPitched', 0) or 0)
        k    = int(s.get('strikeOuts', 0) or 0)
        k9   = round(k / ip * 9, 2) if ip > 0 else 0.0
        return {'era': era, 'whip': whip, 'k9': k9}
    except Exception:
        return {}


def _team_hitting_stats(team_id: int) -> dict:
    """OPS, AVG, K% for a team's lineup this season."""
    try:
        r = _http.get(f"{_MLB_API}/teams/{team_id}/stats",
            params={"stats": "season", "group": "hitting",
                    "gameType": "R", "season": 2026},
            timeout=8)
        if r.status_code != 200:
            return {}
        splits = r.json().get('stats', [{}])[0].get('splits', [])
        if not splits:
            return {}
        s    = splits[0].get('stat', {})
        ops  = float(s.get('ops', 0) or 0)
        avg  = float(s.get('avg', 0) or 0)
        so   = int(s.get('strikeOuts', 0) or 0)
        pa   = int(s.get('plateAppearances', 0) or 0)
        k_pct = round(so / pa * 100, 1) if pa > 0 else 0.0
        return {'ops': ops, 'avg': avg, 'k_pct': k_pct}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_DEFENSE_CACHE_FILE = os.path.join(CACHE_DIR, 'mlb_defense.json')


def get_defensive_matchups(date_str: str = None) -> tuple:
    """
    Build today's defensive context for each player facing a probable pitcher.

    Returns:
        batter_matchups  — {norm_batter_name: {'era': float, 'whip': float, 'k9': float,
                                                'opp_pitcher': str}}
        pitcher_matchups — {norm_pitcher_name: {'team_ops': float, 'team_avg': float,
                                                 'team_k_pct': float, 'opp_team': str}}
    """
    # --- cache ---
    try:
        if os.path.exists(_DEFENSE_CACHE_FILE):
            age = (time.time() - os.path.getmtime(_DEFENSE_CACHE_FILE)) / 60
            if age < CACHE_MINUTES:
                with open(_DEFENSE_CACHE_FILE) as f:
                    cached = json.load(f)
                n_b = len(cached.get('batters', {}))
                n_p = len(cached.get('pitchers', {}))
                print(f"   Using cached defensive matchups ({n_b} batters, {n_p} pitchers)")
                return cached.get('batters', {}), cached.get('pitchers', {})
    except Exception:
        pass

    from datetime import date
    today = date_str or date.today().strftime('%Y-%m-%d')
    print(f"   Fetching defensive matchups for {today}...")

    try:
        r = _http.get(f"{_MLB_API}/schedule",
            params={"sportId": 1, "date": today,
                    "hydrate": "probablePitcher"},
            timeout=12)
        if r.status_code != 200:
            return {}, {}
    except Exception as e:
        print(f"   Defensive matchups error: {e}")
        return {}, {}

    games = r.json().get('dates', [{}])[0].get('games', [])
    if not games:
        return {}, {}

    batter_matchups  = {}
    pitcher_matchups = {}

    # Collect all pitcher-stat and team-stat tasks, then fire in parallel
    pitcher_stat_tasks = []   # (pitcher_id, pitcher_name, batter_team_id, batter_team_name)
    team_stat_tasks    = []   # (pitcher_id, pitcher_name, opp_team_id, opp_team_name)

    for game in games:
        away         = game['teams']['away']
        home         = game['teams']['home']
        away_id      = away['team']['id']
        home_id      = home['team']['id']
        away_name    = away['team']['name']
        home_name    = home['team']['name']
        away_pitcher = away.get('probablePitcher', {})
        home_pitcher = home.get('probablePitcher', {})

        if away_pitcher.get('id'):
            pitcher_stat_tasks.append((away_pitcher['id'], away_pitcher.get('fullName',''), home_id, home_name))
            team_stat_tasks.append((away_pitcher['id'], away_pitcher.get('fullName',''), home_id, home_name))
        if home_pitcher.get('id'):
            pitcher_stat_tasks.append((home_pitcher['id'], home_pitcher.get('fullName',''), away_id, away_name))
            team_stat_tasks.append((home_pitcher['id'], home_pitcher.get('fullName',''), away_id, away_name))

    roster_cache2 = {}

    def _fetch_batter_defense(pitcher_id, pitcher_name, batter_team_id, _unused):
        """Fetch pitcher stats + roster for batter-side matchups."""
        p_stats = _pitcher_season_stats(pitcher_id)
        if not p_stats:
            return {}
        try:
            r2 = _http.get(f"{_MLB_API}/teams/{batter_team_id}/roster",
                params={"rosterType": "active", "season": 2026}, timeout=10)
            roster = r2.json().get('roster', []) if r2.status_code == 200 else []
        except Exception:
            roster = []
        out = {}
        for p in roster:
            if p.get('position', {}).get('type') != 'Pitcher':
                out[_normalize(p['person']['fullName'])] = {**p_stats, 'opp_pitcher': pitcher_name}
        return out

    def _fetch_pitcher_defense(pitcher_id, pitcher_name, opp_team_id, opp_team_name):
        t_stats = _team_hitting_stats(opp_team_id)
        if not t_stats:
            return {}
        return {_normalize(pitcher_name): {
            'team_ops':   t_stats['ops'],
            'team_avg':   t_stats['avg'],
            'team_k_pct': t_stats['k_pct'],
            'opp_team':   opp_team_name,
        }}

    with ThreadPoolExecutor(max_workers=16) as ex:
        batter_futs  = [ex.submit(_fetch_batter_defense, *t) for t in pitcher_stat_tasks]
        pitcher_futs = [ex.submit(_fetch_pitcher_defense, *t) for t in team_stat_tasks]
        for fut in as_completed(batter_futs):
            try:
                batter_matchups.update(fut.result())
            except Exception:
                pass
        for fut in as_completed(pitcher_futs):
            try:
                pitcher_matchups.update(fut.result())
            except Exception:
                pass

    print(f"   Defensive matchups: {len(batter_matchups)} batters, {len(pitcher_matchups)} pitchers")
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_DEFENSE_CACHE_FILE, 'w') as f:
            json.dump({'batters': batter_matchups, 'pitchers': pitcher_matchups}, f)
    except Exception:
        pass

    return batter_matchups, pitcher_matchups


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date
    print(f"--- MLB Splits Test ({date.today()}) ---\n")
    splits = get_todays_splits()

    if not splits:
        print("No data returned")
    else:
        print(f"\n{'Player':<28} {'Hand':>5} {'AB':>5} {'AVG':>6} {'OPS':>6} {'K%':>6}")
        print("-" * 60)
        for name, s in sorted(splits.items(), key=lambda x: -x[1].get('ops', 0))[:20]:
            print(f"{name:<28} {'v'+s['hand']:>5} {s['ab']:>5} "
                  f"{s['avg']:>6.3f} {s['ops']:>6.3f} {s['k_pct']:>5.1f}%")


# New get_todays_splits + Savant helpers. Replaces broken statSplits per-batter calls.

def _parse_savant_float(v):
    """Savant rate stats arrive as strings like '.278' or '0.831'. Safe float."""
    if v is None:
        return 0.0
    s = str(v).strip().strip('"')
    if s == '' or s == '.':
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fetch_savant_hand_table(hand: str) -> dict:
    """
    Pull the season hitting leaderboard vs a given pitcher hand from Baseball
    Savant (one CSV for the whole league). Returns {player_id: {avg,ops,slg,k_pct,ab}}.

    hand: 'R' or 'L' (the PITCHER's throwing hand the batter faced).
    Savant filter is pitch_hand|<R|L>.

    min=20 (raw PA vs this hand) instead of Savant's default min=q (qualified
    for the batting title — full-season PA, ~300+, a much higher bar than PA
    against one specific hand). q covers ~152 batters/hand; 20 covers ~519 —
    the tradeoff is more small-sample noise at the margin, which is why the
    caller keeps and exposes 'ab' (actually PA) per player so the UI can show
    sample size instead of presenting every row as equally reliable.
    """
    import csv, io
    url = ("https://baseballsavant.mlb.com/leaderboard/custom"
           "?year=2026&type=batter&filter=pitch_hand|" + hand +
           "&min=20&selections=pa,batting_avg,slg_percent,on_base_plus_slg,k_percent"
           "&sortColumn=on_base_plus_slg&sortDirection=desc&csv=true")
    out = {}
    try:
        r = _http.get(url, timeout=20)
        if r.status_code != 200:
            print(f"   Savant hand={hand} HTTP {r.status_code}")
            return out
        reader = csv.DictReader(io.StringIO(r.content.decode('utf-8-sig')))
        for row in reader:
            try:
                pid = int(row.get('player_id') or 0)
            except (ValueError, TypeError):
                continue
            if not pid:
                continue
            pa  = int(_parse_savant_float(row.get('pa')))
            out[pid] = {
                'avg':   _parse_savant_float(row.get('batting_avg')),
                'slg':   _parse_savant_float(row.get('slg_percent')),
                'ops':   _parse_savant_float(row.get('on_base_plus_slg')),
                'k_pct': _parse_savant_float(row.get('k_percent')),
                'ab':    pa,   # PA used as volume proxy (Savant gives PA not AB here)
            }
    except Exception as e:
        print(f"   Savant hand={hand} error: {e}")
    return out


def get_todays_splits(date_str: str = None) -> dict:
    """
    Build a lookup of every batter playing today -> their season splits vs the
    handedness of today's opposing probable pitcher.

    Data source: Baseball Savant custom leaderboard (pitch_hand filter).
    Two CSV pulls total (vs R, vs L) for the whole league, joined to today's
    rosters by player_id, emitted keyed by normalized name.

    Return contract (unchanged from prior MLB-API version):
        { normalized_name: {'avg','ops','ab','k_pct','hand'} }
    """
    cached = _load_cache()
    if cached is not None:
        print(f"   Using cached MLB splits ({len(cached)} batters)")
        return cached

    from datetime import date
    today = date_str or date.today().strftime('%Y-%m-%d')
    print(f"   Fetching MLB splits for {today} (source: Baseball Savant)...")

    # Step 1: today's schedule + probable pitchers (MLB API — this path works)
    try:
        r = _http.get(f"{_MLB_API}/schedule",
            params={"sportId": 1, "date": today,
                    "hydrate": "probablePitcher"},
            timeout=12)
        if r.status_code != 200:
            print(f"   MLB schedule HTTP {r.status_code}")
            return {}
    except Exception as e:
        print(f"   MLB schedule error: {e}")
        return {}

    games = r.json().get('dates', [{}])[0].get('games', [])
    if not games:
        print("   No MLB games today")
        return {}

    # Step 2: pitcher hands (parallel) — _pitcher_hand is a /people call, works
    pitcher_ids = set()
    for game in games:
        for side in ('away', 'home'):
            p = game['teams'][side].get('probablePitcher', {})
            if p.get('id'):
                pitcher_ids.add(p['id'])

    hand_map = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_pitcher_hand, pid): pid for pid in pitcher_ids}
        for fut in as_completed(futs):
            pid = futs[fut]
            try:
                hand_map[pid] = fut.result()
            except Exception:
                hand_map[pid] = ''

    # Step 3: pull both Savant hand tables ONCE (2 calls for whole league)
    savant = {
        'R': _fetch_savant_hand_table('R'),
        'L': _fetch_savant_hand_table('L'),
    }
    if not savant['R'] and not savant['L']:
        print("   Savant returned no rows — splits unavailable")
        return {}

    # Step 4: for each batter on a team facing a known-hand starter, emit the
    # row matching that hand, keyed by normalized name.
    result = {}
    roster_cache = {}

    for game in games:
        away_team = game['teams']['away']
        home_team = game['teams']['home']
        away_id   = away_team['team']['id']
        home_id   = home_team['team']['id']
        away_p    = away_team.get('probablePitcher', {})
        home_p    = home_team.get('probablePitcher', {})

        # (pitcher_hand_faced, batter_team_id)
        matchups = []
        if away_p.get('id') and hand_map.get(away_p['id']):
            matchups.append((hand_map[away_p['id']], home_id))
        if home_p.get('id') and hand_map.get(home_p['id']):
            matchups.append((hand_map[home_p['id']], away_id))

        for pitcher_hand, batter_team_id in matchups:
            hand_table = savant.get(pitcher_hand, {})
            if not hand_table:
                continue
            if batter_team_id not in roster_cache:
                try:
                    rr = _http.get(f"{_MLB_API}/teams/{batter_team_id}/roster",
                        params={"rosterType": "active", "season": 2026}, timeout=10)
                    roster_cache[batter_team_id] = (
                        rr.json().get('roster', []) if rr.status_code == 200 else []
                    )
                except Exception:
                    roster_cache[batter_team_id] = []

            for p in roster_cache[batter_team_id]:
                if p.get('position', {}).get('type') == 'Pitcher':
                    continue
                person = p.get('person', {})
                pid    = person.get('id')
                pname  = person.get('fullName', '')
                if not pid or not pname:
                    continue
                stats = hand_table.get(pid)
                if not stats:
                    continue   # not a qualified hitter vs this hand
                result[_normalize(pname)] = {
                    'avg':   stats['avg'],
                    'ops':   stats['ops'],
                    'ab':    stats['ab'],
                    'k_pct': stats['k_pct'],
                    'hand':  pitcher_hand,
                }

    print(f"   MLB splits loaded: {len(result)} batters across {len(games)} games")
    _save_cache(result)
    return result
