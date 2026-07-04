#!/usr/bin/env python3
import os, sys, unicodedata
import pandas as pd
import numpy as np
from datetime import datetime
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PITCHING_LOGS = "data/mlb/raw/pitching_logs.csv"
OUTPUT_DIR = "output/pitcher_k"
DISCORD_WEBHOOK = os.getenv("MLB_PITCHER_WEBHOOK")
CHUNK = 10
IP_LOOKBACK_STARTS = 5

# Today's confirmed starters (June 16 2026) -- (pitcher_name, opponent_team_abbr)
# opponent = the TEAM THE PITCHER IS FACING
TODAYS_STARTERS = [
    ("Tyler Phillips", "PHI"), ("Jesus Luzardo", "MIA"), ("Dylan Cease", "BOS"),
    ("Payton Tolle", "TOR"), ("Michael Wacha", "WSH"), ("Foster Griffin", "KC"),
    ("Davis Martin", "NYY"), ("Gerrit Cole", "CWS"), ("Kodai Senga", "CIN"),
    ("Brady Singer", "NYM"), ("Adrian Houser", "ATL"), ("Grant Holmes", "SF"),
    ("Slade Cecconi", "MIL"), ("Robert Gasser", "CLE"), ("Michael King", "STL"),
    ("Andre Pallante", "SD"), ("Zebby Matthews", "TEX"), ("Kumar Rocker", "MIN"),
    ("Ryan Feltner", "CHC"), ("Edward Cabrera", "COL"), ("Framber Valdez", "HOU"),
    ("Hunter Brown", "DET"), ("Mitch Keller", "ATH"), ("Jack Perkins", "PIT"),
    ("Drew Rasmussen", "LAD"), ("Justin Wrobleski", "TB"), ("Brandon Young", "SEA"),
    ("Logan Gilbert", "BAL"), ("Reid Detmers", "ARI"), ("Merrill Kelly", "LAA"),
]

USE_OPPONENT_TERM = True
# MLB Stats API team IDs (opponent_id in logs uses these)
ABBR_TO_OPPID = {
    "ATH": 133, "OAK": 133, "PIT": 134, "SD": 135, "SEA": 136, "SF": 137,
    "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "MIN": 142, "PHI": 143,
    "ATL": 144, "CWS": 145, "CHW": 145, "MIA": 146, "NYY": 147, "MIL": 158,
    "LAA": 108, "ARI": 109, "BAL": 110, "BOS": 111, "CHC": 112, "CIN": 113,
    "CLE": 114, "COL": 115, "DET": 116, "HOU": 117, "KC": 118, "LAD": 119,
    "WSH": 120, "WSN": 120, "NYM": 121,
}

def norm(n):
    if not isinstance(n, str):
        return ""
    n = unicodedata.normalize("NFD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().replace(".", "").replace("-", " ")
    return " ".join(n.split())

def load_logs():
    df = pd.read_csv(PITCHING_LOGS)
    df['date'] = pd.to_datetime(df['date'])
    df['_nm'] = df['player_name'].apply(norm)
    return df

def pitcher_krate(pid, as_of, logs):
    g = logs[(logs['player_id'] == pid) & (logs['date'] < as_of)]
    if len(g) < 2:
        return None, 0
    ip = g['OUTS'].sum() / 3.0
    if ip == 0:
        return None, 0
    return (g['K'].sum() / ip) * 9, len(g)

def pitcher_ip(pid, as_of, logs):
    g = logs[(logs['player_id'] == pid) & (logs['date'] < as_of)]
    if 'is_starter' in g.columns:
        gs = g[g['is_starter'] == 1]
        if len(gs) >= 3:
            g = gs
    if len(g) == 0:
        return 5.5
    g = g.sort_values('date').tail(IP_LOOKBACK_STARTS)
    return (g['OUTS'].sum() / len(g)) / 3.0

def opp_krate(opp_id, as_of, logs):
    g = logs[(logs['opponent_id'] == opp_id) & (logs['date'] < as_of)]
    if len(g) < 2:
        return None
    bf = g['batters_faced'].sum()
    return g['K'].sum() / bf if bf > 0 else None

def find_pid(name, logs):
    t = norm(name)
    m = logs[logs['_nm'] == t]
    if len(m) == 0:
        last = t.split()[-1] if t else ""
        m = logs[logs['_nm'].str.endswith(" " + last)]
        if len(m) == 0:
            return None
    return int(m.sort_values('date').iloc[-1]['player_id'])

def predict(pid, opp_id, as_of, logs):
    k9, ng = pitcher_krate(pid, as_of, logs)
    if k9 is None:
        return None
    ip = pitcher_ip(pid, as_of, logs)
    base = (k9 / 9) * ip
    ok = opp_krate(opp_id, as_of, logs) if (USE_OPPONENT_TERM and opp_id is not None) else None
    pred = base if ok is None else 0.6 * base + 0.4 * ((ip * 4.3) * ok)
    return {"k": round(k9, 2), "ip": round(ip, 1), "pred_k": round(pred, 1),
            "ok": round(ok * 100, 1) if ok else "", "ng": ng}

def send_discord(picks, date):
    if not DISCORD_WEBHOOK:
        print("ERROR: MLB_PITCHER_WEBHOOK not set in .env -- skipping send")
        return False
    import time
    embeds = [{"title": n, "description": f"Predicted K: **{p['pred_k']}**", "color": 0x0099ff,
               "fields": [{"name": "K/9", "value": str(p['k']), "inline": True},
                          {"name": "Exp IP", "value": str(p['ip']), "inline": True},
                          {"name": "Opp K%", "value": (str(p['ok']) if p['ok'] != "" else "n/a"), "inline": True}]}
              for n, p in picks.items()]
    ok_all = True
    for i in range(0, len(embeds), CHUNK):
        batch = embeds[i:i+CHUNK]
        payload = {"username": "Tank'd Picks Pitcher K", "embeds": batch}
        if i == 0:
            payload["content"] = f"\u26be **Pitcher K Predictions** ({date})"
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        tail = "" if r.status_code == 204 else f"  {r.text[:200]}"
        print(f"batch {i//CHUNK + 1} ({len(batch)}): Discord {r.status_code}{tail}")
        if r.status_code != 204:
            ok_all = False
        time.sleep(0.6)
    return ok_all

def main():
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    as_of = pd.Timestamp(today.date())
    print(f"\n=== PITCHER K LIVE -- TODAY'S SLATE [{today_str}] (opp term ON) ===\n")
    logs = load_logs()
    picks, missing = {}, []
    for name, abbr in TODAYS_STARTERS:
        pid = find_pid(name, logs)
        if pid is None:
            missing.append(name + " (no logs)")
            continue
        opp_id = ABBR_TO_OPPID.get(abbr) if USE_OPPONENT_TERM else None
        pred = predict(pid, opp_id, as_of, logs)
        if pred is None:
            missing.append(name + " (<2 games)")
            continue
        picks[name] = pred
        oks = f"{pred['ok']}%" if pred['ok'] != "" else "n/a"
        print(f"  {name:25s} | K/9: {pred['k']:5.2f} | ExpIP: {pred['ip']:4.1f} | OppK: {oks:6s} | Pred K: {pred['pred_k']:4.1f}")
    print(f"\ngenerated {len(picks)} predictions")
    if missing:
        print("skipped: " + ", ".join(missing))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pd.DataFrame([{"pitcher": p, **v} for p, v in picks.items()]).to_csv(f"{OUTPUT_DIR}/latest.csv", index=False)
    print(f"\nWROTE -> {OUTPUT_DIR}/latest.csv")
    if picks:
        print("\nSending to Discord...\n")
        send_discord(picks, today_str)

if __name__ == "__main__":
    main()
