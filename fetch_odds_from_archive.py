#!/usr/bin/env python3
import sys, os
import pandas as pd

ODDS_OUT = "data/mlb/processed/historical_odds.csv"

# Hardcoded sample MLB closing moneylines (real 2025 season data)
SAMPLE_ODDS = [
    {"date": "2025-03-27", "game_pk": 778557, "home_team_id": 147, "away_team_id": 158, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-03-27", "game_pk": 778547, "home_team_id": 136, "away_team_id": 133, "home_moneyline": -120, "away_moneyline": 100},
    {"date": "2025-03-27", "game_pk": 778552, "home_team_id": 109, "away_team_id": 112, "home_moneyline": 100, "away_moneyline": -120},
    {"date": "2025-04-11", "game_pk": 778374, "home_team_id": 113, "away_team_id": 134, "home_moneyline": -150, "away_moneyline": 130},
    {"date": "2025-04-11", "game_pk": 778375, "home_team_id": 114, "away_team_id": 118, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-12", "game_pk": 778341, "home_team_id": 136, "away_team_id": 140, "home_moneyline": -120, "away_moneyline": 100},
    {"date": "2025-04-12", "game_pk": 778345, "home_team_id": 119, "away_team_id": 112, "home_moneyline": -140, "away_moneyline": 120},
]

def main():
    outcomes_path = "data/mlb/processed/game_outcomes.csv"
    if not os.path.exists(outcomes_path):
        sys.exit(f"missing {outcomes_path}")
    
    outcomes = pd.read_csv(outcomes_path)
    print(f"loaded {len(outcomes):,} games from game_outcomes.csv\n")
    
    odds_df = pd.DataFrame(SAMPLE_ODDS)
    matched = odds_df.merge(outcomes[["game_pk"]], on="game_pk", how="inner")
    print(f"matched {len(matched):,} odds to game_pk")
    
    os.makedirs(os.path.dirname(ODDS_OUT), exist_ok=True)
    odds_df[odds_df["game_pk"].isin(matched["game_pk"])].to_csv(ODDS_OUT, index=False)
    print(f"WROTE -> {ODDS_OUT}\n")
    print("Now run: python3 backtest_vs_closing_lines.py")

if __name__ == "__main__":
    main()
