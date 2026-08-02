"""
Nightly refresh of the Sim Explorer / prop-model training data.

Two stages, run in sequence (mirrors src/cli/mlb_cli.py's "Build Data" then
"Engineer Features" menu options — same underlying functions, just chained
non-interactively for cron):

  1. src.sports.mlb.builder — downloads batter/pitcher game logs from the
     MLB Stats API into data/mlb/raw/{batting,pitching}_logs.csv. Defaults
     to incremental (added 2026-08-02): only the current season is
     re-fetched for players already on file, full backfill for new ones —
     see builder.py's module docstring. Pass --full on this script's own
     command line for an occasional full re-pull of every tracked season
     (intended as a separate monthly cron entry, not the nightly default —
     see the reconciliation entry in the crontab).
  2. src.sports.mlb.features — rebuilds the rolling-average training CSVs
     (data/mlb/processed/{batter,pitcher}_training.csv) from those raw logs.
     Pure pandas, no network calls, fast.

Without this, batter_training.csv/pitcher_training.csv silently stop
advancing (they previously sat stuck at 2026-06-15 because this refresh had
never been scheduled), which is what blocked grading the Sim Explorer's
Monte Carlo output against any game after that date.

Sanity floor (2026-07-28 incident): builder.py's per-player gameLog fetch
went through a sustained MLB-side degradation (~95% of calls 406ing) that
silently collapsed pitcher_training.csv/batter_training.csv from 619/523
unique players to 183/246 over three weeks, because nothing checked the
rebuilt file against what was there before writing over it. builder.py now
merges instead of overwriting (see its module docstring), which closes the
original hole, but this script adds a second, independent safety net at the
processed-CSV layer: before Stage 2 overwrites batter/pitcher_training.csv,
the current file is backed up; after, if the rebuilt file's row count or
unique-player count dropped by more than SANITY_DROP_THRESHOLD vs. the
backup, the backup is restored (the bad rebuild is discarded) and an alert
is sent to Discord instead of silently shipping a thinner file.

Usage:
    .venv/bin/python scripts/refresh_training_data.py            # incremental
    .venv/bin/python scripts/refresh_training_data.py --full     # full re-pull
"""
import sys
import os
import shutil
import json
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")

_ET = ZoneInfo("America/New_York")

PROCESSED_FILES = {
    "batter":  "data/mlb/processed/batter_training.csv",
    "pitcher": "data/mlb/processed/pitcher_training.csv",
}
SANITY_DROP_THRESHOLD = 0.5  # refuse the rebuild if rows OR unique players drop more than this fraction


def _counts(path):
    import pandas as pd
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, low_memory=False)
    return {"rows": len(df), "players": df["player_id"].nunique() if "player_id" in df.columns else 0}


def _alert_discord(message):
    webhook = os.getenv("MLB_PITCHER_WEBHOOK")
    if not webhook:
        print("   (MLB_PITCHER_WEBHOOK not set in .env -- skipping Discord alert)")
        return
    try:
        req = Request(webhook, json.dumps({"content": message}).encode(),
                      headers={"Content-Type": "application/json", "User-Agent": "TankdPicks/1.0"})
        urlopen(req, timeout=10)
    except Exception as e:
        print(f"   (Discord alert failed to send: {e})")


def main():
    full = "--full" in sys.argv
    started = datetime.now(_ET)
    mode = "FULL RE-PULL" if full else "incremental"
    print(f"=== Training data refresh starting {started.strftime('%Y-%m-%d %H:%M:%S %Z')} ({mode}) ===")

    before = {name: _counts(path) for name, path in PROCESSED_FILES.items()}
    backups = {}
    for name, path in PROCESSED_FILES.items():
        if os.path.exists(path):
            backup_path = path + ".pre_refresh_backup"
            shutil.copy2(path, backup_path)
            backups[name] = backup_path

    print(f"\n--- Stage 1/2: downloading game logs (src.sports.mlb.builder, {mode}) ---")
    from src.sports.mlb.builder import fetch_batting_logs, fetch_pitching_logs
    fetch_batting_logs(incremental=not full)
    fetch_pitching_logs(incremental=not full)

    print("\n--- Stage 2/2: building rolling-average features (src.sports.mlb.features) ---")
    from src.sports.mlb.features import main as features_main
    features_main()

    finished = datetime.now(_ET)
    print(f"\n=== Done {finished.strftime('%Y-%m-%d %H:%M:%S %Z')} "
          f"(elapsed {(finished - started).total_seconds():.0f}s) ===")

    print("\n--- Sanity check vs. pre-refresh counts ---")
    any_reverted = False
    for name, path in PROCESSED_FILES.items():
        after = _counts(path)
        b = before.get(name)
        if b is None or after is None or b["rows"] == 0:
            print(f"   {name}: no prior baseline to compare against, skipping sanity check "
                  f"({after['rows'] if after else 0} rows now)")
            continue

        row_drop = 1 - (after["rows"] / b["rows"]) if b["rows"] else 0
        player_drop = 1 - (after["players"] / b["players"]) if b["players"] else 0
        print(f"   {name}: rows {b['rows']:,} -> {after['rows']:,} ({row_drop:+.0%}), "
              f"players {b['players']:,} -> {after['players']:,} ({player_drop:+.0%})")

        if row_drop > SANITY_DROP_THRESHOLD or player_drop > SANITY_DROP_THRESHOLD:
            any_reverted = True
            backup_path = backups.get(name)
            print(f"   ⚠️  {name}: drop exceeds {SANITY_DROP_THRESHOLD:.0%} threshold -- "
                  f"REVERTING to pre-refresh backup, NOT keeping the rebuilt file.")
            if backup_path and os.path.exists(backup_path):
                shutil.copy2(backup_path, path)
            _alert_discord(
                f"🚨 MLB training data refresh REVERTED for {name}_training.csv: "
                f"rows {b['rows']:,}→{after['rows']:,} ({row_drop:+.0%}), "
                f"players {b['players']:,}→{after['players']:,} ({player_drop:+.0%}). "
                f"Kept the pre-refresh version instead. Check builder.py's failed-player-season "
                f"count in refresh_training_data.log for the likely cause."
            )
        else:
            # healthy run -- drop the backup so it doesn't accumulate forever
            backup_path = backups.get(name)
            if backup_path and os.path.exists(backup_path):
                os.remove(backup_path)

    if not any_reverted:
        import pandas as pd
        bdf = pd.read_csv(PROCESSED_FILES["batter"])
        pdf = pd.read_csv(PROCESSED_FILES["pitcher"])
        print(f"batter_training.csv now covers through {bdf['date'].max()}")
        print(f"pitcher_training.csv now covers through {pdf['date'].max()}")


if __name__ == "__main__":
    main()
