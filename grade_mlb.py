#!/usr/bin/env python3
"""Honest MLB grader — grades scan picks vs actual box scores, split by OddsType."""
import os, glob, json, time, unicodedata, urllib.request
import pandas as pd

API = "https://statsapi.mlb.com/api/v1"

HITTER = {
    "Hits": "hits", "Total Bases": "totalBases", "Home Runs": "homeRuns",
    "RBIs": "rbi", "Runs": "runs", "Walks": "baseOnBalls",
    "Hitter Strikeouts": "strikeOuts",
}
HITTER_COMBO = {"Hits+Runs+RBIs": lambda b: b.get("hits",0)+b.get("runs",0)+b.get("rbi",0)}
PITCHER = {
    "Pitcher Strikeouts": "strikeOuts", "Earned Runs Allowed": "earnedRuns",
    "Pitching Outs": "outs",
}

def norm(name):
    if not isinstance(name, str): return ""
    n = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode()
    n = n.lower().replace(".","").replace(",","").strip()
    for s in (" jr"," sr"," ii"," iii"," iv"):
        if n.endswith(s): n = n[:-len(s)]
    return " ".join(n.split())

def get_json(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tankd-picks grader)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 406 and i < tries-1:
                time.sleep(5 * (i+1)); continue
            if i==tries-1: raise
            time.sleep(1.5)
        except Exception:
            if i==tries-1: raise
            time.sleep(1.5)

def box_for_date(date):
    sched = get_json(f"{API}/schedule?sportId=1&date={date}")
    games = [g["gamePk"] for d in sched.get("dates",[]) for g in d.get("games",[])
             if g.get("status",{}).get("abstractGameState")=="Final"]
    actuals = {}
    for gp in games:
        try: bx = get_json(f"{API}/game/{gp}/boxscore")
        except Exception: continue
        for side in ("home","away"):
            for _, pdata in bx["teams"][side]["players"].items():
                st = pdata.get("stats",{})
                actuals[norm(pdata["person"]["fullName"])] = {
                    "batting": st.get("batting",{}), "pitching": st.get("pitching",{})}
        time.sleep(0.3)
    return actuals, len(games)

def actual_value(label, is_pitcher, block):
    if is_pitcher:
        col = PITCHER.get(label)
        return block.get(col,0) if col else None
    if label in HITTER_COMBO:
        return HITTER_COMBO[label](block)
    col = HITTER.get(label)
    return block.get(col,0) if col else None

def grade_day(date):
    scan = f"output/mlb/scans/scan_{date}.csv"
    if not os.path.exists(scan): return None
    df = pd.read_csv(scan)
    actuals, ngames = box_for_date(date)
    if not actuals: return None
    rows = []
    for _, r in df.iterrows():
        nm = norm(r.get("Player")); a = actuals.get(nm)
        if a is None: continue
        is_p = bool(r.get("Is_Pitcher", False))
        block = a["pitching"] if is_p else a["batting"]
        if not block: continue
        if not is_p and block.get("gamesPlayed",0)==0: continue
        av = actual_value(r.get("Stat_Label"), is_p, block)
        if av is None: continue
        line = float(r.get("PP_Line",0)); side = str(r.get("Side","")).strip().lower()
        if av == line: res = "Push"
        elif side.startswith("o"): res = "WIN" if av>line else "LOSS"
        elif side.startswith("u"): res = "WIN" if av<line else "LOSS"
        else: continue
        odds = "goblin" if r.get("Is_Goblin") else "demon" if r.get("Is_Demon") else "standard"
        rec = r.to_dict(); rec.update(actual_value=av, result=res,
                                      hit=1 if res=="WIN" else 0, odds_type=odds, scan_date=date)
        rows.append(rec)
    out = pd.DataFrame(rows)
    if len(out): out.to_csv(f"output/mlb/graded/graded_{date}.csv", index=False)
    return out

def main():
    os.makedirs("output/mlb/graded", exist_ok=True)
    import sys
    if len(sys.argv) > 1:
        scans = [f"output/mlb/scans/scan_{d}.csv" for d in sys.argv[1:]]
    else:
        scans = sorted(glob.glob("output/mlb/scans/scan_2026-*.csv"))
    scans = [s for s in scans if s.count("_")==1]
    allr = []
    print(f"Grading {len(scans)} days...\n")
    for s in scans:
        date = os.path.basename(s).replace("scan_","").replace(".csv","")
        try:
            o = grade_day(date)
            if o is not None and len(o):
                allr.append(o)
                d = o[o["result"]!="Push"]
                line = f"  {date}: {len(o):>4} graded"
                for t in ("standard","goblin"):
                    sub = d[d["odds_type"]==t]
                    if len(sub): line += f" | {t} {sub['hit'].mean():.3f} (n={len(sub)})"
                print(line)
        except Exception as e:
            print(f"  {date}: ERROR {e}")
    if allr:
        full = pd.concat(allr, ignore_index=True)
        full.to_csv("output/mlb/graded/training_data.csv", index=False)
        d = full[full["result"]!="Push"]
        print(f"\nTOTAL graded: {len(full)} | saved training_data.csv")
        print("\nHit rate by OddsType (push excluded):")
        print(d.groupby("odds_type")["hit"].agg(["mean","count"]).round(3).to_string())
        print("\nGoblin hit rate by Tier:")
        gob = d[d["odds_type"]=="goblin"]
        if len(gob) and "Tier" in gob.columns:
            print(gob.groupby("Tier")["hit"].agg(["mean","count"]).round(3).to_string())
        print("\nStandard hit rate by Tier:")
        std = d[d["odds_type"]=="standard"]
        if len(std) and "Tier" in std.columns:
            print(std.groupby("Tier")["hit"].agg(["mean","count"]).round(3).to_string())

if __name__ == "__main__":
    main()
