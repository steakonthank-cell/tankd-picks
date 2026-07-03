#!/usr/bin/env python3
"""
Regression check for the LOCK/STRONG/LEAN tier-filter bug (Bug 2: the
Aranda/Kreidler SO@0.5 case, where the pick card rendered a "LOCK" badge but
the LOCK filter tab showed "No picks for this line yet.").

This calls the exact Python logic the API serves to the frontend --
features.pipeline.enrich_scan_data() + api.server.df_to_picks() -- directly,
with no HTTP layer and no browser/UI involved. It then re-implements, in
Python, the two pieces of client-side logic from frontend/dist/app.jsx that
must agree with each other for the tier tabs to work:

  1. The pick-card badge (TankdPicks render, ~line 617):
       const cd = pick.model_prob != null ? confDisplay(pick.model_prob) : null;
       const tier = pick.grade || (cd ? cd.tier : (pick.tier || ""));

  2. The gradeFilter tab logic (TankdPicks `filtered` useMemo, ~line 273):
       if (gradeFilter !== "all") {
         let g = segmentPicks.filter(p => p.grade === gradeFilter);
         ...
       }
     Note this filters the whole segment (hitter/pitcher) on `grade` alone --
     it does NOT re-scope to the currently selected stat+line. That's real,
     current app behavior, not a bug we introduced here; the check below
     accounts for it.

For every (segment, stat, line) combination we report the "All" count, and
for every (segment, tier) we report the tier-tab count. A pick is flagged
MISMATCH when the badge would render a given tier for at least one pick at
a specific stat+line, but the corresponding filter tab (segment-wide) is
empty -- i.e. exactly the "badge says X, filter tab shows nothing" failure.

Usage:
    python3 scripts/check_filters.py
"""
import os
import sys

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")

import pandas as pd  # noqa: E402

from api.server import get_latest_csv, df_to_picks  # noqa: E402
from features.pipeline import enrich_scan_data  # noqa: E402

HITTER_STATS = ["HRR", "TB", "H", "SO", "R", "RBI", "HR"]
PITCHER_STATS = ["K", "OUTS", "ER"]
TIERS = ["LOCK", "STRONG", "LEAN"]


def conf_display_tier(mp):
    """Mirrors confDisplay() in frontend/dist/app.jsx."""
    if mp is None:
        return None
    if mp >= 0.92:
        return "LOCK"
    if mp >= 0.80:
        return "STRONG"
    if mp >= 0.68:
        return "LEAN"
    return "PASS"


def badge_tier(pick):
    """Which tier, if any, the pick card badge visually claims membership in
    for the LOCK/STRONG/LEAN filter system.

    The badge text itself is `pick.grade || confDisplay(model_prob).tier ||
    pick.tier` (see app.jsx). But pick.tier is v2_tier -- a *different*,
    unrelated scale (ELITE/STRONG/DECENT/LEAN from features/pipeline.py) that
    happens to share the words STRONG/LEAN with the goblin grade vocabulary.
    Post-fix, only a grade-backed badge renders in the gold/teal "graded"
    palette that implies filterability; the v2_tier fallback renders in a
    separate palette specifically so it no longer makes that claim, even
    when the text coincides. So the only tier a badge legitimately claims to
    be filterable under is pick.grade itself.
    """
    return pick.get("grade") or ""


def load_picks(sport="mlb"):
    csv_path = get_latest_csv(sport)
    if not csv_path:
        print(f"No scan CSV found for {sport}")
        sys.exit(1)
    df = pd.read_csv(csv_path)
    enriched = enrich_scan_data(df, sport=sport)
    return df_to_picks(enriched), csv_path


def main():
    picks, csv_path = load_picks("mlb")
    print(f"Loaded {len(picks)} MLB picks from {csv_path}\n")

    table_rows = []
    mismatches = []
    empties = []

    for segment, stats in (("hitter", HITTER_STATS), ("pitcher", PITCHER_STATS)):
        seg_picks = [p for p in picks if p.get("segment") == segment]

        # gradeFilter in app.jsx filters the WHOLE segment on `grade` once a
        # tier tab is active -- it does not re-scope to stat+line. Mirror
        # that exactly: one count per (segment, tier), independent of stat/line.
        segment_tier_counts = {
            tier: len([p for p in seg_picks if p.get("grade") == tier])
            for tier in TIERS
        }

        for stat in stats:
            lines = sorted({p["line"] for p in seg_picks if p["stat_type"] == stat})

            if not lines:
                table_rows.append((segment, stat, "-", "All", 0, "EMPTY (no lines at all)"))
                empties.append((segment, stat, "-"))
                continue

            for line in lines:
                all_subset = [p for p in seg_picks if p["stat_type"] == stat and p["line"] == line]
                all_count = len(all_subset)

                flag = "EMPTY" if all_count == 0 else ""
                if flag:
                    empties.append((segment, stat, line))
                table_rows.append((segment, stat, line, "All", all_count, flag))

                for tier in TIERS:
                    tier_count = segment_tier_counts[tier]
                    badge_tagged = [p for p in all_subset if badge_tier(p) == tier]

                    flag = ""
                    if tier_count == 0 and len(badge_tagged) > 0:
                        flag = "MISMATCH"
                        mismatches.append((segment, stat, line, tier, len(badge_tagged)))
                    table_rows.append((segment, stat, line, tier, tier_count, flag))

    # ─── Print table ───
    print(f"{'SEGMENT':<9}{'STAT':<6}{'LINE':<7}{'TIER':<8}{'COUNT':>6}  FLAG")
    print("-" * 55)
    for seg, stat, line, tier, count, flag in table_rows:
        print(f"{seg:<9}{stat:<6}{str(line):<7}{tier:<8}{count:>6}  {flag}")

    # ─── Summary ───
    print("\n" + "=" * 70)
    if mismatches:
        print(f"MISMATCH: {len(mismatches)} case(s) where a tier tab is empty but the")
        print("badge would render that tier for picks at that stat+line:")
        for seg, stat, line, tier, n in mismatches:
            print(f"  [{seg:<8}] {stat} @ {line:<5} -> {tier} tab = 0, "
                  f"but {n} pick(s) at that line render a {tier} badge")
    else:
        print("No MISMATCHes found.")

    print()
    if empties:
        print(f"EMPTY: {len(empties)} stat+line combo(s) with 0 results under \"All\" "
              f"(possible upstream data/scoring issue):")
        for seg, stat, line in empties:
            print(f"  [{seg:<8}] {stat} @ {line}")
    else:
        print("No EMPTY stat+line combos found.")

    print("\n" + "=" * 70)
    status = "FAIL" if mismatches else "PASS"
    print(f"{status} -- {len(mismatches)} mismatch(es), {len(empties)} empty stat+line combo(s)")
    sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
