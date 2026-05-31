"""
MLB XGBoost + LightGBM Ensemble Training Pipeline

Trains separate regression models for:
  Batters:  H, TB, HR, RBI, R, SO, BB
  Pitchers: K, ER, OUTS

Improvements over v1:
  - XGBoost (60%) + LightGBM (40%) blended ensemble
  - Tiered hyperparameters per stat volatility
  - Log-transform for HR, BB, SB (zero-inflated)
  - Per-player median directional accuracy (realistic proxy for sportsbook lines)
  - Saves both model files for scanner ensemble loading

Output:
    models/mlb/{STAT}_model.json       (XGBoost)
    models/mlb/{STAT}_model_lgbm.txt   (LightGBM)
    models/mlb/model_metrics.csv

Usage:
    $ python3 -m src.sports.mlb.train
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import lightgbm as lgb
import os
import csv
from datetime import datetime
from sklearn.metrics import mean_absolute_error, r2_score

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BATTER_FILE   = os.path.join(BASE_DIR, 'data',   'mlb', 'processed', 'batter_training.csv')
PITCHER_FILE  = os.path.join(BASE_DIR, 'data',   'mlb', 'processed', 'pitcher_training.csv')
MODEL_DIR     = os.path.join(BASE_DIR, 'models', 'mlb')

BATTER_TARGETS  = ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB']
PITCHER_TARGETS = ['K', 'ER', 'OUTS']

# Stats that are zero-inflated / right-skewed — train on log1p(y)
LOG_TRANSFORM_TARGETS = {'HR', 'BB', 'SB', 'ER'}

TEST_FRACTION = 0.10

# ── Feature sets ────────────────────────────────────────────────────────────
BATTER_ROLL_STATS  = ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB', 'AB', 'SB', '2B', '3B']
PITCHER_ROLL_STATS = ['K', 'ER', 'OUTS', 'HA', 'BBA', 'HR_A', 'pitches', 'batters_faced']

BATTER_WINDOWS  = [5, 10, 20]
PITCHER_WINDOWS = [3, 5, 10]


def _build_feature_list(roll_stats, windows, extra=None):
    feats = []
    for stat in roll_stats:
        for w in windows:
            feats.append(f'{stat}_L{w}')
        feats.append(f'{stat}_season_avg')
    feats.append('is_home')
    if extra:
        feats.extend(extra)
    return feats


BATTER_FEATURES  = _build_feature_list(
    BATTER_ROLL_STATS, BATTER_WINDOWS,
    ['games_played', 'PA_L5', 'PA_L10', 'PA_season_avg']
)
PITCHER_FEATURES = _build_feature_list(
    PITCHER_ROLL_STATS, PITCHER_WINDOWS,
    ['is_starter', 'apps_season']
)

# ── XGBoost hyperparameter tiers ────────────────────────────────────────────
_XGB_HIGH = dict(
    n_estimators=800, learning_rate=0.04, max_depth=6,
    subsample=0.85, colsample_bytree=0.75, min_child_weight=3,
    gamma=0.05, reg_alpha=0.1, reg_lambda=1.5,
    early_stopping_rounds=50, n_jobs=-1, random_state=42, verbosity=0,
)
_XGB_MEDIUM = dict(
    n_estimators=600, learning_rate=0.03, max_depth=5,
    subsample=0.80, colsample_bytree=0.70, min_child_weight=7,
    gamma=0.10, reg_alpha=0.2, reg_lambda=1.5,
    early_stopping_rounds=40, n_jobs=-1, random_state=42, verbosity=0,
)
_XGB_LOW = dict(
    n_estimators=400, learning_rate=0.02, max_depth=4,
    subsample=0.70, colsample_bytree=0.60, min_child_weight=15,
    gamma=0.30, reg_alpha=0.5, reg_lambda=2.0,
    early_stopping_rounds=30, n_jobs=-1, random_state=42, verbosity=0,
)

# ── LightGBM hyperparameter tiers ───────────────────────────────────────────
_LGBM_HIGH = dict(
    n_estimators=800, learning_rate=0.04, max_depth=6, num_leaves=50,
    subsample=0.85, subsample_freq=5, colsample_bytree=0.75,
    min_child_samples=20, min_split_gain=0.05,
    reg_alpha=0.1, reg_lambda=1.5, n_jobs=-1, random_state=42, verbosity=-1,
)
_LGBM_MEDIUM = dict(
    n_estimators=600, learning_rate=0.03, max_depth=5, num_leaves=35,
    subsample=0.80, subsample_freq=5, colsample_bytree=0.70,
    min_child_samples=30, min_split_gain=0.10,
    reg_alpha=0.2, reg_lambda=1.5, n_jobs=-1, random_state=42, verbosity=-1,
)
_LGBM_LOW = dict(
    n_estimators=400, learning_rate=0.02, max_depth=4, num_leaves=25,
    subsample=0.70, subsample_freq=5, colsample_bytree=0.60,
    min_child_samples=50, min_split_gain=0.20,
    reg_alpha=0.5, reg_lambda=2.0, n_jobs=-1, random_state=42, verbosity=-1,
)

# Per-target tier assignments
_BATTER_TIER = {
    'H':   ('HIGH',   _XGB_HIGH,   _LGBM_HIGH),
    'TB':  ('HIGH',   _XGB_HIGH,   _LGBM_HIGH),
    'SO':  ('HIGH',   _XGB_HIGH,   _LGBM_HIGH),
    'RBI': ('MEDIUM', _XGB_MEDIUM, _LGBM_MEDIUM),
    'R':   ('MEDIUM', _XGB_MEDIUM, _LGBM_MEDIUM),
    'HR':  ('LOW',    _XGB_LOW,    _LGBM_LOW),
    'BB':  ('LOW',    _XGB_LOW,    _LGBM_LOW),
}
_PITCHER_TIER = {
    'K':    ('HIGH',   _XGB_HIGH,   _LGBM_HIGH),
    'OUTS': ('HIGH',   _XGB_HIGH,   _LGBM_HIGH),
    'ER':   ('MEDIUM', _XGB_MEDIUM, _LGBM_MEDIUM),
}

ENSEMBLE_WEIGHT_XGB  = 0.60
ENSEMBLE_WEIGHT_LGBM = 0.40


def _train_group(df, targets, feature_list, group_name, tier_map, all_metrics):
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    split_idx  = int(len(df) * (1 - TEST_FRACTION))
    split_date = df.iloc[split_idx]['date']
    print(f"\n   {group_name} — {len(df):,} rows | test from {split_date.date()}")

    for target in targets:
        if target not in df.columns:
            print(f"   ⚠  '{target}' not in dataset — skipping")
            continue

        sub = df[df[target].notna()].copy().sort_values('date').reset_index(drop=True)
        available = [f for f in feature_list if f in sub.columns]
        X = sub[available].fillna(0)
        y = sub[target].astype(float)

        log_target = target in LOG_TRANSFORM_TARGETS
        y_fit = np.log1p(y) if log_target else y

        t_split = int(len(sub) * (1 - TEST_FRACTION))
        X_train, y_train_fit = X.iloc[:t_split], y_fit.iloc[:t_split]
        X_test,  y_test      = X.iloc[t_split:],  y.iloc[t_split:]

        if len(X_train) < 100 or len(X_test) == 0:
            print(f"   ⚠  {target}: not enough data — skipping")
            continue

        tier_name, xgb_params, lgbm_params = tier_map.get(target, ('MEDIUM', _XGB_MEDIUM, _LGBM_MEDIUM))
        print(f"\n   [{tier_name}] Training {target}  "
              f"(feats:{len(available)} train:{len(X_train):,} test:{len(X_test):,}"
              f"{' log' if log_target else ''})")

        # ── XGBoost ─────────────────────────────────────────────────────────
        xgb_model = xgb.XGBRegressor(**xgb_params)
        xgb_model.fit(X_train, y_train_fit,
                      eval_set=[(X_test, np.log1p(y_test) if log_target else y_test)],
                      verbose=False)
        xgb_raw = xgb_model.predict(X_test)
        if log_target:
            xgb_raw = np.expm1(xgb_raw)

        # ── LightGBM ─────────────────────────────────────────────────────────
        lgbm_model = lgb.LGBMRegressor(**lgbm_params)
        lgbm_model.fit(X_train, y_train_fit)
        lgbm_raw = lgbm_model.predict(X_test)
        if log_target:
            lgbm_raw = np.expm1(lgbm_raw)

        # ── Ensemble ──────────────────────────────────────────────────────────
        preds = ENSEMBLE_WEIGHT_XGB * xgb_raw + ENSEMBLE_WEIGHT_LGBM * lgbm_raw
        preds = np.clip(preds, 0, None)

        mae = mean_absolute_error(y_test, preds)
        r2  = r2_score(y_test, preds)

        # Directional accuracy vs per-player L20 median (realistic line proxy)
        if 'player_name' in sub.columns or 'player_id' in sub.columns:
            pid_col = 'player_id' if 'player_id' in sub.columns else 'player_name'
            test_sub = sub.iloc[t_split:].copy()
            test_sub['_pred'] = preds
            medians = sub.iloc[:t_split].groupby(pid_col)[target].median()
            test_sub['_median'] = test_sub[pid_col].map(medians).fillna(y_train_fit.mean())
            dir_acc = np.mean((test_sub['_pred'] > test_sub['_median']) ==
                              (test_sub[target]  > test_sub['_median'])) * 100
        else:
            m = float(y_train_fit.mean())
            dir_acc = np.mean((preds > m) == (y_test.values > m)) * 100

        print(f"      MAE:{mae:.3f}  R²:{r2:.4f}  DirAcc:{dir_acc:.1f}%")

        # ── Save models ───────────────────────────────────────────────────────
        xgb_path  = os.path.join(MODEL_DIR, f'{target}_model.json')
        lgbm_path = os.path.join(MODEL_DIR, f'{target}_model_lgbm.txt')
        xgb_model.save_model(xgb_path)
        lgbm_model.booster_.save_model(lgbm_path)
        print(f"      ✅ XGB  → {xgb_path}")
        print(f"      ✅ LGBM → {lgbm_path}")

        all_metrics.append({
            'target':       target,
            'group':        group_name,
            'tier':         tier_name,
            'train_rows':   len(X_train),
            'test_rows':    len(X_test),
            'features':     len(available),
            'mae':          round(mae, 4),
            'r2':           round(r2, 4),
            'dir_accuracy': round(dir_acc, 2),
            'log_transform': log_target,
            'trained_at':   datetime.now().strftime('%Y-%m-%d %H:%M'),
        })


def train_and_evaluate():
    print("=" * 62)
    print("   ⚾  MLB XGBoost + LightGBM Ensemble Training")
    print("=" * 62)

    os.makedirs(MODEL_DIR, exist_ok=True)
    all_metrics = []

    if not os.path.exists(BATTER_FILE):
        print(f"❌ Batter data not found: {BATTER_FILE}")
    else:
        df_bat = pd.read_csv(BATTER_FILE, low_memory=False)
        _train_group(df_bat, BATTER_TARGETS, BATTER_FEATURES, 'Batters',  _BATTER_TIER,  all_metrics)

    if not os.path.exists(PITCHER_FILE):
        print(f"❌ Pitcher data not found: {PITCHER_FILE}")
    else:
        df_pit = pd.read_csv(PITCHER_FILE, low_memory=False)
        _train_group(df_pit, PITCHER_TARGETS, PITCHER_FEATURES, 'Pitchers', _PITCHER_TIER, all_metrics)

    if not all_metrics:
        print("No models trained.")
        return

    metrics_path = os.path.join(MODEL_DIR, 'model_metrics.csv')
    with open(metrics_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_metrics[0].keys())
        writer.writeheader()
        writer.writerows(all_metrics)

    print(f"\n📊 Metrics → {metrics_path}")
    print("\n" + "=" * 62)
    print(f"{'TARGET':<7} {'GROUP':<9} {'TIER':<7} {'MAE':>6} {'R²':>7} {'DIR%':>7}")
    print("-" * 50)
    for m in all_metrics:
        print(f"{m['target']:<7} {m['group']:<9} {m['tier']:<7} "
              f"{m['mae']:>6.3f} {m['r2']:>7.4f} {m['dir_accuracy']:>6.1f}%")
    print("=" * 62)
    print("✅  TRAINING COMPLETE")


if __name__ == "__main__":
    train_and_evaluate()
