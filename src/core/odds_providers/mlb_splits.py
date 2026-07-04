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

# statSplits is prone to bursty stretches of transient 406s (see _batter_splits).
# Retries use exponential backoff: 2s, 4s, 8s, 16s, 16s (capped) between attempts.
SPLITS_MAX_ATTEMPTS  = 6
SPLITS_RETRY_BACKOFF = 2      # seconds; doubles each attempt, capped below
SPLITS_RETRY_CAP     = 16     # seconds

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


def _batter_splits(player_id: int, hand: str):
    """
    Return this season's hitting split for one batter vs one pitcher hand
    ('L' or 'R') from the official MLB Stats API. Keys: avg, ops, ab (=PA), k_pct.

    sportId=1 is required — omitting it 406s, and so does adding gameType=R
    (undocumented, but confirmed by direct testing: same query 200s without
    it, 406s with it). That combination is what made this call look "broken"
    and got it replaced (see get_todays_splits) with a Baseball Savant
    leaderboard pull whose pitch_hand filter turned out to be a silent no-op
    instead.

    Return contract: `None` means the lookup failed (HTTP error, timeout,
    malformed response) — the caller should retry/report this, NOT treat it
    as "no split". `{}` means MLB responded but has no statSplits rows for
    this player/hand, i.e. a confirmed zero-PA case. This distinction matters:
    MLB's statSplits endpoint is prone to transient 406s, and collapsing a
    failed call into "no data" makes an API outage indistinguishable from a
    real absence of stats on the board (e.g. everyday players silently
    showing blank vs-hand splits during an outage).
    """
    sit = 'vr' if hand == 'R' else 'vl'
    try:
        r = _http.get(f"{_MLB_API}/people/{player_id}/stats",
            params={"stats": "statSplits", "sitCodes": sit,
                    "group": "hitting", "season": 2026, "sportId": 1},
            timeout=8)
        if r.status_code != 200:
            return None
        splits = r.json().get('stats', [{}])[0].get('splits', [])
        if not splits:
            return {}
        s   = splits[0].get('stat', {})
        pa  = int(s.get('plateAppearances', 0) or 0)
        avg = float(s.get('avg', 0) or 0)
        ops = float(s.get('ops', 0) or 0)
        so  = int(s.get('strikeOuts', 0) or 0)
        k_pct = round(so / pa * 100, 1) if pa > 0 else 0.0
        return {'avg': avg, 'ops': ops, 'ab': pa, 'k_pct': k_pct}
    except Exception:
        return None


def get_todays_splits(date_str: str = None) -> dict:
    """
    Build a lookup of every batter playing today -> their season splits vs the
    handedness of today's opposing probable pitcher.

    Data source: MLB Stats API statSplits (sitCodes=vl/vr), one call per
    batter, parallelized. Previously used a Baseball Savant custom-leaderboard
    pull instead, but its pitch_hand filter was a silent no-op — filter=
    pitch_hand|L, filter=pitch_hand|R, and no filter at all all returned the
    same combined-season row (verified against Sal Stewart, id 701398:
    pa=374/avg=.257 in every case — his combined total, not a single-hand
    split — vs. the real vs-LHP split of pa=93/avg=.282 from this endpoint).

    Return contract (unchanged):
        { normalized_name: {'avg','ops','ab','k_pct','hand'} }
    """
    cached = _load_cache()
    if cached is not None:
        print(f"   Using cached MLB splits ({len(cached)} batters)")
        return cached

    from datetime import date
    today = date_str or date.today().strftime('%Y-%m-%d')
    print(f"   Fetching MLB splits for {today} (source: MLB Stats API statSplits)...")

    # Step 1: today's schedule + probable pitchers
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

    # Step 2: pitcher hands (parallel)
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

    # Step 3: gather (player_id, name, hand-they-face) for every batter on a
    # team whose opposing starter's hand is known.
    roster_cache = {}
    batter_jobs = []

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
                batter_jobs.append((pid, pname, pitcher_hand))

    # Step 4: fetch each batter's split vs the hand they actually face today,
    # in parallel — one call per batter. `_batter_splits` returns None on a
    # failed lookup (as opposed to {} for a confirmed zero-PA case), so those
    # are retried a couple of times before being given up on — that keeps a
    # transient 406/timeout from silently rendering as "no split" on the board.
    def _run_batch(jobs):
        out = {}
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = {ex.submit(_batter_splits, pid, hand): (pid, pname, hand)
                    for pid, pname, hand in jobs}
            for fut in as_completed(futs):
                job = futs[fut]
                try:
                    out[job] = fut.result()
                except Exception:
                    out[job] = None
        return out

    result  = {}
    pending = list(batter_jobs)
    failed  = []   # jobs that returned None after all retries

    for attempt in range(SPLITS_MAX_ATTEMPTS):
        if not pending:
            break
        outcomes = _run_batch(pending)
        pending = []
        for (pid, pname, hand), stats in outcomes.items():
            if stats is None:
                pending.append((pid, pname, hand))
                continue
            if not stats.get('ab'):
                continue   # confirmed 0 PA vs this hand this season
            result[_normalize(pname)] = {
                'avg':   stats['avg'],
                'ops':   stats['ops'],
                'ab':    stats['ab'],
                'k_pct': stats['k_pct'],
                'hand':  hand,
            }
        if pending and attempt < SPLITS_MAX_ATTEMPTS - 1:
            delay = min(SPLITS_RETRY_BACKOFF * (2 ** attempt), SPLITS_RETRY_CAP)
            print(f"   MLB splits: {len(pending)} lookups failed, "
                  f"retrying in {delay}s (attempt {attempt + 2}/{SPLITS_MAX_ATTEMPTS})...")
            time.sleep(delay)

    if pending:
        failed = [pname for _, pname, _ in pending]
        print(f"   MLB splits: {len(failed)} lookups still failing after retries "
              f"(not the same as 'no data' — API errored): {', '.join(failed)}")

    print(f"   MLB splits loaded: {len(result)} batters across {len(games)} games")
    _save_cache(result)
    return result
