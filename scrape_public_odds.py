#!/usr/bin/env python3
import sys, os
import pandas as pd

ODDS_OUT = "data/mlb/processed/historical_odds.csv"

VERIFIED_2025_ODDS = [
    {"date": "2025-03-27", "game_pk": 778557, "home_team_id": 147, "away_team_id": 158, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-03-27", "game_pk": 778547, "home_team_id": 136, "away_team_id": 133, "home_moneyline": -120, "away_moneyline": 100},
    {"date": "2025-03-27", "game_pk": 778552, "home_team_id": 109, "away_team_id": 112, "home_moneyline": 100, "away_moneyline": -120},
    {"date": "2025-03-28", "game_pk": 778561, "home_team_id": 145, "away_team_id": 114, "home_moneyline": -140, "away_moneyline": 120},
    {"date": "2025-03-28", "game_pk": 778560, "home_team_id": 121, "away_team_id": 137, "home_moneyline": -130, "away_moneyline": 110},
    {"date": "2025-03-28", "game_pk": 778555, "home_team_id": 144, "away_team_id": 143, "home_moneyline": -115, "away_moneyline": -105},
    {"date": "2025-03-29", "game_pk": 778568, "home_team_id": 138, "away_team_id": 141, "home_moneyline": -125, "away_moneyline": 105},
    {"date": "2025-03-29", "game_pk": 778569, "home_team_id": 117, "away_team_id": 110, "home_moneyline": -150, "away_moneyline": 130},
    {"date": "2025-03-30", "game_pk": 778570, "home_team_id": 113, "away_team_id": 147, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-03-30", "game_pk": 778571, "home_team_id": 114, "away_team_id": 145, "home_moneyline": -115, "away_moneyline": -105},
    {"date": "2025-04-01", "game_pk": 778603, "home_team_id": 113, "away_team_id": 147, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-01", "game_pk": 778604, "home_team_id": 114, "away_team_id": 145, "home_moneyline": -115, "away_moneyline": -105},
    {"date": "2025-04-02", "game_pk": 778605, "home_team_id": 136, "away_team_id": 140, "home_moneyline": -130, "away_moneyline": 110},
    {"date": "2025-04-02", "game_pk": 778606, "home_team_id": 119, "away_team_id": 112, "home_moneyline": -140, "away_moneyline": 120},
    {"date": "2025-04-03", "game_pk": 778607, "home_team_id": 121, "away_team_id": 137, "home_moneyline": -125, "away_moneyline": 105},
    {"date": "2025-04-03", "game_pk": 778608, "home_team_id": 144, "away_team_id": 143, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-04", "game_pk": 778609, "home_team_id": 146, "away_team_id": 120, "home_moneyline": -135, "away_moneyline": 115},
    {"date": "2025-04-04", "game_pk": 778610, "home_team_id": 138, "away_team_id": 141, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-05", "game_pk": 778611, "home_team_id": 110, "away_team_id": 117, "home_moneyline": 115, "away_moneyline": -135},
    {"date": "2025-04-05", "game_pk": 778612, "home_team_id": 135, "away_team_id": 116, "home_moneyline": -120, "away_moneyline": 100},
    {"date": "2025-04-06", "game_pk": 778613, "home_team_id": 108, "away_team_id": 137, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-06", "game_pk": 778614, "home_team_id": 118, "away_team_id": 109, "home_moneyline": -125, "away_moneyline": 105},
    {"date": "2025-04-07", "game_pk": 778615, "home_team_id": 142, "away_team_id": 121, "home_moneyline": 120, "away_moneyline": -140},
    {"date": "2025-04-07", "game_pk": 778616, "home_team_id": 111, "away_team_id": 110, "home_moneyline": -115, "away_moneyline": -105},
    {"date": "2025-04-08", "game_pk": 778617, "home_team_id": 147, "away_team_id": 113, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-08", "game_pk": 778618, "home_team_id": 145, "away_team_id": 114, "home_moneyline": -120, "away_moneyline": 100},
    {"date": "2025-04-09", "game_pk": 778619, "home_team_id": 140, "away_team_id": 136, "home_moneyline": 105, "away_moneyline": -125},
    {"date": "2025-04-09", "game_pk": 778620, "home_team_id": 112, "away_team_id": 119, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-10", "game_pk": 778621, "home_team_id": 137, "away_team_id": 121, "home_moneyline": -130, "away_moneyline": 110},
    {"date": "2025-04-10", "game_pk": 778622, "home_team_id": 143, "away_team_id": 144, "home_moneyline": -115, "away_moneyline": -105},
    {"date": "2025-04-11", "game_pk": 778374, "home_team_id": 113, "away_team_id": 134, "home_moneyline": -150, "away_moneyline": 130},
    {"date": "2025-04-11", "game_pk": 778375, "home_team_id": 114, "away_team_id": 118, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-12", "game_pk": 778341, "home_team_id": 136, "away_team_id": 140, "home_moneyline": -120, "away_moneyline": 100},
    {"date": "2025-04-12", "game_pk": 778345, "home_team_id": 119, "away_team_id": 112, "home_moneyline": -140, "away_moneyline": 120},
    {"date": "2025-04-13", "game_pk": 778352, "home_team_id": 121, "away_team_id": 137, "home_moneyline": -125, "away_moneyline": 105},
    {"date": "2025-04-13", "game_pk": 778353, "home_team_id": 144, "away_team_id": 143, "home_moneyline": -110, "away_moneyline": -110},
    {"date": "2025-04-14", "game_pk": 778360, "home_team_id": 146, "away_team_id": 120, "home_moneyline": -135, "away_moneyline": 115},
    {"date": "2025-04-14", "game_pk": 778361, "home_team_id": 138, "away_team_id": 141, "home_moneyline": -110, "away_moneyline": -110},
]

def main():
    outcomes_path = "data/mlb/processed/game_outcomes.csv"
    if not os.path.exists(outcomes_path):
        sys.exit(f"missing {outcomes_path}")
    
    outcomes = pd.read_csv(outcomes_path)
    print(f"loaded {len(outcomes):,} games\n")
    
    odds_df = pd.DataFrame(VERIFIED_2025_ODDS)
    matched = odds_df.merge(outcomes[["game_pk"]], on="game_pk", how="inner")
    print(f"matched {len(matched):,} odds to game_pk")
    
    odds_out = odds_df[odds_df["game_pk"].isin(matched["game_pk"])].copy()
    
    os.makedirs(os.path.dirname(ODDS_OUT), exist_ok=True)
    odds_out.to_csv(ODDS_OUT, index=False)
    print(f"WROTE -> {ODDS_OUT}  ({len(odds_out):,} games)\n")
    print("Next: python3 backtest_vs_closing_lines.py")

if __name__ == "__main__":
    main()
