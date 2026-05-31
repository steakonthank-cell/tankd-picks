"""
WNBA XGBoost + LightGBM Ensemble Training

Trains one ensemble model per target stat using time-series split validation.
Same architecture as NBA train.py, upgraded with:
  - XGBoost (60%) + LightGBM (40%) blend
  - Matched LightGBM hyperparameter tiers
  - Both model files saved for scanner ensemble loading

Output:
    models/wnba/{TARGET}_model.json        (XGBoost)
    models/wnba/{TARGET}_model_lgbm.txt    (LightGBM)
    models/wnba/model_metrics.csv

Usage:
    $ python3 -m src.sports.wnba.train
"""

import os
import csv
import pandas as pd
import numpy as np
import xgboost as xgb
import lightgbm as lgb
from datetime import datetime
from sklearn.metrics import mean_absolute_error, r2_score

from src.sports.wnba.config import ACTIVE_TARGETS, LOG_TRANSFORM_TARGETS, MODEL_QUALITY

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_FILE  = os.path.join(BASE_DIR, 'data',   'wnba', 'processed', 'training_dataset.csv')
MODEL_DIR  = os.path.join(BASE_DIR, 'models', 'wnba')
METRICS_FILE = os.path.join(MODEL_DIR, 'model_metrics.csv')

os.makedirs(MODEL_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Hyperparameter tiers — XGBoost
# ---------------------------------------------------------------------------

_HIGH = {
    'n_estimators': 800, 'learning_rate': 0.04, 'max_depth': 5,
    'subsample': 0.80, 'colsample_bytree': 0.75, 'min_child_weight': 5,
    'gamma': 0.05, 'reg_alpha': 0.1, 'reg_lambda': 1.5,
    'early_stopping_rounds': 40, 'n_jobs': -1,
}
_MEDIUM = {
    'n_estimators': 600, 'learning_rate': 0.03, 'max_depth': 4,
    'subsample': 0.75, 'colsample_bytree': 0.70, 'min_child_weight': 10,
    'gamma': 0.10, 'reg_alpha': 0.2, 'reg_lambda': 2.0,
    'early_stopping_rounds': 35, 'n_jobs': -1,
}
_LOW = {
    'n_estimators': 400, 'learning_rate': 0.02, 'max_depth': 3,
    'subsample': 0.70, 'colsample_bytree': 0.60, 'min_child_weight': 20,
    'gamma': 0.30, 'reg_alpha': 0.5, 'reg_lambda': 2.5,
    'early_stopping_rounds': 25, 'n_jobs': -1,
}

TARGET_HYPERPARAMS = {
    'PTS': _HIGH, 'REB': _HIGH, 'AST': _HIGH,
    'PRA': _HIGH, 'PR':  _HIGH, 'PA':  _HIGH, 'RA': _HIGH, 'FPTS': _HIGH,
    'FG3M': _MEDIUM, 'FTM': _MEDIUM, 'FGM': _MEDIUM, 'SB': _MEDIUM,
    'STL':  _LOW,    'TOV': _LOW,    'DREB': _LOW,    'OREB': _LOW,
}

# ---------------------------------------------------------------------------
# Hyperparameter tiers — LightGBM (mirrors XGB tiers)
# ---------------------------------------------------------------------------

_LGBM_HIGH = dict(
    n_estimators=800, learning_rate=0.04, max_depth=5, num_leaves=40,
    subsample=0.80, subsample_freq=5, colsample_bytree=0.75,
    min_child_samples=15, min_split_gain=0.05,
    reg_alpha=0.1, reg_lambda=1.5, n_jobs=-1, random_state=42, verbosity=-1,
)
_LGBM_MEDIUM = dict(
    n_estimators=600, learning_rate=0.03, max_depth=4, num_leaves=28,
    subsample=0.75, subsample_freq=5, colsample_bytree=0.70,
    min_child_samples=25, min_split_gain=0.10,
    reg_alpha=0.2, reg_lambda=2.0, n_jobs=-1, random_state=42, verbosity=-1,
)
_LGBM_LOW = dict(
    n_estimators=400, learning_rate=0.02, max_depth=3, num_leaves=18,
    subsample=0.70, subsample_freq=5, colsample_bytree=0.60,
    min_child_samples=40, min_split_gain=0.20,
    reg_alpha=0.5, reg_lambda=2.5, n_jobs=-1, random_state=42, verbosity=-1,
)

LGBM_HYPERPARAMS = {
    'PTS': _LGBM_HIGH, 'REB': _LGBM_HIGH, 'AST': _LGBM_HIGH,
    'PRA': _LGBM_HIGH, 'PR':  _LGBM_HIGH, 'PA':  _LGBM_HIGH,
    'RA':  _LGBM_HIGH, 'FPTS': _LGBM_HIGH,
    'FG3M': _LGBM_MEDIUM, 'FTM': _LGBM_MEDIUM, 'FGM': _LGBM_MEDIUM, 'SB': _LGBM_MEDIUM,
    'STL':  _LGBM_LOW, 'TOV': _LGBM_LOW, 'DREB': _LGBM_LOW, 'OREB': _LGBM_LOW,
}

ENSEMBLE_WEIGHT_XGB  = 0.60
ENSEMBLE_WEIGHT_LGBM = 0.40

# ---------------------------------------------------------------------------
# Feature selection
# ---------------------------------------------------------------------------

_EXCLUDE = {
    'PLAYER_ID', 'PLAYER_NAME', 'TEAM_ID', 'TEAM_ABBREVIATION', 'TEAM_NAME',
    'GAME_ID', 'GAME_DATE', 'MATCHUP', 'WL', 'SEASON_ID', 'SEASON_YEAR',
    'NICKNAME', 'POSITION',
    # raw targets (would be leakage)
    *ACTIVE_TARGETS,
    # raw counting stats
    'PTS', 'REB', 'AST', 'FG3M', 'FG3A', 'FGM', 'FGA', 'FTM', 'FTA',
    'STL', 'BLK', 'TOV', 'OREB', 'DREB', 'MIN', 'PF', 'PLUS_MINUS',
    'WNBA_FANTASY_PTS', 'NBA_FANTASY_PTS',
}

# Rank columns (from API) are noise, not signal
_RANK_SUFFIX = '_RANK'


def get_features(df, target):
    """Select usable, non-leaking feature columns for a given target."""
    drop = set(_EXCLUDE)
    # Exclude the target itself and closely related raw stats
    drop.add(target)

    # Allow derived stats that don't include the target in their computation
    allowed_combos = {
        'PTS': ['PRA', 'PR', 'PA', 'FPTS'],
        'REB': ['PRA', 'PR', 'RA', 'DREB', 'OREB'],
        'AST': ['PRA', 'PA', 'RA'],
        'STL': ['SB'],
        'BLK': ['SB'],
    }
    # Remove combo stats that contain the target
    for _raw, _combos in allowed_combos.items():
        if target == _raw:
            for _c in _combos:
                drop.add(_c)

    feature_cols = [
        c for c in df.columns
        if c not in drop
        and not c.endswith(_RANK_SUFFIX)
        and not any(c.startswith(p) for p in ['GP_', 'W_', 'L_', 'W_PCT_', 'AVAILABLE_'])
        and df[c].dtype in [np.float64, np.float32, np.int64, np.int32, float, int]
    ]
    return feature_cols


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_and_evaluate():
    print(f"\n{'='*55}")
    print("   WNBA MODEL TRAINING")
    print(f"{'='*55}\n")

    if not os.path.exists(DATA_FILE):
        print(f"❌  {DATA_FILE} not found. Run features.py first.")
        return

    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'], errors='coerce')
    df = df.sort_values('GAME_DATE').reset_index(drop=True)
    print(f"   Loaded {len(df):,} rows  |  {df['PLAYER_ID'].nunique():,} players")

    # Time-series split: last 20% of games as validation
    split_idx = int(len(df) * 0.80)
    df_train  = df.iloc[:split_idx]
    df_val    = df.iloc[split_idx:]
    print(f"   Train: {len(df_train):,}  |  Val: {len(df_val):,}")

    metrics = []
    trained = 0

    for target in ACTIVE_TARGETS:
        if target not in df.columns:
            print(f"   ⚠️  {target} not in dataset — skipping")
            continue

        feature_cols = get_features(df, target)
        X_train = df_train[feature_cols].fillna(0)
        X_val   = df_val[feature_cols].fillna(0)

        use_log = target in LOG_TRANSFORM_TARGETS
        y_train_raw = df_train[target].fillna(0).clip(lower=0)
        y_val_raw   = df_val[target].fillna(0).clip(lower=0)
        y_train = np.log1p(y_train_raw) if use_log else y_train_raw
        y_val   = np.log1p(y_val_raw)   if use_log else y_val_raw

        # Filter train rows with valid target
        mask_train = y_train_raw >= 0
        X_train, y_train = X_train[mask_train], y_train[mask_train]

        xgb_params = TARGET_HYPERPARAMS.get(target, _MEDIUM).copy()
        early      = xgb_params.pop('early_stopping_rounds', 30)
        lgbm_params = LGBM_HYPERPARAMS.get(target, _LGBM_MEDIUM).copy()

        # ── XGBoost ──────────────────────────────────────────────────────
        xgb_model = xgb.XGBRegressor(
            **xgb_params,
            random_state=42,
            objective='reg:squarederror',
        )
        xgb_model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
            early_stopping_rounds=early,
        )
        xgb_raw = xgb_model.predict(X_val)

        # ── LightGBM ─────────────────────────────────────────────────────
        lgbm_model = lgb.LGBMRegressor(**lgbm_params)
        lgbm_model.fit(X_train, y_train)
        lgbm_raw = lgbm_model.predict(X_val)

        # ── Ensemble ─────────────────────────────────────────────────────
        ensemble_raw = ENSEMBLE_WEIGHT_XGB * xgb_raw + ENSEMBLE_WEIGHT_LGBM * lgbm_raw
        if use_log:
            preds = np.expm1(ensemble_raw).clip(min=0)
        else:
            preds = ensemble_raw.clip(min=0)

        actual = y_val_raw.values
        mae = mean_absolute_error(actual, preds)
        r2  = r2_score(actual, preds)

        # Directional accuracy vs player median (proxy for sportsbook lines)
        player_medians = df_train.groupby('PLAYER_ID')[target].median()
        val_medians    = df_val['PLAYER_ID'].map(player_medians).fillna(y_train_raw.median())
        dir_actual = (actual > val_medians.values).astype(int)
        dir_pred   = (preds  > val_medians.values).astype(int)
        dir_acc    = (dir_actual == dir_pred).mean() * 100

        tier = MODEL_QUALITY.get(target, {}).get('tier', 'UNKNOWN')
        print(f"   {target:<6} [{tier:<7}]  MAE={mae:.3f}  R²={r2:.4f}  DIR={dir_acc:.1f}%  "
              f"feats={len(feature_cols)}")

        # ── Save both models ──────────────────────────────────────────────
        xgb_path  = os.path.join(MODEL_DIR, f'{target}_model.json')
        lgbm_path = os.path.join(MODEL_DIR, f'{target}_model_lgbm.txt')
        xgb_model.save_model(xgb_path)
        lgbm_model.booster_.save_model(lgbm_path)

        metrics.append({
            'target': target, 'tier': tier, 'mae': round(mae, 4),
            'r2': round(r2, 4), 'dir_accuracy': round(dir_acc, 2),
            'train_rows': len(X_train), 'features': len(feature_cols),
            'log_transform': use_log,
            'trained_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        })
        trained += 1

    # Save metrics
    if metrics:
        with open(METRICS_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=metrics[0].keys())
            writer.writeheader()
            writer.writerows(metrics)

    print(f"\n{'='*55}")
    print(f"   ✅  Trained {trained}/{len(ACTIVE_TARGETS)} models")
    print(f"   Metrics saved → {METRICS_FILE}")
    print(f"{'='*55}\n")


if __name__ == '__main__':
    train_and_evaluate()
