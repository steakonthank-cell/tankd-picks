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


def _normalize(name: str) -> str:
    """Lowercase, strip accents, collapse spaces — same as scanner.normalize_name."""
    import unicodedata
    n = unicodedata.normalize('NFKD', name)
    n = ''.join(c for c in n if not unicodedata.combining(c))
    return n.lower().strip()


def _pitcher_hand(pitcher_id: int) -> str:
    """Return 'L' or 'R' for a pitcher, '' if unknown."""
    try:
        r = _http.get(f"{_MLB_API}/people/{pitcher_id}", timeout=8)
        if r.status_code == 200:
            return r.json().get('people', [{}])[0].get('pitchHand', {}).get('code', '')
    except Exception:
        pass
    return ''


def _batter_splits(player_id: int, hand: str) -> dict:
    """
    Return hitting splits for a batter vs the given pitcher hand ('L' or 'R').
    Keys: avg, ops, ab, k_pct (all floats/ints, 0 if missing).
    """
    sit = 'vr' if hand == 'R' else 'vl'
    try:
        r = _http.get(f"{_MLB_API}/people/{player_id}/stats",
            params={"stats": "statSplits", "sitCodes": sit,
                    "gameType": "R", "season": 2026},
            timeout=8)
        if r.status_code != 200:
            return {}
        splits = r.json().get('stats', [{}])[0].get('splits', [])
        if not splits:
            return {}
        s = splits[0].get('stat', {})
        ab  = int(s.get('atBats', 0) or 0)
        avg = float(s.get('avg', 0) or 0)
        ops = float(s.get('ops', 0) or 0)
        so  = int(s.get('strikeOuts', 0) or 0)
        pa  = int(s.get('plateAppearances', 0) or 0)
        k_pct = round(so / pa * 100, 1) if pa > 0 else 0.0
        return {'avg': avg, 'ops': ops, 'ab': ab, 'k_pct': k_pct}
    except Exception:
        return {}


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

def get_todays_splits(date_str: str = None) -> dict:
    """
    Build a lookup of every batter playing today → their splits vs today's
    opposing probable pitcher handedness.

    Args:
        date_str: 'YYYY-MM-DD', defaults to today.

    Returns:
        {
          normalized_player_name: {
            'avg':   float,   # batting average vs pitcher hand
            'ops':   float,   # OPS vs pitcher hand
            'ab':    int,     # at-bats vs pitcher hand this season
            'k_pct': float,   # strikeout % vs pitcher hand
            'hand':  str,     # 'L' or 'R' (opposing pitcher's throw hand)
          }
        }
    """
    cached = _load_cache()
    if cached is not None:
        print(f"   Using cached MLB splits ({len(cached)} batters)")
        return cached

    from datetime import date
    today = date_str or date.today().strftime('%Y-%m-%d')
    print(f"   Fetching MLB splits for {today}...")

    # Step 1: today's schedule with probable pitchers
    try:
        r = _http.get(f"{_MLB_API}/schedule",
            params={"sportId": 1, "date": today,
                    "hydrate": "team,probablePitcher"},
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

    result = {}

    for game in games:
        away_team = game['teams']['away']
        home_team = game['teams']['home']
        away_id   = away_team['team']['id']
        home_id   = home_team['team']['id']

        away_pitcher = away_team.get('probablePitcher', {})
        home_pitcher = home_team.get('probablePitcher', {})

        # Away pitcher faces home batters; home pitcher faces away batters
        matchups = []
        if away_pitcher.get('id'):
            hand = _pitcher_hand(away_pitcher['id'])
            if hand:
                matchups.append({'pitcher_hand': hand, 'batter_team_id': home_id,
                                 'pitcher_name': away_pitcher.get('fullName','')})
        if home_pitcher.get('id'):
            hand = _pitcher_hand(home_pitcher['id'])
            if hand:
                matchups.append({'pitcher_hand': hand, 'batter_team_id': away_id,
                                 'pitcher_name': home_pitcher.get('fullName','')})

        for matchup in matchups:
            batter_team_id = matchup['batter_team_id']
            pitcher_hand   = matchup['pitcher_hand']

            # Get team roster
            try:
                r_roster = _http.get(f"{_MLB_API}/teams/{batter_team_id}/roster",
                    params={"rosterType": "active", "season": 2026}, timeout=10)
                if r_roster.status_code != 200:
                    continue
                roster = r_roster.json().get('roster', [])
            except Exception:
                continue

            batters = [p for p in roster
                       if p.get('position', {}).get('type') != 'Pitcher']

            for batter in batters:
                bid  = batter['person']['id']
                bname = batter['person']['fullName']
                splits = _batter_splits(bid, pitcher_hand)
                if not splits:
                    continue
                splits['hand'] = pitcher_hand
                result[_normalize(bname)] = splits

    print(f"   MLB splits loaded: {len(result)} batters across {len(games)} games")
    _save_cache(result)
    return result


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
                    "hydrate": "team,probablePitcher"},
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

    for game in games:
        away        = game['teams']['away']
        home        = game['teams']['home']
        away_id     = away['team']['id']
        home_id     = home['team']['id']
        away_name   = away['team']['name']
        home_name   = home['team']['name']
        away_pitcher = away.get('probablePitcher', {})
        home_pitcher = home.get('probablePitcher', {})

        # Home batters face the away starter
        if away_pitcher.get('id'):
            p_stats = _pitcher_season_stats(away_pitcher['id'])
            if p_stats:
                try:
                    r2 = _http.get(f"{_MLB_API}/teams/{home_id}/roster",
                        params={"rosterType": "active", "season": 2026}, timeout=10)
                    if r2.status_code == 200:
                        for p in r2.json().get('roster', []):
                            if p.get('position', {}).get('type') != 'Pitcher':
                                batter_matchups[_normalize(p['person']['fullName'])] = {
                                    **p_stats,
                                    'opp_pitcher': away_pitcher.get('fullName', ''),
                                }
                except Exception:
                    pass

        # Away batters face the home starter
        if home_pitcher.get('id'):
            p_stats = _pitcher_season_stats(home_pitcher['id'])
            if p_stats:
                try:
                    r3 = _http.get(f"{_MLB_API}/teams/{away_id}/roster",
                        params={"rosterType": "active", "season": 2026}, timeout=10)
                    if r3.status_code == 200:
                        for p in r3.json().get('roster', []):
                            if p.get('position', {}).get('type') != 'Pitcher':
                                batter_matchups[_normalize(p['person']['fullName'])] = {
                                    **p_stats,
                                    'opp_pitcher': home_pitcher.get('fullName', ''),
                                }
                except Exception:
                    pass

        # Home pitcher faces the away lineup
        if home_pitcher.get('id'):
            t_stats = _team_hitting_stats(away_id)
            if t_stats:
                pitcher_matchups[_normalize(home_pitcher.get('fullName', ''))] = {
                    'team_ops':   t_stats['ops'],
                    'team_avg':   t_stats['avg'],
                    'team_k_pct': t_stats['k_pct'],
                    'opp_team':   away_name,
                }

        # Away pitcher faces the home lineup
        if away_pitcher.get('id'):
            t_stats = _team_hitting_stats(home_id)
            if t_stats:
                pitcher_matchups[_normalize(away_pitcher.get('fullName', ''))] = {
                    'team_ops':   t_stats['ops'],
                    'team_avg':   t_stats['avg'],
                    'team_k_pct': t_stats['k_pct'],
                    'opp_team':   home_name,
                }

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
