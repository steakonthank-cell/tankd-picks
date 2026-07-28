#!/usr/bin/env python3
"""Backfill grader: match past scan picks to actual MLB box-score outcomes."""
import os, sys, glob, json, time, unicodedata, urllib.request
import pandas as pd

API = "https://statsapi.mlb.com/api/v1"

# scan Stat_Label -> function of a batting stat dict -> actual value
HITTER_STATS = {
    "Hits":            lambda b: b.get("hits", 0),
    "Total Bases":     lambda b: b.get("totalBases", 0),
    "Home Runs":       lambda b: b.get("homeRuns", 0),
    "RBIs":            lambda b: b.get("rbi", 0),
    "Runs":            lambda b: b.get("runs", 0),
    "Walks":           lambda b: b.get("baseOnBalls", 0),
    "Hitter Strikeouts": lambda b: b.get("strikeOuts", 0),
    "Hits+Runs+RBIs":  lambda b: b.get("hits", 0) + b.get("runs", 0) + b.get("rbi", 0),
}
PITCHER_STATS = {
    "Pitcher Strikeouts":  lambda p: p.get("strikeOuts", 0),
    "Earned Runs Allowed": lambda p: p.get("earnedRuns", 0),
    "Pitching Outs":       lambda p: p.get("outs", 0),
}

def norm(name):
    if not isinstance(name, str): return ""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = n.lower().replace(".", "").replace(",", "").strip()
    for suf in (" jr", " sr", " ii", " iii", " iv"):
        if n.endswith(suf): n = n[:-len(suf)]
    return " ".join(n.split())

def get_json(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(1.5)

def build_actuals(date):
    """Return {normalized_name: {'batting':{...}, 'pitching':{...}}} for a date."""
    sched = get_json(f"{API}/schedule?sportId=1&date={date}")
    games = [g["gamePk"] for d in sched.get("dates", []) for g in d.get("games", [])
             if g.get("status", {}).get("abstractGameState") == "Final"]
    actuals = {}
    for gp in games:
        try:
            box = get_json(f"{API}/game/{gp}/boxscore")
        except Exception:
            continue
        for side in ("home", "away"):
            for pid, pd_ in box["teams"][side]["players"].items():
                nm = norm(pd_["person"]["fullName"])
                st = pd_.get("stats", {})
                actuals[nm] = {"batting": st.get("batting", {}), "pitching": st.get("pitching", {})}
        time.sleep(0.3)  # be polite to the API
    return actuals, len(games)

def grade_day(date):
    path = f"output/mlb/scans/scan_{date}.csv"
    if not os.path.exists(path): return None
    df = pd.read_csv(path)
    actuals, ngames = build_actuals(date)
    if not actuals:
        print(f"  {date}: no final games found, skipping"); return None

    rows, matched, no_player, no_stat = [], 0, 0, 0
    for _, r in df.iterrows():
        label = r.get("Stat_Label")
        is_pitcher = bool(r.get("Is_Pitcher", False))
        nm = norm(r.get("Player"))
        a = actuals.get(nm)
        if a is None:
            no_player += 1; continue
        statmap = PITCHER_STATS if is_pitcher else HITTER_STATS
        fn = statmap.get(label)
        if fn is None:
            no_stat += 1; continue
        block = a["pitching"] if is_pitcher else a["batting"]
        if not block or block.get("gamesPlayed", 0) == 0 and not is_pitcher:
            no_player += 1; continue
        actual = fn(block)
        line = float(r.get("PP_Line", 0))
        side = str(r.get("Side", "")).strip().lower()
        # determine hit: Over cashes if actual > line; Under if actual < line; push excluded already
        if side.startswith("o"):
            hit = 1 if actual > line else 0
        elif side.startswith("u"):
            hit = 1 if actual < line else 0
        else:
            continue
        rec = r.to_dict()
        rec["actual_value"] = actual
        rec["hit"] = hit
        rec["scan_date"] = date
        rows.append(rec); matched += 1

    out = pd.DataFrame(rows)
    if len(out):
        out.to_csv(f"output/mlb/graded/graded_{date}.csv", index=False)
    hr = out["hit"].mean() if len(out) else 0
    print(f"  {date}: {ngames} games | matched {matched} | hit-rate {hr:.3f} "
          f"| dropped: no_player {no_player}, no_stat {no_stat}")
    return out

def main():
    scans = sorted(glob.glob("output/mlb/scans/scan_2026-*.csv"))
    # only clean YYYY-MM-DD files (skip the _v2_v2 dupes)
    scans = [s for s in scans if s.count("_") == 1]
    print(f"Grading {len(scans)} scan days...\n")
    all_rows = []
    for s in scans:
        date = os.path.basename(s).replace("scan_", "").replace(".csv", "")
        try:
            out = grade_day(date)
            if out is not None and len(out): all_rows.append(out)
        except Exception as e:
            print(f"  {date}: ERROR {e}")
    if all_rows:
        full = pd.concat(all_rows, ignore_index=True)
        out_path = "output/mlb/graded/training_data.csv"
        # Merge into the existing file instead of replacing it outright, so a
        # partial-date run (e.g. re-grading just a few days) can't wipe out
        # historical rows for dates it never touched.
        run_dates = set(full["scan_date"].unique())
        if os.path.exists(out_path):
            existing = pd.read_csv(out_path)
            existing = existing[~existing["scan_date"].isin(run_dates)]
            merged = pd.concat([existing, full], ignore_index=True)
        else:
            merged = full
        merged = merged.sort_values("scan_date").reset_index(drop=True)
        merged.to_csv(out_path, index=False)
        print(f"\nTOTAL graded this run: {len(full)} | training_data.csv now has {len(merged)} rows across {merged['scan_date'].nunique()} days")
        print(f"Overall hit rate (this run): {full['hit'].mean():.3f}")
        print(f"Saved -> {out_path}")
        print(f"\nHit rate by tier (this run):")
        if "Tier" in full.columns:
            print(full.groupby("Tier")["hit"].agg(["mean", "count"]).round(3).to_string())

if __name__ == "__main__":
    main()
