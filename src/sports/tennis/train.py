"""
Tennis XGBoost + LightGBM Ensemble Training Pipeline

Trains separate regression models for 7 tennis markets using time-series
split validation. 60% XGBoost / 40% LightGBM ensemble per target,
with tiered hyperparameters based on stat volatility.

Targets:
    total_games, games_won, total_sets, aces,
    bp_won, total_tiebreaks, double_faults

Output:
    models/tennis/{TARGET}_model.json       (XGBoost)
    models/tennis/{TARGET}_model_lgbm.txt   (LightGBM)
    models/tennis/model_metrics.csv

Usage:
    $ python3 -m src.sports.tennis.train
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import lightgbm as lgb
import os
import csv
from datetime import datetime
from sklearn.metrics import mean_absolute_error, r2_score

# --- CONFIGURATION ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_FILE  = os.path.join(BASE_DIR, 'data',   'tennis', 'processed', 'training_dataset.csv')
MODEL_DIR  = os.path.join(BASE_DIR, 'models', 'tennis')

TEST_FRACTION = 0.10

ENSEMBLE_WEIGHT_XGB  = 0.60
ENSEMBLE_WEIGHT_LGBM = 0.40

TARGETS = [
    'total_games',
    'games_won',
    'total_sets',
    'aces',
    'bp_won',
    'total_tiebreaks',
    'double_faults',
]

# Tiered volatility — determines hyperparameter aggression
# HIGH = predictable counting stats, MEDIUM = moderate variance, LOW = rare/noisy
TARGET_TIER = {
    'total_games':    'HIGH',
    'games_won':      'HIGH',
    'total_sets':     'HIGH',
    'aces':           'MEDIUM',
    'bp_won':         'MEDIUM',
    'total_tiebreaks':'LOW',
    'double_faults':  'LOW',
}

# ── XGBoost hyperparameters by tier ──────────────────────────────────────────
_XGB_HIGH = dict(
    n_estimators=600, learning_rate=0.04, max_depth=6,
    subsample=0.85, colsample_bytree=0.85,
    min_child_weight=4, reg_alpha=0.05, reg_lambda=1.0,
    random_state=42, n_jobs=-1, verbosity=0,
)
_XGB_MEDIUM = dict(
    n_estimators=500, learning_rate=0.05, max_depth=5,
    subsample=0.80, colsample_bytree=0.80,
    min_child_weight=6, reg_alpha=0.10, reg_lambda=1.2,
    random_state=42, n_jobs=-1, verbosity=0,
)
_XGB_LOW = dict(
    n_estimators=400, learning_rate=0.03, max_depth=4,
    subsample=0.75, colsample_bytree=0.75,
    min_child_weight=10, reg_alpha=0.20, reg_lambda=2.0,
    random_state=42, n_jobs=-1, verbosity=0,
)
XGB_PARAMS = {'HIGH': _XGB_HIGH, 'MEDIUM': _XGB_MEDIUM, 'LOW': _XGB_LOW}

# ── LightGBM hyperparameters by tier ─────────────────────────────────────────
_LGBM_HIGH = dict(
    n_estimators=600, learning_rate=0.04, max_depth=6,
    num_leaves=50, subsample=0.85, colsample_bytree=0.85,
    min_child_samples=20, reg_alpha=0.05, reg_lambda=1.0,
    random_state=42, n_jobs=-1, verbosity=-1,
)
_LGBM_MEDIUM = dict(
    n_estimators=500, learning_rate=0.05, max_depth=5,
    num_leaves=40, subsample=0.80, colsample_bytree=0.80,
    min_child_samples=30, reg_alpha=0.10, reg_lambda=1.2,
    random_state=42, n_jobs=-1, verbosity=-1,
)
_LGBM_LOW = dict(
    n_estimators=400, learning_rate=0.03, max_depth=4,
    num_leaves=31, subsample=0.75, colsample_bytree=0.75,
    min_child_samples=50, reg_alpha=0.20, reg_lambda=2.0,
    random_state=42, n_jobs=-1, verbosity=-1,
)
LGBM_PARAMS = {'HIGH': _LGBM_HIGH, 'MEDIUM': _LGBM_MEDIUM, 'LOW': _LGBM_LOW}

# Core features
FEATURES = [
    'surface_hard', 'surface_clay', 'surface_grass', 'surface_carpet',
    'is_best_of_5', 'round_ordinal', 'is_atp',
    'player_rank', 'opp_rank', 'rank_delta', 'rank_ratio',
    'log_rank', 'log_opp_rank',
    'days_rest', 'matches_L14D', 'is_b2b',
    'h2h_win_rate', 'h2h_avg_games',
    'career_win_pct_vs_top20', 'career_win_pct_vs_top50', 'career_win_pct_vs_top100',
    'career_matches', 'is_early_career',
]

for stat in ['aces', 'double_faults', 'total_games', 'games_won', 'bp_won']:
    for surf in ['hard', 'clay', 'grass']:
        FEATURES.append(f'opp_{stat}_{surf}_L10')

for stat in TARGETS + ['won_match', 'sets_won', 'bp_faced', 'svpt', 'svc_games']:
    for window in ['L5', 'L20', 'Season']:
        FEATURES.append(f'{stat}_{window}')

for stat in ['aces', 'double_faults', 'total_games', 'games_won', 'bp_won']:
    for surf in ['hard', 'clay', 'grass']:
        FEATURES.append(f'{stat}_{surf}_L10')

for stat in ['total_games', 'games_won', 'aces', 'double_faults', 'bp_won', 'bp_faced']:
    for window in ['L5', 'L20']:
        FEATURES.append(f'opp_{stat}_{window}')


def train_and_evaluate():
    print("=" * 60)
    print("   🎾 TENNIS MODEL TRAINING  (XGBoost + LightGBM Ensemble)")
    print("=" * 60)

    if not os.path.exists(DATA_FILE):
        print(f"ERROR: Training data not found at {DATA_FILE}")
        print("       Run features.py first.")
        return

    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['tourney_date'] = pd.to_datetime(df['tourney_date'], errors='coerce')
    df = df.dropna(subset=['tourney_date'])
    df = df.sort_values('tourney_date').reset_index(drop=True)

    split_idx      = int(len(df) * (1 - TEST_FRACTION))
    split_date     = df.iloc[split_idx]['tourney_date']
    test_start_str = split_date.strftime('%Y-%m-%d')

    print(f"Loaded {len(df):,} rows")
    print(f"Train: before {test_start_str}  ({split_idx:,} rows)")
    print(f"Test:  {test_start_str} → {df['tourney_date'].max().date()}  ({len(df) - split_idx:,} rows)\n")

    os.makedirs(MODEL_DIR, exist_ok=True)
    metrics_path = os.path.join(MODEL_DIR, 'model_metrics.csv')
    all_metrics  = []

    for target in TARGETS:
        if target not in df.columns:
            print(f"⚠️  Target '{target}' not found — skipping.")
            continue

        tier = TARGET_TIER.get(target, 'MEDIUM')
        print(f"--- {target.upper()}  [{tier}] ---")

        df_model = df[df[target].notna()].copy()
        df_model = df_model.sort_values('tourney_date').reset_index(drop=True)

        available_features = [f for f in FEATURES if f in df_model.columns]
        missing = len(FEATURES) - len(available_features)
        if missing > 0:
            print(f"   ℹ️  {missing} features absent — using {len(available_features)}")

        X = df_model[available_features].fillna(0)
        y = df_model[target]

        t_split    = int(len(df_model) * (1 - TEST_FRACTION))
        train_mask = df_model.index < t_split
        test_mask  = df_model.index >= t_split

        X_train, y_train = X[train_mask], y[train_mask]
        X_test,  y_test  = X[test_mask],  y[test_mask]

        if len(X_train) < 100 or len(X_test) == 0:
            print(f"   ⚠️  Insufficient data. Skipping.")
            continue

        print(f"   Train: {len(X_train):,}  |  Test: {len(X_test):,}")

        # ── XGBoost ──────────────────────────────────────────────────────
        xgb_model = xgb.XGBRegressor(**XGB_PARAMS[tier])
        xgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        xgb_preds = xgb_model.predict(X_test)

        # ── LightGBM ─────────────────────────────────────────────────────
        lgbm_model = lgb.LGBMRegressor(**LGBM_PARAMS[tier])
        lgbm_model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(period=-1)],
        )
        lgbm_preds = lgbm_model.predict(X_test)

        # ── Ensemble blend ───────────────────────────────────────────────
        preds = ENSEMBLE_WEIGHT_XGB * xgb_preds + ENSEMBLE_WEIGHT_LGBM * lgbm_preds

        mae = mean_absolute_error(y_test, preds)
        r2  = r2_score(y_test, preds)

        target_mean = float(y_train.mean())
        dir_correct = (
            np.sum((preds > target_mean) == (y_test.values > target_mean))
            / len(y_test) * 100
        )

        print(f"   MAE: {mae:.3f} | R²: {r2:.3f} | Dir Acc: {dir_correct:.1f}%")

        # Save both models
        xgb_path  = os.path.join(MODEL_DIR, f'{target}_model.json')
        lgbm_path = os.path.join(MODEL_DIR, f'{target}_model_lgbm.txt')
        xgb_model.save_model(xgb_path)
        lgbm_model.booster_.save_model(lgbm_path)
        print(f"   ✅  XGB  → {xgb_path}")
        print(f"   ✅  LGBM → {lgbm_path}")

        all_metrics.append({
            'target':       target,
            'tier':         tier,
            'train_rows':   len(X_train),
            'test_rows':    len(X_test),
            'features':     len(available_features),
            'mae':          round(mae, 4),
            'r2':           round(r2, 4),
            'dir_accuracy': round(dir_correct, 2),
            'trained_at':   datetime.now().strftime('%Y-%m-%d %H:%M'),
        })

    if all_metrics:
        with open(metrics_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=all_metrics[0].keys())
            writer.writeheader()
            writer.writerows(all_metrics)
        print(f"\n📊 Metrics → {metrics_path}")

    print("\n" + "=" * 60)
    print(f"{'TARGET':<22} {'TIER':>7} {'MAE':>7} {'R²':>7} {'DIR%':>7}")
    print("-" * 55)
    for m in all_metrics:
        print(f"{m['target']:<22} {m['tier']:>7} {m['mae']:>7.3f} {m['r2']:>7.3f} {m['dir_accuracy']:>6.1f}%")
    print("=" * 60)
    print("✅  TRAINING COMPLETE  (60% XGB + 40% LGBM ensemble)")


if __name__ == "__main__":
    train_and_evaluate()
