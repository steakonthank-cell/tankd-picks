import sys, os, glob, json, builtins, pandas as pd, numpy as np
from urllib.request import Request, urlopen
from datetime import datetime
import time

os.chdir("/root/tankd-picks")
sys.path.insert(0, "/root/tankd-picks")
builtins.input = lambda *a: ""

SEND_ONLY = "--send-only" in sys.argv
WEBHOOKS = {
    "mlb": "https://discord.com/api/webhooks/1510730614381219920/WFvTrQIl5NyCWps-xAYksry-JmgXPBgQWeuo506EYKzte7nCsAEiA8ls4jXdkHVKpr0r",
    "mlb_pitchers": "https://discord.com/api/webhooks/1513983385960321137/dgKg5ciROdL-aiHmQIWKVB09E8MfQV2Wy-Kmc-M1AlX8MHia6qEI-FIDy792GmrAn1iV",
    "wnba": "https://discord.com/api/webhooks/1511425744931258469/T7dyW7duwFY7jrRGXK329tW6ylNsFUcpszKYpzLiEHAmjyOZuwCokZI2f6fNOhMZpaUV",
    "nba": "https://discord.com/api/webhooks/1511425836702502964/UN0xY2pUGWwbJwVwsd1vQs21uINBturak2mY8t_AY4yjkhflY9d3HC8H1yi8aHO8oYVW",
    "moneylines": "https://discord.com/api/webhooks/1511425913315655901/RFyJ8dtvvqmjKYvoVU_qvv1UQbGZONjhgjgj0ej0bkOglQiC5gPR_u2xynErBho7JI1I",
}
HDR = {"Content-Type": "application/json", "User-Agent": "TankdPicks/1.0"}

HITTER_STATS = ["hits","hit","h","hits+runs+rbis","hrr","hits+runs+rbi","hitter strikeouts","batter strikeouts","hitter ks"]
PITCHER_STATS = ["pitching outs","pitcher outs","outs","strikeouts","pitcher strikeouts","pitching strikeouts","k"]
ALLOWED_STATS_MLB = HITTER_STATS + PITCHER_STATS

def stat_allowed(sl, sport):
    if sport != "mlb":
        return True
    s = str(sl).strip().lower()
    return any(a in s or s in a for a in ALLOWED_STATS_MLB)

def is_pitcher_stat(sl):
    s = str(sl).strip().lower()
    return any(a in s or s in a for a in PITCHER_STATS)

def send(url, msg):
    urlopen(Request(url, json.dumps({"content": msg[:1950]}).encode(), headers=HDR))
    time.sleep(0.5)

def normalize(df):
    rn = {"Stat": "Stat_Label", "AI_Edge": "Edge_Pct", "Tier_Label": "Tier", "Avg_L10": "L5"}
    df = df.rename(columns={k: v for k, v in rn.items() if k in df.columns and v not in df.columns})
    if "L10" not in df.columns:
        df["L10"] = df["L5"] if "L5" in df.columns else float("nan")
    if "L5" not in df.columns:
        df["L5"] = float("nan")
    for c in ["OPS_vs", "K_Pct_vs"]:
        if c not in df.columns:
            df[c] = float("nan")
    if "AI_Proj" not in df.columns:
        df["AI_Proj"] = float("nan")  # do not fabricate; drop/flag downstream
    return df.reset_index(drop=True)

def score_pick(r):
    s = 0
    edge = abs(r.get("Edge_Pct", 0))
    if edge >= 60: s += 30
    elif edge >= 40: s += 25
    elif edge >= 25: s += 18
    elif edge >= 15: s += 10
    else: s += 5
    tier = str(r.get("Tier", ""))
    if "ELITE" in tier: s += 20
    elif "STRONG" in tier: s += 14
    elif "DECENT" in tier: s += 8
    try:
        line = float(r.get("PP_Line", 0))
        l5 = float(r.get("L5", 0))
        l10 = float(r.get("L10", 0))
        side = str(r.get("Side", ""))
        if "Over" in side:
            if l5 > line: s += 8
            if l10 > line: s += 7
        else:
            if l5 < line: s += 8
            if l10 < line: s += 7
    except: pass
    try:
        ops = float(r.get("OPS_vs", 0))
        kp = float(r.get("K_Pct_vs", 0))
        side = str(r.get("Side", ""))
        if "Over" in side:
            if ops >= 0.800: s += 8
            elif ops >= 0.700: s += 5
            if kp <= 20: s += 7
            elif kp <= 25: s += 4
        else:
            if ops <= 0.650: s += 8
            elif ops <= 0.720: s += 5
            if kp >= 28: s += 7
            elif kp >= 24: s += 4
    except: pass
    try:
        l5 = float(r.get("L5", 0))
        l10 = float(r.get("L10", 0))
        if l10 > 0:
            ratio = l5 / l10 if l10 != 0 else 1
            if 0.85 <= ratio <= 1.15: s += 10
            elif 0.7 <= ratio <= 1.3: s += 5
    except: pass
    stat = str(r.get("Stat_Label", "")).lower()
    if any(k in stat for k in ["strikeout", "k", "pitching", "outs"]):
        s += 10
    try:
        e = abs(r.get("Edge_Pct", 0))
        ln = float(r.get("PP_Line", 1))
        if ln > 0 and e / ln > 15: s += 5
    except: pass
    return min(s, 100)

def fmt(df, n, label):
    if len(df) == 0:
        return ""
    top = df.head(n)
    hdr = " #  SC PLAYER               STAT          LINE  PROJ  EDGE SD   L5    OPS     K%"
    sep = "-" * 76
    rows = []
    for i, (_, r) in enumerate(top.iterrows(), 1):
        sc = int(r.get("smart_score", 0))
        sd = "OV" if "Over" in str(r.get("Side", "")) else "UN"
        st = str(r.get("Stat_Label", ""))[:12]
        ops = "{:.3f}".format(r["OPS_vs"]) if not pd.isna(r.get("OPS_vs")) else " ---"
        kp = "{:.1f}%".format(r["K_Pct_vs"]) if not pd.isna(r.get("K_Pct_vs")) else " ---"
        l5 = "{:.1f}".format(r["L5"]) if not pd.isna(r.get("L5")) else " ---"
        proj = "{:.2f}".format(r["AI_Proj"]) if not pd.isna(r.get("AI_Proj")) else " ---"
        epct = "{:.1f}%".format(r["Edge_Pct"]) if not pd.isna(r.get("Edge_Pct")) else " ---"
        rows.append("{:>2} {:>2} {:<20} {:<13} {:>4} {:>5} {:>5} {:>2} {:>4} {:>6}   {:>5}".format(
            i, sc, str(r["Player"])[:19], st, r["PP_Line"], proj, epct, sd, l5, ops, kp))
    return "**{}**\n```\n{}\n{}\n".format(label, hdr, sep) + "\n".join(rows) + "\n```"

def send_picks(df, webhook, label_prefix):
    gob_col = df.get("Is_Goblin", pd.Series([False] * len(df))).astype(bool)
    std = df[~gob_col].drop_duplicates(subset=["Player"])
    t1 = fmt(std, 10, "{} TOP 10 STANDARD (AI Scored)".format(label_prefix))
    if t1:
        send(webhook, t1)
    gob = df[gob_col].drop_duplicates(subset=["Player"])
    g1 = fmt(gob.head(10), 10, "{} TOP GOBLINS 1-10 (AI Scored)".format(label_prefix))
    if g1:
        send(webhook, g1)
    if len(gob) > 10:
        g2 = fmt(gob.iloc[10:20].reset_index(drop=True), 10, "{} TOP GOBLINS 11-20 (AI Scored)".format(label_prefix))
        if g2:
            send(webhook, g2)
    best = df.drop_duplicates(subset=["Player"]).head(5)
    medal = ["1st", "2nd", "3rd", "4th", "5th"]
    lines = []
    for i, (_, r) in enumerate(best.iterrows()):
        sd = "OVER" if "Over" in str(r.get("Side", "")) else "UNDER"
        gt = " (GOB)" if r.get("Is_Goblin", False) else ""
        ep = "{:.1f}%".format(r["Edge_Pct"]) if not pd.isna(r.get("Edge_Pct")) else "?"
        lines.append("{}: **{}** - {} {} {} | Edge: {} | Score: {}{}".format(
            medal[i], r["Player"], r["Stat_Label"], sd, r["PP_Line"], ep, int(r["smart_score"]), gt))
    if lines:
        send(webhook, "**{} BEST BETS (AI Picks)**\n".format(label_prefix) + "\n".join(lines))

# Run scanners or skip
if SEND_ONLY:
    print(">> SEND-ONLY MODE: skipping scanners, using existing CSVs")
else:
    print(">> FULL SCAN MODE: running all scanners...")
    for mod in ["src.sports.mlb.scanner"]:
        try:
            print("   Running {}...".format(mod))
            __import__(mod, fromlist=["main"]).main()
            print("   {} done!".format(mod))
        except Exception as e:
            print("   {} failed: {}".format(mod, e))

now = datetime.now().strftime("%B %d, %I:%M %p")
send(WEBHOOKS["mlb"], "# Tankd Picks AI Analysis - {}\nScored on: Edge, Tier, Form, Matchups, Consistency\nhttp://157.230.3.58/".format(now))

for sp in ["mlb"]:
    ff = sorted(glob.glob("/root/tankd-picks/output/{}/scans/scan_*.csv".format(sp)))
    if not ff:
        print("{}: No scan files found".format(sp.upper()))
        continue
    df = normalize(pd.read_csv(ff[-1]))
    if len(df) == 0:
        print("{}: Empty scan".format(sp.upper()))
        continue
    SP = sp.upper()
    webhook = WEBHOOKS.get(sp, WEBHOOKS["mlb"])
    mask = [stat_allowed(x, sp) for x in df["Stat_Label"]]
    df = df[mask].reset_index(drop=True)
    if len(df) == 0:
        print("{}: No plays after stat filter".format(SP))
        continue
    print("{}: {} plays after stat filter".format(SP, len(df)))
    df["smart_score"] = df.apply(score_pick, axis=1)
    df = df.sort_values("smart_score", ascending=False).reset_index(drop=True)

    if sp == "mlb":
        pitcher_mask = [is_pitcher_stat(x) for x in df["Stat_Label"]]
        hitter_mask = [not x for x in pitcher_mask]
        df_hit = df[hitter_mask].reset_index(drop=True)
        df_pit = df[pitcher_mask].reset_index(drop=True)
        if len(df_hit) > 0:
            print("  MLB HITTERS: {} plays".format(len(df_hit)))
            send_picks(df_hit, WEBHOOKS["mlb"], "MLB HITTERS")
        if len(df_pit) > 0:
            print("  MLB PITCHERS: {} plays SKIPPED (handled by pitcher_k_today.py)".format(len(df_pit)))
        print("MLB: hitters -> #mlb (pitchers handled separately by K model)")
    else:
        send_picks(df, webhook, SP)
        print("{}: scored and sent to #{} channel".format(SP, sp))

# === MONEYLINES ===
print("Fetching moneylines...")
try:
    from src.core.moneylines import fetch_moneylines
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("ODDS_API_KEY")
    if api_key:
        ml_lines = fetch_moneylines(api_key)
        if ml_lines:
            from zoneinfo import ZoneInfo
            _ET = ZoneInfo("America/New_York")
            today_str = datetime.now(_ET).strftime("%Y-%m-%d")
            today_games = [r for r in ml_lines if r.get("Date") == today_str]
            if today_games:
                seen = set()
                best_ml = []
                for r in sorted(today_games, key=lambda x: -x.get("Win %", 0)):
                    gk = tuple(sorted([r["Team"], r["Opponent"]]))
                    if gk in seen:
                        continue
                    seen.add(gk)
                    best_ml.append(r)
                # --- write moneylines to CSV for the dashboard (/api/moneylines) ---
                try:
                    import csv as _csv, os as _os
                    from src.sports.mlb.scanner import _abbr
                    _ml_dir = "/root/tankd-picks/output/moneylines"
                    _os.makedirs(_ml_dir, exist_ok=True)
                    _cols = ["Date","Sport","Time","Team","Opponent","Home","Win %","Avg Odds","Best Odds","Best Book","Game Total","Team_Abbr","Opponent_Abbr","Books"]
                    _ml_path = _os.path.join(_ml_dir, "latest.csv")
                    with open(_ml_path, "w", newline="") as _f:
                        _w = _csv.DictWriter(_f, fieldnames=_cols, extrasaction="ignore")
                        _w.writeheader()
                        for _row in best_ml:
                            _row["Team_Abbr"] = _abbr(_row["Team"])
                            _row["Opponent_Abbr"] = _abbr(_row["Opponent"])
                            _w.writerow(_row)
                    print("MONEYLINES: wrote {} rows -> {}".format(len(best_ml), _ml_path))
                except Exception as _we:
                    print("MONEYLINES: CSV write failed: {}".format(_we))
                hdr = " {:<3} {:<5} {:<24} {:>6} {:>6} {:>12}".format("#", "SPORT", "MATCHUP", "ODDS", "WIN%", "PICK")
                sep = "-" * 62
                rows = []
                for i, r in enumerate(best_ml[:15], 1):
                    hm = "(H)" if r.get("Home") else ""
                    team_short = r["Team"][:12]
                    opp_short = r["Opponent"][:10]
                    matchup = "{} {} v {}".format(team_short, hm, opp_short)[:24]
                    odds_str = "{:+d}".format(int(r.get("Avg Odds", 0)))
                    wp = "{:.1f}%".format(r.get("Win %", 0))
                    pick = r["Team"][:12]
                    sport = r.get("Sport", "")[:5]
                    rows.append(" {:>2}  {:<5} {:<24} {:>6} {:>6} {:>12}".format(i, sport, matchup, odds_str, wp, pick))
                msg = "**MONEYLINE PICKS - {}**\n```\n{}\n{}\n".format(today_str, hdr, sep)
                msg += "\n".join(rows) + "\n```"
                msg += "\nhttp://157.230.3.58/"
                send(WEBHOOKS["moneylines"], msg)
                print("MONEYLINES: {} picks sent to #moneylines".format(len(rows)))
            else:
                print("MONEYLINES: no games today")
        else:
            print("MONEYLINES: no data returned")
    else:
        print("MONEYLINES: no ODDS_API_KEY in .env")
except Exception as e:
    print("MONEYLINES failed: {}".format(e))

print("Done!")
