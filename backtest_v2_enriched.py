#!/usr/bin/env python3
import sys, os
import numpy as np
import pandas as pd

GAME_OUTCOMES = "data/mlb/processed/game_outcomes.csv"
BACKTEST_PREDS = "data/mlb/processed/backtest_preds.csv"
ODDS = "data/mlb/processed/historical_odds.csv"
OUT = "data/mlb/processed/backtest_v2_enriched.csv"

PARK_FACTORS = {
    108: 0.02, 109: 0.04, 110: -0.01, 111: -0.03, 112: 0.03, 113: 0.05,
    114: -0.02, 115: 0.06, 116: 0.01, 117: 0.02, 118: -0.01, 119: 0.03,
    120: -0.02, 121: -0.04, 133: -0.01, 134: 0.04, 135: 0.02, 136: -0.03,
    137: -0.01, 138: 0.01, 139: -0.01, 140: 0.04, 141: 0.02, 142: 0.01,
    143: 0.03, 144: 0.05, 145: 0.02, 146: -0.02, 147: 0.04, 158: 0.02,
}

def get_rest_factor(home_team, away_team, game_date, outcomes):
    try:
        home_prev = outcomes[(outcomes["home_team_id"] == home_team) & (outcomes["date"] < game_date)].sort_values("date").tail(1)
        away_prev = outcomes[(outcomes["away_team_id"] == away_team) & (outcomes["date"] < game_date)].sort_values("date").tail(1)
        if len(home_prev) == 0 or len(away_prev) == 0: return 0.0
        home_rest = (pd.to_datetime(game_date) - pd.to_datetime(home_prev.iloc[0]["date"])).days
        away_rest = (pd.to_datetime(game_date) - pd.to_datetime(away_prev.iloc[0]["date"])).days
        rest_diff = min(3, max(-3, home_rest - away_rest))
        return rest_diff * 0.01
    except: return 0.0

def get_weather_factor(game_date):
    try:
        month = pd.to_datetime(game_date).month
        if month in [3, 4, 10]: return -0.01
        elif month in [7, 8]: return 0.01
        else: return 0.0
    except: return 0.0

def american_to_implied(american):
    if pd.isna(american) or american == 0: return np.nan
    if american > 0: return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)

def american_to_decimal(american):
    if pd.isna(american) or american == 0: return np.nan
    if american > 0: return (american / 100) + 1
    return (100 / abs(american)) + 1

def main():
    if not os.path.exists(BACKTEST_PREDS): sys.exit(f"missing {BACKTEST_PREDS}")
    if not os.path.exists(ODDS): sys.exit(f"missing {ODDS}")
    if not os.path.exists(GAME_OUTCOMES): sys.exit(f"missing {GAME_OUTCOMES}")
    
    preds = pd.read_csv(BACKTEST_PREDS)
    odds = pd.read_csv(ODDS)
    outcomes = pd.read_csv(GAME_OUTCOMES)
    
    m = preds.merge(odds, on="game_pk", how="inner", suffixes=("_pred", "_odds"))
    
    print(f"merged {len(m):,} games\n")
    if len(m) == 0: sys.exit("No games matched")
    
    home_team_col = "home_team_id_pred" if "home_team_id_pred" in m.columns else "home_team_id"
    away_team_col = "away_team_id_pred" if "away_team_id_pred" in m.columns else "away_team_id"
    date_col = "date_pred" if "date_pred" in m.columns else "date"
    
    print("applying enrichments...")
    m["park_factor_home"] = m[home_team_col].apply(lambda tid: PARK_FACTORS.get(tid, 0.0))
    m["rest_factor"] = m.apply(lambda row: get_rest_factor(row[home_team_col], row[away_team_col], row[date_col], outcomes), axis=1)
    m["weather_factor"] = m.apply(lambda row: get_weather_factor(row[date_col]), axis=1)
    
    m["total_multiplier"] = 1.0 + m["park_factor_home"] + m["rest_factor"] + m["weather_factor"]
    m["p_home_enriched"] = (m["p_home"] * m["total_multiplier"]).clip(0, 1)
    m["line_prob_home"] = m["home_moneyline"].apply(american_to_implied)
    m["edge"] = m["p_home_enriched"] - m["line_prob_home"]
    
    print(f"  park factors: mean {m['park_factor_home'].mean()*100:+.2f}%")
    print(f"  rest factors: mean {m['rest_factor'].mean()*100:+.2f}%")
    print(f"  enriched p_home: mean {m['p_home_enriched'].mean():.3f}\n")
    
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
    
    print(f"=== BACKTEST V2 (ENRICHED PYTHAGOREAN) ===")
    print(f"total bets: {total_bets} | accuracy: {win_rate:.3f} | P&L: {total_roi:+.2f} | ROI: {(total_roi/total_bets)*100:+.1f}%\n")
    
    if total_roi > 0:
        print(f"✓ PASS — Enriched model beats closing line!")
    elif total_roi > -0.5:
        print(f"⚠ MARGINAL — Still near break-even.")
    else:
        print(f"✗ FAIL — Model loses.")
    
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    m[["game_pk", "p_home", "p_home_enriched", "home_win", "edge", "pnl"]].to_csv(OUT, index=False)
    print(f"\nWROTE -> {OUT}")

if __name__ == "__main__":
    main()
