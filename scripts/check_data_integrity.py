#!/usr/bin/env python3
"""
Data-integrity health check for the MLB scan: flags internal contradictions
and data problems automatically, so bugs like the Luke Raley case (a 64.6
score/DECENT tier on a projection of 1.37 vs. a line of 4.5 -- a pick whose
own math says it's unlikely) get caught going forward instead of by eye.

This is a diagnostic only -- it does not fix anything, and it does NOT
validate that picks have real betting edge. Confirming edge requires
backtesting against graded outcomes (a separate, later effort, same gate as
the moneyline model). This script only confirms the scan's own numbers are
internally consistent: score agrees with direction, edge math checks out,
splits are correctly flagged, stat coverage isn't silently capped, and
goblin/non-goblin picks pull from the right scoring path.

Checks:
  1. Score/confidence vs. projection direction
  2. Split integrity (real vs-hand split vs. season fallback vs. blank)
  3. Edge/proj sanity (impossible or contradictory values)
  4. Stat coverage (empty buckets, silent cap truncation)
  5. Goblin vs. non-goblin scoring path

Usage:
    python3 scripts/check_data_integrity.py
"""
import os
import sys

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")

import pandas as pd  # noqa: E402

from api.server import get_latest_csv, df_to_picks  # noqa: E402
from features.pipeline import enrich_scan_data  # noqa: E402
from goblin_scorer import score_goblins  # noqa: E402

HITTER_STATS = ["HRR", "TB", "H", "SO", "R", "RBI", "HR"]
PITCHER_STATS = ["K", "OUTS", "ER"]
ALL_STATS = HITTER_STATS + PITCHER_STATS

# A v1/v2 heuristic score at or above this reads as a confident pick
# (DECENT+ on the v2_tier scale -- see features/pipeline.py:v2_tier).
DIRECTION_SCORE_THRESHOLD = 60
# Goblin grades that read as confident (i.e. not SKIP/FLOOR).
DIRECTION_GOBLIN_GRADES = ("LOCK", "STRONG", "LEAN")
# Warn if the real vs-hand-split share of hitter rows drops below this --
# signals the MLB statSplits endpoint may be down again.
SPLIT_COVERAGE_WARN = 0.5
# statSplits has 406'd unconditionally since this date -- a confirmed
# sustained MLB-side outage (re-probed live on 2026-07-28: still down across
# every param/header combination, including the /people hydrate route), not
# a bug in this codebase. src/core/odds_providers/mlb_splits.py already
# degrades gracefully to a season-aggregate fallback (is_split=False) when
# this happens, which is why real_pct sits at 0% instead of the board going
# blank. A prior attempt to replace statSplits with a Baseball Savant
# leaderboard pull was reverted for being worse: its hand filter silently
# no-op'd and served combined-season stats mislabeled as real splits. If
# real_pct is still 0% below, that's this known outage, not a new problem --
# it's only worth investigating further if "No split data" also grows, since
# that would mean the fallback itself started failing.
KNOWN_SPLIT_OUTAGE_SINCE = "2026-07-04"
# Safety ceiling in api/server.py's _cap_per_stat(); a bucket sitting at or
# near it may be getting silently truncated rather than fully served.
CAP_PER_STAT = 1000
CAP_WARN_FRACTION = 0.9


def load_enriched():
    csv_path = get_latest_csv("mlb")
    if not csv_path:
        print("No scan CSV found for mlb")
        sys.exit(1)
    df = pd.read_csv(csv_path)
    enriched = enrich_scan_data(df, sport="mlb")
    return enriched, csv_path


def _direction_favorable(proj, line, side):
    """True/False if AI_Proj vs PP_Line favors the picked Side; None if
    the row can't be evaluated (missing data, or proj == line exactly)."""
    if pd.isna(proj) or pd.isna(line):
        return None
    side = str(side).strip().lower()
    if side not in ("over", "under"):
        return None
    diff = float(proj) - float(line)
    if diff == 0:
        return None
    return (diff > 0) if side == "over" else (diff < 0)


# ─────────────────────────────────────────────────────────────────────────
# Check 1: score/confidence vs. projection direction
# ─────────────────────────────────────────────────────────────────────────
def check_direction(df, goblin_scores):
    issues = []
    for idx, row in df.iterrows():
        favorable = _direction_favorable(row.get("AI_Proj"), row.get("PP_Line"), row.get("Side"))
        if favorable is None or favorable:
            continue  # can't evaluate, or direction is fine

        is_goblin = bool(row.get("Is_Goblin", False))
        if is_goblin:
            prob, grade = goblin_scores.get(idx, (None, None))
            if grade in DIRECTION_GOBLIN_GRADES:
                issues.append(dict(
                    player=row.get("Player"), stat=row.get("Stat"), line=row.get("PP_Line"),
                    proj=row.get("AI_Proj"), side=row.get("Side"), path="goblin",
                    shown=f"grade={grade} model_prob={prob}",
                ))
        else:
            score = row.get("v2_score")
            tier = row.get("v2_tier")
            if pd.notna(score) and score >= DIRECTION_SCORE_THRESHOLD:
                issues.append(dict(
                    player=row.get("Player"), stat=row.get("Stat"), line=row.get("PP_Line"),
                    proj=row.get("AI_Proj"), side=row.get("Side"), path="heuristic",
                    shown=f"v2_tier={tier} v2_score={score}",
                ))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# Check 2: split integrity (coverage report, not a hard fail)
# ─────────────────────────────────────────────────────────────────────────
def check_splits(df):
    if "Split_Is_Live" not in df.columns:
        return dict(real=0, fallback=0, blank=0, real_pct=None, warn=True,
                    reason="Split_Is_Live column missing from scan output")

    hitters = df[df.get("Is_Pitcher") != True] if "Is_Pitcher" in df.columns else df
    live = hitters["Split_Is_Live"]
    real = int((live == True).sum())      # noqa: E712
    fallback = int((live == False).sum())  # noqa: E712
    blank = int(live.isna().sum())

    total = real + fallback
    real_pct = (real / total) if total else None
    warn = real_pct is not None and real_pct < SPLIT_COVERAGE_WARN
    return dict(real=real, fallback=fallback, blank=blank, real_pct=real_pct, warn=warn, reason=None)


# ─────────────────────────────────────────────────────────────────────────
# Check 3: edge/proj sanity
# ─────────────────────────────────────────────────────────────────────────
def check_edge_sanity(df):
    issues = []
    for idx, row in df.iterrows():
        proj = row.get("AI_Proj")
        line = row.get("PP_Line")
        side = str(row.get("Side", "")).strip().title()
        is_goblin = bool(row.get("Is_Goblin", False))
        is_demon = bool(row.get("Is_Demon", False))
        base = dict(player=row.get("Player"), stat=row.get("Stat"), line=line, proj=proj, side=row.get("Side"))

        if pd.notna(proj) and float(proj) < 0:
            issues.append(dict(base, reason="negative AI_Proj"))
        if pd.isna(line) or float(line) <= 0:
            issues.append(dict(base, reason="PP_Line missing or <= 0"))
            continue  # nothing directional to check without a real line

        if (is_goblin or is_demon) and side != "Over":
            issues.append(dict(base, reason=f"goblin/demon pick with Side={side} (PrizePicks goblins/demons are Over-only)"))

        if not is_goblin and not is_demon and pd.notna(proj):
            diff = float(proj) - float(line)
            if diff > 0 and side != "Over":
                issues.append(dict(base, reason=f"AI_Proj > PP_Line but Side={side}"))
            elif diff < 0 and side != "Under":
                issues.append(dict(base, reason=f"AI_Proj < PP_Line but Side={side}"))
    return issues


# ─────────────────────────────────────────────────────────────────────────
# Check 4: stat coverage / silent cap truncation
# ─────────────────────────────────────────────────────────────────────────
def check_coverage(df, served_picks):
    rows = []
    empties = []
    cap_warnings = []

    for segment, stats in (("hitter", HITTER_STATS), ("pitcher", PITCHER_STATS)):
        is_pitcher_seg = segment == "pitcher"
        seg_raw = df[df.get("Is_Pitcher", False) == is_pitcher_seg] if "Is_Pitcher" in df.columns else df
        seg_served = [p for p in served_picks if p.get("segment") == segment]

        for stat in stats:
            raw_count = int((seg_raw.get("Stat", pd.Series(dtype=str)).astype(str).str.upper() == stat).sum())
            served_count = len([p for p in seg_served if str(p.get("stat_type", "")).upper() == stat])

            flag = ""
            if raw_count > 0 and served_count == 0:
                flag = "EMPTY (raw data existed but nothing served)"
                empties.append((segment, stat, raw_count))

            for bucket_name, bucket_picks in (("goblin", [p for p in seg_served if p.get("is_goblin")]),
                                               ("non-goblin", [p for p in seg_served if not p.get("is_goblin")])):
                bucket_count = len([p for p in bucket_picks if str(p.get("stat_type", "")).upper() == stat])
                if bucket_count >= CAP_PER_STAT * CAP_WARN_FRACTION:
                    cap_warnings.append((segment, stat, bucket_name, bucket_count))

            rows.append((segment, stat, raw_count, served_count, flag))

    return rows, empties, cap_warnings


# ─────────────────────────────────────────────────────────────────────────
# Check 5: goblin vs. non-goblin scoring path
# ─────────────────────────────────────────────────────────────────────────
def check_scoring_path(df, goblin_scores):
    issues = []
    for idx, row in df.iterrows():
        is_goblin = bool(row.get("Is_Goblin", False))
        prob, grade = goblin_scores.get(idx, (None, None))
        base = dict(player=row.get("Player"), stat=row.get("Stat"), line=row.get("PP_Line"))

        if is_goblin and prob is None:
            issues.append(dict(base, reason="goblin row has no model_prob -- calibrated model silently unavailable, would fall back to heuristic v2_score"))
        if not is_goblin and prob is not None:
            issues.append(dict(base, reason=f"non-goblin row has model_prob={prob}/grade={grade} -- calibrated goblin score leaked onto a non-goblin pick"))
    return issues


def _print_issues(issues, cols):
    for it in issues:
        parts = [f"{c}={it.get(c)}" for c in cols]
        print("  " + " | ".join(parts))


def main():
    df, csv_path = load_enriched()
    print(f"Loaded {len(df)} MLB rows from {csv_path}\n")

    try:
        goblin_scores = score_goblins(df)
    except Exception as e:
        print(f"WARNING: goblin scoring failed to run at all: {e}\n")
        goblin_scores = {}

    served_picks = df_to_picks(df)

    fail = False

    print("=" * 70)
    print("CHECK 1: Score/confidence vs. projection direction")
    print("=" * 70)
    direction_issues = check_direction(df, goblin_scores)
    if direction_issues:
        fail = True
        print(f"FAIL: {len(direction_issues)} pick(s) show a confident score/grade on an unfavorable projection:")
        _print_issues(direction_issues, ["player", "stat", "line", "proj", "side", "path", "shown"])
    else:
        print("OK: no confident picks found with an unfavorable projection direction.")

    print("\n" + "=" * 70)
    print("CHECK 2: Split integrity (coverage report)")
    print("=" * 70)
    split_stats = check_splits(df)
    if split_stats.get("reason") and split_stats["real"] == 0 and split_stats["fallback"] == 0 and split_stats["blank"] == 0:
        print(f"WARN: {split_stats['reason']}")
    else:
        real, fallback, blank = split_stats["real"], split_stats["fallback"], split_stats["blank"]
        pct = split_stats["real_pct"]
        pct_s = f"{pct * 100:.1f}%" if pct is not None else "n/a"
        marker = "⚠ " if split_stats["warn"] else ""
        print(f"{marker}Real vs-hand splits: {real}  |  Season fallback: {fallback}  |  No split data: {blank}  |  Real-split share: {pct_s}")
        if split_stats["warn"]:
            print(f"WARN: real-split share is below {SPLIT_COVERAGE_WARN * 100:.0f}% -- "
                  f"known MLB statSplits outage since {KNOWN_SPLIT_OUTAGE_SINCE}, season-aggregate "
                  f"fallback is active and working as designed (see src/core/odds_providers/mlb_splits.py). "
                  f"Only investigate further if 'No split data' also grows -- that would mean the "
                  f"fallback itself is failing, which is a new problem.")

    print("\n" + "=" * 70)
    print("CHECK 3: Edge/proj sanity")
    print("=" * 70)
    edge_issues = check_edge_sanity(df)
    if edge_issues:
        fail = True
        print(f"FAIL: {len(edge_issues)} pick(s) with impossible or contradictory edge/proj/line values:")
        _print_issues(edge_issues, ["player", "stat", "line", "proj", "side", "reason"])
    else:
        print("OK: no impossible or contradictory edge/proj/line combinations found.")

    print("\n" + "=" * 70)
    print("CHECK 4: Stat coverage / silent cap truncation")
    print("=" * 70)
    coverage_rows, empties, cap_warnings = check_coverage(df, served_picks)
    print(f"{'SEGMENT':<9}{'STAT':<6}{'RAW':>6}{'SERVED':>8}  FLAG")
    print("-" * 55)
    for seg, stat, raw_count, served_count, flag in coverage_rows:
        print(f"{seg:<9}{stat:<6}{raw_count:>6}{served_count:>8}  {flag}")
    if empties:
        fail = True
        print(f"\nFAIL: {len(empties)} stat bucket(s) had raw data but served 0 picks:")
        for seg, stat, raw_count in empties:
            print(f"  [{seg:<8}] {stat}: {raw_count} raw row(s), 0 served")
    if cap_warnings:
        fail = True
        print(f"\nFAIL: {len(cap_warnings)} bucket(s) sitting at/near the {CAP_PER_STAT}-per-stat cap (may be silently truncating):")
        for seg, stat, bucket_name, count in cap_warnings:
            print(f"  [{seg:<8}] {stat} ({bucket_name}): {count} served")
    if not empties and not cap_warnings:
        print("\nOK: no empty buckets, no bucket near the per-stat cap.")

    print("\n" + "=" * 70)
    print("CHECK 5: Goblin vs. non-goblin scoring path")
    print("=" * 70)
    path_issues = check_scoring_path(df, goblin_scores)
    if path_issues:
        fail = True
        print(f"FAIL: {len(path_issues)} pick(s) pulling from the wrong scoring path:")
        _print_issues(path_issues, ["player", "stat", "line", "reason"])
    else:
        print("OK: every goblin row has a calibrated model_prob, no non-goblin row does.")

    print("\n" + "=" * 70)
    status = "FAIL" if fail else "PASS"
    print(f"{status} -- direction:{len(direction_issues)} edge_sanity:{len(edge_issues)} "
          f"empty_buckets:{len(empties)} cap_warnings:{len(cap_warnings)} scoring_path:{len(path_issues)} "
          f"(split coverage is informational only, never fails this run)")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
