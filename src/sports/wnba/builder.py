"""
WNBA Historical Data Builder

Downloads raw game logs for all WNBA players via nba_api (official stats.wnba.com,
free, no key required). Uses the same data source as PickFinder's hit-rate calculations.

Output:
    data/wnba/raw/raw_game_logs.csv      — player box scores (all seasons)
    data/wnba/processed/player_positions.csv — player positions

Seasons pulled: 2020–2025 (configurable in config.py)

Usage:
    $ python3 -m src.sports.wnba.builder
"""

import os
import time
import pandas as pd
from nba_api.stats.endpoints import playergamelogs, commonallplayers
from nba_api.stats.endpoints import commonteamroster

from src.sports.wnba.config import SEASONS

BASE_DIR         = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_DIR          = os.path.join(BASE_DIR, 'data', 'wnba', 'raw')
PROCESSED_DIR    = os.path.join(BASE_DIR, 'data', 'wnba', 'processed')
RAW_LOG_FILE     = os.path.join(RAW_DIR,       'raw_game_logs.csv')
POSITION_FILE    = os.path.join(PROCESSED_DIR, 'player_positions.csv')

WNBA_LEAGUE_ID = '10'
API_DELAY      = 1.2   # seconds between requests (WNBA API is stricter)


def fetch_game_logs():
    """
    Download WNBA box scores for all players across all configured seasons.

    Output: data/wnba/raw/raw_game_logs.csv
    """
    os.makedirs(RAW_DIR, exist_ok=True)
    all_logs = []

    print(f"\n{'='*55}")
    print(f"   WNBA DATA BUILDER")
    print(f"{'='*55}")
    print(f"   Seasons: {SEASONS}")
    print(f"   This takes 5-10 minutes on first run.\n")

    for season in SEASONS:
        for attempt in range(4):
            try:
                if attempt > 0:
                    print(f"   Retry {attempt}/3 for {season}...")
                    time.sleep(5 * attempt)
                else:
                    print(f"   Fetching {season}...", end='', flush=True)

                logs = playergamelogs.PlayerGameLogs(
                    season_nullable=season,
                    league_id_nullable=WNBA_LEAGUE_ID,
                    season_type_nullable='Regular Season',
                    timeout=45,
                )
                df = logs.get_data_frames()[0]
                if df.empty:
                    print(f" (no data)")
                    break
                df['SEASON_ID'] = season
                all_logs.append(df)
                print(f" {len(df):,} rows")
                time.sleep(API_DELAY)
                break
            except Exception as e:
                if attempt == 3:
                    print(f" FAILED: {e}")
                    break

    if not all_logs:
        print("\n❌  No data fetched. Check internet connection and nba_api version.")
        return

    combined = pd.concat(all_logs, ignore_index=True)
    combined['GAME_DATE'] = pd.to_datetime(combined['GAME_DATE'], errors='coerce')
    combined = combined.sort_values(['PLAYER_ID', 'GAME_DATE']).reset_index(drop=True)

    os.makedirs(RAW_DIR, exist_ok=True)
    combined.to_csv(RAW_LOG_FILE, index=False)
    print(f"\n   ✅  Saved {len(combined):,} rows to {RAW_LOG_FILE}")
    print(f"   Players: {combined['PLAYER_ID'].nunique():,}")
    print(f"   Date range: {combined['GAME_DATE'].min().date()} → {combined['GAME_DATE'].max().date()}")


def fetch_player_positions():
    """
    Pull position data for WNBA players from active team rosters.

    Output: data/wnba/processed/player_positions.csv
    """
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # WNBA team IDs (stable across seasons)
    WNBA_TEAM_IDS = [
        1611661313,  # Atlanta Dream
        1611661314,  # Chicago Sky
        1611661315,  # Connecticut Sun
        1611661316,  # Dallas Wings
        1611661317,  # Indiana Fever
        1611661318,  # Las Vegas Aces
        1611661319,  # Los Angeles Sparks
        1611661320,  # Minnesota Lynx
        1611661321,  # New York Liberty
        1611661322,  # Phoenix Mercury
        1611661323,  # Seattle Storm
        1611661324,  # Washington Mystics
    ]

    all_positions = []
    print(f"\n   Fetching positions from {len(WNBA_TEAM_IDS)} WNBA team rosters...")

    for team_id in WNBA_TEAM_IDS:
        for attempt in range(3):
            try:
                roster = commonteamroster.CommonTeamRoster(
                    team_id=team_id,
                    league_id=WNBA_LEAGUE_ID,
                    timeout=20,
                )
                df = roster.get_data_frames()[0]
                if not df.empty:
                    df = df[['PLAYER_ID', 'POSITION']].copy()
                    all_positions.append(df)
                time.sleep(API_DELAY)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"   ⚠️  Team {team_id} failed: {e}")
                time.sleep(2)

    if not all_positions:
        print("   ⚠️  No position data fetched.")
        return

    positions = pd.concat(all_positions, ignore_index=True).drop_duplicates('PLAYER_ID')
    positions.to_csv(POSITION_FILE, index=False)
    print(f"   ✅  Saved {len(positions)} player positions to {POSITION_FILE}")


def main():
    fetch_game_logs()
    fetch_player_positions()
    print("\n✅  WNBA data build complete!")
    print("   Next: python3 -m src.sports.wnba.features  (engineer features)")
    print("   Then: python3 -m src.sports.wnba.train     (train models)")


if __name__ == '__main__':
    main()
