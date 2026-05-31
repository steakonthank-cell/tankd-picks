"""
MLB Feature Engineering Pipeline

Transforms raw batter/pitcher game logs into rolling-average features
for XGBoost model training.

Batter features: L5/L10/L20 rolling averages of H, TB, HR, RBI, R, SO, BB
Pitcher features: L3/L5/L10 rolling averages of K, ER, OUTS, HA, BBA

Output:
    data/mlb/processed/batter_training.csv
    data/mlb/processed/pitcher_training.csv

Usage:
    $ python3 -m src.sports.mlb.features
"""

import pandas as pd
import numpy as np
import os

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_DIR       = os.path.join(BASE_DIR, 'data', 'mlb', 'raw')
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'mlb', 'processed')

BATTING_RAW  = os.path.join(RAW_DIR,       'batting_logs.csv')
PITCHING_RAW = os.path.join(RAW_DIR,       'pitching_logs.csv')
BATTER_OUT   = os.path.join(PROCESSED_DIR, 'batter_training.csv')
PITCHER_OUT  = os.path.join(PROCESSED_DIR, 'pitcher_training.csv')

BATTER_TARGETS  = ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB']
PITCHER_TARGETS = ['K', 'ER', 'OUTS']

BATTER_ROLL_STATS  = ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB', 'AB', 'SB']
PITCHER_ROLL_STATS = ['K', 'ER', 'OUTS', 'HA', 'BBA', 'HR_A', 'pitches']

BATTER_WINDOWS  = [5, 10, 20]
PITCHER_WINDOWS = [3, 5, 10]


def _rolling_avg(group_df, stat, window):
    return group_df[stat].shift(1).rolling(window, min_periods=1).mean()


def build_batter_features(df):
    print(f"   Building batter features from {len(df):,} game rows...")
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date', 'player_id'])
    df = df.sort_values(['player_id', 'date']).reset_index(drop=True)

    df['AB'] = pd.to_numeric(df.get('AB', 0), errors='coerce').fillna(0)

    feature_cols = []

    for stat in BATTER_ROLL_STATS:
        if stat not in df.columns:
            continue
        df[stat] = pd.to_numeric(df[stat], errors='coerce').fillna(0)

        for w in BATTER_WINDOWS:
            col = f'{stat}_L{w}'
            df[col] = (
                df.groupby('player_id', group_keys=False)
                  .apply(lambda g: _rolling_avg(g, stat, w))
            )
            feature_cols.append(col)

        # Season average (within same season, prior games only)
        col_season = f'{stat}_season_avg'
        df[col_season] = (
            df.groupby(['player_id', 'season'], group_keys=False)
              .apply(lambda g: g[stat].shift(1).expanding().mean())
        )
        feature_cols.append(col_season)

    # Season games played
    df['games_played'] = (
        df.groupby(['player_id', 'season'], group_keys=False)
          .apply(lambda g: g['AB'].shift(1).expanding().count())
    )
    feature_cols.append('games_played')

    # Context features
    df['is_home'] = pd.to_numeric(df.get('is_home', 0), errors='coerce').fillna(0)
    feature_cols.append('is_home')

    df = df.dropna(subset=['H'])
    df = df[df['AB'] > 0]

    print(f"   Batter features built: {len(feature_cols)} features, {len(df):,} rows")
    return df, feature_cols


def build_pitcher_features(df):
    print(f"   Building pitcher features from {len(df):,} game rows...")
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date', 'player_id'])
    df = df.sort_values(['player_id', 'date']).reset_index(drop=True)

    feature_cols = []

    for stat in PITCHER_ROLL_STATS:
        if stat not in df.columns:
            continue
        df[stat] = pd.to_numeric(df[stat], errors='coerce').fillna(0)

        for w in PITCHER_WINDOWS:
            col = f'{stat}_L{w}'
            df[col] = (
                df.groupby('player_id', group_keys=False)
                  .apply(lambda g: _rolling_avg(g, stat, w))
            )
            feature_cols.append(col)

        col_season = f'{stat}_season_avg'
        df[col_season] = (
            df.groupby(['player_id', 'season'], group_keys=False)
              .apply(lambda g: g[stat].shift(1).expanding().mean())
        )
        feature_cols.append(col_season)

    # Starter flag
    if 'is_starter' in df.columns:
        df['is_starter'] = pd.to_numeric(df['is_starter'], errors='coerce').fillna(0)
        feature_cols.append('is_starter')

    df['is_home'] = pd.to_numeric(df.get('is_home', 0), errors='coerce').fillna(0)
    feature_cols.append('is_home')

    df['apps_season'] = (
        df.groupby(['player_id', 'season'], group_keys=False)
          .apply(lambda g: g['OUTS'].shift(1).expanding().count())
    )
    feature_cols.append('apps_season')

    df = df.dropna(subset=['K'])
    df = df[df['OUTS'] > 0]

    print(f"   Pitcher features built: {len(feature_cols)} features, {len(df):,} rows")
    return df, feature_cols


def main():
    print("=" * 60)
    print("   ⚾ MLB FEATURE ENGINEERING")
    print("=" * 60)

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # --- BATTERS ---
    if not os.path.exists(BATTING_RAW):
        print(f"❌ Batting logs not found at {BATTING_RAW}. Run builder.py first.")
    else:
        print("\n[1/2] Batters")
        df_bat = pd.read_csv(BATTING_RAW, low_memory=False)
        df_bat, _ = build_batter_features(df_bat)
        df_bat.to_csv(BATTER_OUT, index=False)
        print(f"   ✅  Saved → {BATTER_OUT}")

    # --- PITCHERS ---
    if not os.path.exists(PITCHING_RAW):
        print(f"❌ Pitching logs not found at {PITCHING_RAW}. Run builder.py first.")
    else:
        print("\n[2/2] Pitchers")
        df_pit = pd.read_csv(PITCHING_RAW, low_memory=False)
        df_pit, _ = build_pitcher_features(df_pit)
        df_pit.to_csv(PITCHER_OUT, index=False)
        print(f"   ✅  Saved → {PITCHER_OUT}")

    print("\n" + "=" * 60)
    print("✅  FEATURES COMPLETE — Next: Run train.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
