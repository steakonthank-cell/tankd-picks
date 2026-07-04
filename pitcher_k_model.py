#!/usr/bin/env python3
import sys, os
import pandas as pd
import numpy as np
from datetime import datetime

PITCHING_LOGS = "data/mlb/raw/pitching_logs.csv"
PITCHER_BACKTEST = "output/pitcher_k/backtest.csv"

def load_pitcher_logs():
    if not os.path.exists(PITCHING_LOGS):
        print(f"error: {PITCHING_LOGS} not found")
        return None
    df = pd.read_csv(PITCHING_LOGS)
    df['date'] = pd.to_datetime(df['date'])
    print(f"loaded {len(df):,} pitcher records ({df['date'].min().date()} → {df['date'].max().date()})")
    return df

def get_pitcher_k_rate(pitcher_id, as_of_date, logs, min_games=2):
    games = logs[(logs['player_id'] == pitcher_id) & (logs['date'] < as_of_date)]
    if len(games) < min_games:
        return None, None
    total_k = games['K'].sum()
    total_outs = games['OUTS'].sum()
    innings_pitched = total_outs / 3.0
    if innings_pitched == 0:
        return None, None
    k_per_9 = (total_k / innings_pitched) * 9
    return k_per_9, len(games)

def get_opponent_k_rate(opponent_id, as_of_date, logs, min_games=2):
    opp_games = logs[(logs['opponent_id'] == opponent_id) & (logs['date'] < as_of_date)]
    if len(opp_games) < min_games:
        return None
    total_k_faced = opp_games['K'].sum()
    total_batters = opp_games['batters_faced'].sum()
    if total_batters == 0:
        return None
    return total_k_faced / total_batters

def predict_pitcher_k(pitcher_id, pitcher_name, opponent_id, game_date, logs):
    k_per_9, games = get_pitcher_k_rate(pitcher_id, game_date, logs, min_games=2)
    if k_per_9 is None:
        return None
    opp_k_rate = get_opponent_k_rate(opponent_id, game_date, logs, min_games=2)
    if opp_k_rate is None:
        predicted_ks = (k_per_9 / 9) * 6
    else:
        predicted_ks = 0.6 * ((k_per_9 / 9) * 6) + 0.4 * (25 * opp_k_rate)
    return {"pitcher_id": pitcher_id, "pitcher_name": pitcher_name, "date": game_date, "opponent_id": opponent_id, "k_per_9": round(k_per_9, 2), "predicted_k": round(predicted_ks, 1)}

def main():
    logs = load_pitcher_logs()
    if logs is None:
        return
    
    print("\n=== PITCHER K BACKTEST ===\n")
    
    logs_sorted = logs.sort_values('date')
    starters = logs_sorted[logs_sorted['is_starter'] == 1].copy()
    
    print(f"backtesting {len(starters):,} starter appearances\n")
    
    predictions = []
    for idx, (i, game) in enumerate(starters.iterrows()):
        if idx % 5000 == 0 and idx > 0:
            print(f"  processed {idx:,}...")
        
        pred = predict_pitcher_k(game['player_id'], game['player_name'], game['opponent_id'], game['date'], logs_sorted.loc[:i])
        if pred is None:
            continue
        
        pred['actual_k'] = game['K']
        pred['error'] = abs(pred['predicted_k'] - pred['actual_k'])
        predictions.append(pred)
    
    pred_df = pd.DataFrame(predictions)
    if len(pred_df) == 0:
        print("no predictions")
        return
    
    mae = pred_df['error'].mean()
    rmse = np.sqrt((pred_df['error'] ** 2).mean())
    corr = pred_df[['predicted_k', 'actual_k']].corr().iloc[0, 1]
    
    print(f"\ngraded {len(pred_df):,} predictions\n")
    print(f"mean absolute error: {mae:.2f} Ks")
    print(f"RMSE: {rmse:.2f} Ks")
    print(f"correlation: {corr:.3f}\n")
    
    print("sample predictions:\n")
    print(pred_df[['pitcher_name', 'date', 'k_per_9', 'predicted_k', 'actual_k', 'error']].head(15).to_string(index=False))
    
    os.makedirs(os.path.dirname(PITCHER_BACKTEST), exist_ok=True)
    pred_df.to_csv(PITCHER_BACKTEST, index=False)
    print(f"\n\nWROTE -> {PITCHER_BACKTEST}")

if __name__ == "__main__":
    main()
