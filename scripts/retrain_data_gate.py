#!/usr/bin/env python3
"""
Data-readiness hard gate for MLB model retraining.

Refuses to let a retrain proceed against corrupted or collapsed training
data. Built after the 2026-07-28 incident where pitcher_training.csv /
batter_training.csv silently collapsed from 619/523 to 183/246 unique
players over three weeks -- a sustained MLB gameLog API outage that the
row-count-and-date-range check in that incident's own audit missed
entirely, because row count and date range both still looked plausible
even as unique-player coverage quietly fell apart (see CLAUDE.md's
postmortem). That incident already added a same-day relative drop-guard
to the nightly refresh (SANITY_DROP_THRESHOLD in refresh_training_data.py,
0.5 = refuse if today's rebuild drops more than 50% vs. yesterday's file).

This is a second, independent gate, run immediately before a retrain
(not nightly): it checks unique-player coverage against a ratcheting
known-good baseline rather than only "did today look like yesterday" --
so a slow multi-day decay that never trips the 50%-in-one-day nightly
guard still can't reach a model that ships to production. The baseline
self-updates (upward only) on every PASS, seeded from the 2026-07-28
post-recovery numbers (709 pitchers / 561 batters) on first run.

Checks:
  1. Required files exist with the expected schema.
  2. Unique player_id coverage >= FLOOR_FRACTION of the recorded baseline.
  3. Recency: most recent game date isn't stale (accounts for the
     All-Star break -- MLB has multi-day real gaps, not just outages).
  4. Rows-per-player hasn't collapsed (same player count, thinner history
     each -- a different failure mode than a player-count drop).

Usage:
    python3 scripts/retrain_data_gate.py
    Exit 0 = clear to retrain. Exit 1 = refuse; do not proceed.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")

import pandas as pd  # noqa: E402

PITCHER_FILE = "data/mlb/processed/pitcher_training.csv"
BATTER_FILE = "data/mlb/processed/batter_training.csv"
BASELINE_FILE = "data/mlb/processed/.retrain_baseline.json"

# Seed values if no baseline file exists yet -- the exact post-recovery
# counts confirmed in the 2026-07-28 postmortem, the last time these files
# were known-good end to end.
SEED_BASELINE = {"pitchers": 709, "batters": 561}

# Refuse if unique-player coverage falls below this fraction of the
# recorded baseline. Deliberately tighter than the nightly refresh's 0.5
# guard -- this gate stands between the data and a model that ships, so
# it should trip well before a repeat of the 74% player-count collapse
# (619->183 pitchers) the 2026-07-28 incident actually produced.
FLOOR_FRACTION = 0.85

# Rows-per-player shouldn't collapse either (same player count, thinner
# history each -- a different symptom than a player-count drop). Same
# floor fraction, applied to the average rows/player ratio.
ROWS_PER_PLAYER_FLOOR_FRACTION = 0.85

# Most recent game date should be within this many days of "today" the
# gate is run. Generous enough to cross the All-Star break (a real
# multi-day gap, not an outage) without masking a stalled nightly refresh.
MAX_STALENESS_DAYS = 5

REQUIRED_COLS = {"player_id", "player_name", "date", "season"}


def _load_baseline():
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return dict(SEED_BASELINE)


def _save_baseline(baseline):
    os.makedirs(os.path.dirname(BASELINE_FILE), exist_ok=True)
    with open(BASELINE_FILE, "w") as f:
        json.dump(baseline, f, indent=2)


def _check_file(label, path, baseline_key, baseline):
    issues = []
    if not os.path.exists(path):
        return None, [f"{label}: file not found at {path}"]

    df = pd.read_csv(path, low_memory=False)

    missing_cols = REQUIRED_COLS - set(df.columns)
    if missing_cols:
        issues.append(f"{label}: missing required column(s): {sorted(missing_cols)}")
        return None, issues  # can't evaluate further without these columns

    n_players = df["player_id"].nunique()
    n_rows = len(df)
    rows_per_player = n_rows / n_players if n_players else 0

    floor = baseline[baseline_key] * FLOOR_FRACTION
    if n_players < floor:
        issues.append(
            f"{label}: unique players {n_players} is below the {FLOOR_FRACTION:.0%} floor "
            f"({floor:.0f}, baseline={baseline[baseline_key]}) -- looks like the "
            f"2026-07-28-style collapse. Do NOT retrain on this data."
        )

    baseline_rpp = baseline.get(f"{baseline_key}_rows_per_player")
    if baseline_rpp:
        rpp_floor = baseline_rpp * ROWS_PER_PLAYER_FLOOR_FRACTION
        if rows_per_player < rpp_floor:
            issues.append(
                f"{label}: rows/player {rows_per_player:.1f} is below the "
                f"{ROWS_PER_PLAYER_FLOOR_FRACTION:.0%} floor ({rpp_floor:.1f}, "
                f"baseline={baseline_rpp:.1f}) -- same player count but thinner history "
                f"per player than expected."
            )

    max_date = pd.to_datetime(df["date"]).max()
    staleness_days = (datetime.now() - max_date.to_pydatetime()).days
    if staleness_days > MAX_STALENESS_DAYS:
        issues.append(
            f"{label}: most recent date is {max_date.date()}, {staleness_days} days old "
            f"(floor: {MAX_STALENESS_DAYS} days) -- nightly refresh may be stalled."
        )

    stats = {
        "players": n_players,
        "rows": n_rows,
        "rows_per_player": rows_per_player,
        "max_date": str(max_date.date()),
        "staleness_days": staleness_days,
    }
    return stats, issues


def main():
    baseline = _load_baseline()
    print(f"Baseline (from {BASELINE_FILE if os.path.exists(BASELINE_FILE) else 'seed defaults'}): {baseline}\n")

    all_issues = []
    results = {}

    for label, path, key in [
        ("Pitchers", PITCHER_FILE, "pitchers"),
        ("Batters", BATTER_FILE, "batters"),
    ]:
        print("=" * 70)
        print(f"CHECK: {label} ({path})")
        print("=" * 70)
        stats, issues = _check_file(label, path, key, baseline)
        results[key] = stats
        if stats:
            print(
                f"  players={stats['players']}  rows={stats['rows']}  "
                f"rows/player={stats['rows_per_player']:.1f}  "
                f"max_date={stats['max_date']} ({stats['staleness_days']}d old)"
            )
        if issues:
            all_issues.extend(issues)
            for it in issues:
                print(f"  FAIL: {it}")
        else:
            print("  OK")
        print()

    print("=" * 70)
    if all_issues:
        print(f"FAIL -- {len(all_issues)} issue(s). Retrain is refused.")
        for it in all_issues:
            print(f"  - {it}")
        sys.exit(1)

    # Ratchet the baseline forward only on a clean pass, and only upward --
    # a failing run must never lower the floor for next time.
    updated = dict(baseline)
    for key in ("pitchers", "batters"):
        if results[key] and results[key]["players"] > baseline.get(key, 0):
            updated[key] = results[key]["players"]
        if results[key]:
            rpp_key = f"{key}_rows_per_player"
            if results[key]["rows_per_player"] > baseline.get(rpp_key, 0):
                updated[rpp_key] = results[key]["rows_per_player"]
    if updated != baseline:
        _save_baseline(updated)
        print(f"Baseline ratcheted forward: {updated}")

    print("PASS -- data is clear for retraining.")
    sys.exit(0)


if __name__ == "__main__":
    main()
