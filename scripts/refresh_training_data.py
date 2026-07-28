"""
Nightly refresh of the Sim Explorer / prop-model training data.

Two stages, run in sequence (mirrors src/cli/mlb_cli.py's "Build Data" then
"Engineer Features" menu options — same underlying functions, just chained
non-interactively for cron):

  1. src.sports.mlb.builder — re-downloads batter/pitcher game logs from the
     MLB Stats API (full re-pull across all tracked seasons, not
     incremental; this is the existing script's only mode) into
     data/mlb/raw/{batting,pitching}_logs.csv.
  2. src.sports.mlb.features — rebuilds the rolling-average training CSVs
     (data/mlb/processed/{batter,pitcher}_training.csv) from those raw logs.
     Pure pandas, no network calls, fast.

Without this, batter_training.csv/pitcher_training.csv silently stop
advancing (they previously sat stuck at 2026-06-15 because this refresh had
never been scheduled), which is what blocked grading the Sim Explorer's
Monte Carlo output against any game after that date.

Usage: .venv/bin/python scripts/refresh_training_data.py
"""
import sys
import os
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")

_ET = ZoneInfo("America/New_York")


def main():
    started = datetime.now(_ET)
    print(f"=== Training data refresh starting {started.strftime('%Y-%m-%d %H:%M:%S %Z')} ===")

    print("\n--- Stage 1/2: downloading game logs (src.sports.mlb.builder) ---")
    from src.sports.mlb.builder import fetch_batting_logs, fetch_pitching_logs
    fetch_batting_logs()
    fetch_pitching_logs()

    print("\n--- Stage 2/2: building rolling-average features (src.sports.mlb.features) ---")
    from src.sports.mlb.features import main as features_main
    features_main()

    finished = datetime.now(_ET)
    print(f"\n=== Done {finished.strftime('%Y-%m-%d %H:%M:%S %Z')} "
          f"(elapsed {(finished - started).total_seconds():.0f}s) ===")

    import pandas as pd
    bdf = pd.read_csv("data/mlb/processed/batter_training.csv")
    pdf = pd.read_csv("data/mlb/processed/pitcher_training.csv")
    print(f"batter_training.csv now covers through {bdf['date'].max()}")
    print(f"pitcher_training.csv now covers through {pdf['date'].max()}")


if __name__ == "__main__":
    main()
