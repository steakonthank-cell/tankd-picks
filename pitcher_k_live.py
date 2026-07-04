#!/usr/bin/env python3
import sys, os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests

PITCHING_LOGS = "data/mlb/raw/pitching_logs.csv"
OUTPUT_DIR = "output/pitcher_k"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1511425913315655901/RFyJ8dtvvqmjKYvoVU_qvv1UQbGZONjhgjgj0ej0bkOglQiC5gPR_u2xynErBho7JI1I"

def load_pitcher_logs():
    if not os.path.exists(PITCHING_LOGS):
        return None
    df = pd.read_csv(PITCHING_LOGS)
    df['date'] = pd.to_datetime(df['date'])
    return df

def get_pitcher_k_rate(pitcher_id, as_of_date, logs):
    games = logs[(logs['player_id'] == pitcher_id) & (logs['date'] < as_of_date)]
    if len(games) < 2:
        return None, None
    total_k = games['K'].sum()
    total_outs = games['OUTS'].sum()
    innings = total_outs / 3.0
    if innings == 0:
        return None, None
    k_per_9 = (total_k / innings) * 9
    return k_per_9, len(games)

def get_opponent_k_rate(opponent_id, as_of_date, logs):
    opp_games = logs[(logs['opponent_id'] == opponent_id) & (logs['date'] < as_of_date)]
    if len(opp_games) < 2:
        return None
    total_k = opp_games['K'].sum()
    total_batters = opp_games['batters_faced'].sum()
    return total_k / total_batters if total_batters > 0 else None

def predict_pitcher_k(pitcher_id, pitcher_name, opponent_id, game_date, logs):
    k_per_9, games = get_pitcher_k_rate(pitcher_id, game_date, logs)
    if k_per_9 is None:
        return None
    opp_k_rate = get_opponent_k_rate(opponent_id, game_date, logs)
    if opp_k_rate is None:
        pred_k = (k_per_9 / 9) * 6
    else:
        pred_k = 0.6 * ((k_per_9 / 9) * 6) + 0.4 * (25 * opp_k_rate)
    return {"pitcher_name": pitcher_name, "k_per_9": round(k_per_9, 2), "predicted_k": round(pred_k, 1), "opp_k_rate": round(opp_k_rate, 3) if opp_k_rate else 0}

def send_to_discord(picks, date):
    try:
        embeds = []
        for pitcher_name, pred in picks.items():
            embed = {"title": pitcher_name, "description": f"Predicted K: **{pred['predicted_k']}**", "color": 0x0099ff, "fields": [{"name": "K/9 Season", "value": str(pred['k_per_9']), "inline": True}, {"name": "Opp K%", "value": str(pred['opp_k_rate']), "inline": True}]}
            embeds.append(embed)
        payload = {"username": "Tank'd Picks Pitcher K", "content": f"⚾ **Pitcher K Predictions** ({date})", "embeds": embeds[:25]}
        resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if resp.status_code == 204:
            print(f"✓ Sent {len(picks)} pitcher K picks to Discord")
            return True
        else:
            print(f"Discord {resp.status_code}")
            return False
    except Exception as e:
        print(f"Discord error: {e}")
        return False

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n=== PITCHER K LIVE INFERENCE [{today}] ===\n")
    logs = load_pitcher_logs()
    if logs is None:
        print("error: pitching logs not found")
        return
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    demo_starters = logs[logs['date'] == yesterday][logs['is_starter'] == 1].head(8)
    if len(demo_starters) == 0:
        demo_starters = logs[logs['is_starter'] == 1].sort_values('date').tail(8)
    print(f"found {len(demo_starters)} pitchers\n")
    picks = {}
    for _, game in demo_starters.iterrows():
        pred = predict_pitcher_k(game['player_id'], game['player_name'], game['opponent_id'], game['date'], logs)
        if pred:
            picks[game['player_name']] = pred
            print(f"  {game['player_name']:30s} | K/9: {pred['k_per_9']:5.2f} | Pred K: {pred['predicted_k']:4.1f}")
    print(f"\ngenerated {len(picks)} predictions\n")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pred_df = pd.DataFrame([{"pitcher": p, **v} for p, v in picks.items()])
    pred_df.to_csv(f"{OUTPUT_DIR}/latest.csv", index=False)
    print(f"WROTE -> {OUTPUT_DIR}/latest.csv\n")
    if len(picks) > 0:
        print("Sending to Discord...\n")
        send_to_discord(picks, yesterday)

if __name__ == "__main__":
    main()
