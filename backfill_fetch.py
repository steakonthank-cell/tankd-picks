#!/usr/bin/env python3
"""Stage 1: fetch & cache final-game box scores. Idempotent, resumable."""
import os, json, time, requests
from datetime import date, timedelta
from datetime import date
API = "https://statsapi.mlb.com/api/v1"
OUT = "data/mlb/boxscores"
os.makedirs(OUT, exist_ok=True)

def get(url, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (tankd-picks)"}, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == tries-1: raise
            time.sleep(2)

def fetch_range(start, end):
    d0 = date.fromisoformat(start); d1 = date.fromisoformat(end)
    saved = 0
    cur = d0
    while cur <= d1:
        ds = cur.isoformat()
        cur += timedelta(days=1)
        out_path = f"{OUT}/{ds}.json"
        if os.path.exists(out_path):
            continue
        sched = get(f"{API}/schedule?sportId=1&date={ds}")
        finals = []
        for d in sched.get("dates", []):
            finals += [g["gamePk"] for g in d.get("games", [])
                       if g.get("status", {}).get("abstractGameState") == "Final"]
        if not finals:
            continue
        day_data = {}
        for gp in finals:
            try:
                box = get(f"{API}/game/{gp}/boxscore")
                slim = {}
                for side in ("home", "away"):
                    tm = box["teams"][side]["team"].get("abbreviation", box["teams"][side]["team"].get("name", ""))
                    for pid, pdata in box["teams"][side]["players"].items():
                        st = pdata.get("stats", {})
                        slim[pdata["person"]["fullName"]] = {
                            "team": tm,
                            "batting": {k: st.get("batting", {}).get(k) for k in
                                ("hits","totalBases","homeRuns","rbi","runs","baseOnBalls","strikeOuts","gamesPlayed","atBats")},
                            "pitching": {k: st.get("pitching", {}).get(k) for k in
                                ("strikeOuts","earnedRuns","outs")},
                        }
                day_data[str(gp)] = slim
                time.sleep(0.25)
            except Exception as e:
                print(f"  game {gp} failed: {e}")
        with open(out_path, "w") as fo:
            json.dump(day_data, fo)
        saved += 1
        if saved % 10 == 0:
            print(f"  saved {saved} days (latest {ds})")
    return saved

def fetch_range_chunked(start, end, days=7):
    d0 = date.fromisoformat(start); d1 = date.fromisoformat(end)
    total = 0
    cur = d0
    while cur <= d1:
        chunk_end = min(cur + timedelta(days=days-1), d1)
        total += fetch_range(cur.isoformat(), chunk_end.isoformat())
        cur = chunk_end + timedelta(days=1)
    return total

for s, e in [("2026-06-14", date.today().isoformat())]:
    print(f"Range {s} -> {e}")
    n = fetch_range(s, e)
    print(f"  {n} new days saved")
print("Total days cached:", len(os.listdir(OUT)))
