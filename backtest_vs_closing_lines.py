#!/usr/bin/env python3
import sys, os
import numpy as np
import pandas as pd

PREDS = "data/mlb/processed/backtest_preds.csv"
ODDS = "data/mlb/processed/historical_odds.csv"
OUT = "data/mlb/processed/backtest_vs_line.csv"

def american_to_implied(american):
    if pd.isna(american) or american == 0: return np.nan
    if american > 0: return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)

def american_to_decimal(american):
    if pd.isna(american) or american == 0: return np.nan
    if american > 0: return (american / 100) + 1
    return (100 / abs(american)) + 1

def main():
    if not os.path.exists(PREDS): sys.exit(f"missing {PREDS}")
    if not os.path.exists(ODDS): sys.exit(f"missing {ODDS}")
    
    preds = pd.read_csv(PREDS)
    odds = pd.read_csv(ODDS)
    m = preds.merge(odds, on="game_pk", how="inner", suffixes=("_preds", "_odds"))
    
    print(f"  merged {len(m):,} games\n")
    if len(m) == 0: sys.exit("No games matched")
    
    m["line_prob_home"] = m["home_moneyline"].apply(american_to_implied)
    m["edge"] = m["p_home"] - m["line_prob_home"]
    
    BET_THRESHOLD = 0.04
    m["bet_home"] = (m["edge"] > BET_THRESHOLD).astype(int)
    m["bet_away"] = (m["edge"] < -BET_THRESHOLD).astype(int)
    m["took_bet"] = (m["bet_home"] | m["bet_away"]).astype(int)
    
    m["home_decimal"] = m["home_moneyline"].apply(american_to_decimal)
    m["away_decimal"] = m["away_moneyline"].apply(american_to_decimal)
    
    m["pnl"] = 0.0
    home_bet = m["bet_home"] == 1
    m.loc[home_bet & (m["home_win"] == 1), "pnl"] = m.loc[home_bet & (m["home_win"] == 1), "home_decimal"] - 1
    m.loc[home_bet & (m["home_win"] == 0), "pnl"] = -1.0
    
    away_bet = m["bet_away"] == 1
    m.loc[away_bet & (m["home_win"] == 0), "pnl"] = m.loc[away_bet & (m["home_win"] == 0), "away_decimal"] - 1
    m.loc[away_bet & (m["home_win"] == 1), "pnl"] = -1.0
    
    bets_taken = m[m["took_bet"] == 1]
    total_bets = len(bets_taken)
    total_roi = bets_taken["pnl"].sum() if total_bets > 0 else 0
    win_rate = (bets_taken["pnl"] > 0).sum() / total_bets if total_bets > 0 else 0
    
    print(f"  === BACKTEST VS CLOSING LINES ===")
    print(f"  total bets: {total_bets} | accuracy: {win_rate:.3f} | P&L: {total_roi:+.2f} | ROI: {(total_roi/total_bets)*100:+.1f}%\n")
    
    if total_roi > 0:
        print(f"  ✓ PASS — Model beats closing line.")
    elif total_roi > -0.5:
        print(f"  ⚠ MARGINAL — Near break-even.")
    else:
        print(f"  ✗ FAIL — Model loses money.")
    
    cols_out = ["game_pk", "p_home", "pred_home_win", "home_win", "home_moneyline", "edge", "pnl"]
    cols_out = [c for c in cols_out if c in m.columns]
    m[cols_out].to_csv(OUT, index=False)
    print(f"\nWROTE -> {OUT}")

if __name__ == "__main__":
    main()
