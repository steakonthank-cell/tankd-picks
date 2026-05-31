"""
MLB Historical Data Collection

Downloads batter and pitcher game logs from the MLB Stats API (free, no key).
Fetches game-by-game stats for all active players across multiple seasons.

Data Source:
    statsapi.mlb.com/api/v1  (official MLB Stats API, no auth required)

Output Files:
    data/mlb/raw/batting_logs.csv   - batter game-by-game stats
    data/mlb/raw/pitching_logs.csv  - pitcher game-by-game stats

Usage:
    $ python3 -m src.sports.mlb.builder

Performance:
    ~10-15 minutes first run (thousands of API calls with rate limiting)
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime

BASE_URL = "https://statsapi.mlb.com/api/v1"
SEASONS  = [2022, 2023, 2024, 2025, 2026]

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_DIR      = os.path.join(BASE_DIR, 'data', 'mlb', 'raw')
BATTING_FILE  = os.path.join(RAW_DIR, 'batting_logs.csv')
PITCHING_FILE = os.path.join(RAW_DIR, 'pitching_logs.csv')


def _get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(1.5 ** attempt)
    return None


def get_active_players(season):
    data = _get(f"{BASE_URL}/sports/1/players", {'season': season})
    if not data:
        return []
    return data.get('people', [])


def get_game_logs(player_id, season, group):
    data = _get(f"{BASE_URL}/people/{player_id}/stats", {
        'stats':    'gameLog',
        'group':    group,
        'season':   season,
        'gameType': 'R',
    })
    if not data:
        return []
    stats = data.get('stats', [])
    if not stats:
        return []
    return stats[0].get('splits', [])


def _ip_to_outs(ip_str):
    try:
        parts = str(ip_str).split('.')
        whole = int(parts[0])
        frac  = int(parts[1]) if len(parts) > 1 else 0
        return whole * 3 + frac
    except Exception:
        return 0


def fetch_batting_logs():
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"\n--- DOWNLOADING BATTING LOGS ({min(SEASONS)}-{max(SEASONS)}) ---")

    players = get_active_players(SEASONS[-1])
    # Filter out pitchers for batting logs
    batters = [p for p in players
               if p.get('primaryPosition', {}).get('code', '') not in ('1',)]
    print(f"   {len(batters)} position players found in {SEASONS[-1]} roster")

    all_rows = []
    total = len(batters) * len(SEASONS)
    done  = 0

    for season in SEASONS:
        season_rows = 0
        for player in batters:
            done += 1
            if done % 100 == 0:
                print(f"   Progress: {done}/{total} ({100*done//total}%)  rows so far: {len(all_rows):,}", end='\r')

            splits = get_game_logs(player['id'], season, 'hitting')
            for s in splits:
                stat = s.get('stat', {})
                ab   = stat.get('atBats', 0)
                if ab == 0:
                    continue
                hits    = stat.get('hits', 0)
                doubles = stat.get('doubles', 0)
                triples = stat.get('triples', 0)
                hr      = stat.get('homeRuns', 0)
                tb      = stat.get('totalBases', hits + doubles + 2*triples + 3*hr)

                all_rows.append({
                    'player_id':   player['id'],
                    'player_name': player.get('fullName', ''),
                    'date':        s.get('date', ''),
                    'season':      season,
                    'is_home':     1 if s.get('isHome', False) else 0,
                    'opponent_id': s.get('opponent', {}).get('id', 0),
                    'team_id':     s.get('team', {}).get('id', 0),
                    'H':           hits,
                    'TB':          tb,
                    'HR':          hr,
                    'RBI':         stat.get('rbi', 0),
                    'R':           stat.get('runs', 0),
                    'SO':          stat.get('strikeOuts', 0),
                    'BB':          stat.get('baseOnBalls', 0),
                    'AB':          ab,
                    'PA':          stat.get('plateAppearances', ab),
                    'SB':          stat.get('stolenBases', 0),
                    '2B':          doubles,
                    '3B':          triples,
                })
                season_rows += 1

            time.sleep(0.08)

        print(f"\n   Season {season}: {season_rows:,} game rows")

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("WARNING: No batting data collected.")
        return df

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.sort_values(['player_id', 'date']).reset_index(drop=True)
    df.to_csv(BATTING_FILE, index=False)
    print(f"\n✅  Batting logs saved: {len(df):,} rows → {BATTING_FILE}")
    print(f"    Players: {df['player_name'].nunique():,}")
    print(f"    Date range: {df['date'].min().date()} → {df['date'].max().date()}")
    return df


def fetch_pitching_logs():
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"\n--- DOWNLOADING PITCHING LOGS ({min(SEASONS)}-{max(SEASONS)}) ---")

    players = get_active_players(SEASONS[-1])
    # Pitchers + two-way players
    pitchers = [p for p in players
                if p.get('primaryPosition', {}).get('code', '') in ('1', 'TWP')]
    print(f"   {len(pitchers)} pitchers found in {SEASONS[-1]} roster")

    all_rows = []
    total = len(pitchers) * len(SEASONS)
    done  = 0

    for season in SEASONS:
        season_rows = 0
        for player in pitchers:
            done += 1
            if done % 50 == 0:
                print(f"   Progress: {done}/{total} ({100*done//total}%)  rows so far: {len(all_rows):,}", end='\r')

            splits = get_game_logs(player['id'], season, 'pitching')
            for s in splits:
                stat = s.get('stat', {})
                ip   = stat.get('inningsPitched', '0.0')
                outs = _ip_to_outs(ip)
                if outs == 0:
                    continue

                all_rows.append({
                    'player_id':   player['id'],
                    'player_name': player.get('fullName', ''),
                    'date':        s.get('date', ''),
                    'season':      season,
                    'is_home':     1 if s.get('isHome', False) else 0,
                    'opponent_id': s.get('opponent', {}).get('id', 0),
                    'team_id':     s.get('team', {}).get('id', 0),
                    'is_starter':  1 if stat.get('gamesStarted', 0) > 0 else 0,
                    'K':           stat.get('strikeOuts', 0),
                    'ER':          stat.get('earnedRuns', 0),
                    'OUTS':        outs,
                    'HA':          stat.get('hits', 0),
                    'BBA':         stat.get('baseOnBalls', 0),
                    'HR_A':        stat.get('homeRuns', 0),
                    'pitches':     stat.get('numberOfPitches', 0),
                    'batters_faced': stat.get('battersFaced', 0),
                })
                season_rows += 1

            time.sleep(0.08)

        print(f"\n   Season {season}: {season_rows:,} game rows")

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("WARNING: No pitching data collected.")
        return df

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.sort_values(['player_id', 'date']).reset_index(drop=True)
    df.to_csv(PITCHING_FILE, index=False)
    print(f"\n✅  Pitching logs saved: {len(df):,} rows → {PITCHING_FILE}")
    print(f"    Pitchers: {df['player_name'].nunique():,}")
    print(f"    Date range: {df['date'].min().date()} → {df['date'].max().date()}")
    return df


if __name__ == "__main__":
    print("=" * 55)
    print("   ⚾ MLB DATA BUILDER")
    print("=" * 55)
    fetch_batting_logs()
    fetch_pitching_logs()
    print("\n" + "=" * 55)
    print("✅  BUILD COMPLETE")
    print("   Next: Run features.py → train.py")
    print("=" * 55)
