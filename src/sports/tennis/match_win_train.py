"""
Tennis Match Win Classifier
Trains an XGBoost binary classifier to predict match winner (won_match).
Uses the same feature set as the props models + mirror trick for symmetry.

Output: models/tennis/match_win_model.json
Usage:  python3 -m src.sports.tennis.match_win_train
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import os
from datetime import datetime
from sklearn.metrics import accuracy_score, roc_auc_score, log_loss
from sklearn.calibration import CalibratedClassifierCV

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_FILE = os.path.join(BASE_DIR, 'data',   'tennis', 'processed', 'training_dataset.csv')
MODEL_DIR = os.path.join(BASE_DIR, 'models', 'tennis')
MODEL_OUT = os.path.join(MODEL_DIR, 'match_win_model.json')

TEST_FRACTION = 0.10

# Features used — these are the same rolling/static features as the props models
# but now target is binary: won_match (1=player won, 0=player lost)
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

# Rolling stats for player
for stat in ['total_games', 'games_won', 'total_sets', 'aces', 'bp_won',
             'total_tiebreaks', 'double_faults', 'won_match', 'sets_won',
             'bp_faced', 'svpt', 'svc_games']:
    for w in ['L5', 'L20', 'Season']:
        FEATURES.append(f'{stat}_{w}')

# Surface-specific rolling
for stat in ['aces', 'double_faults', 'total_games', 'games_won', 'bp_won']:
    for surf in ['hard', 'clay', 'grass']:
        FEATURES.append(f'{stat}_{surf}_L10')

# Opponent rolling
for stat in ['total_games', 'games_won', 'aces', 'double_faults', 'bp_won', 'bp_faced']:
    for w in ['L5', 'L20']:
        FEATURES.append(f'opp_{stat}_{w}')

for stat in ['aces', 'double_faults', 'total_games', 'games_won', 'bp_won']:
    for surf in ['hard', 'clay', 'grass']:
        FEATURES.append(f'opp_{stat}_{surf}_L10')


def train():
    print("=" * 55)
    print("   🎾 TENNIS MATCH WIN CLASSIFIER")
    print("=" * 55)

    if not os.path.exists(DATA_FILE):
        print(f"ERROR: {DATA_FILE} not found. Run features.py first.")
        return

    print("Loading data…")
    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['tourney_date'] = pd.to_datetime(df['tourney_date'], errors='coerce')
    df = df.dropna(subset=['tourney_date', 'won_match'])
    df = df.sort_values('tourney_date').reset_index(drop=True)
    df['won_match'] = df['won_match'].astype(int)

    # ── Mirror trick ──────────────────────────────────────────────────────────
    # Each match is represented twice in the data (once per player).
    # The model already sees both perspectives, but we can also synthetically
    # flip player/opp feature columns to double training diversity and force
    # the model to learn relative rather than absolute patterns.
    print(f"Loaded {len(df):,} rows")

    available = [f for f in FEATURES if f in df.columns]
    print(f"Using {len(available)} features")

    X = df[available].fillna(0).values
    y = df['won_match'].values

    split = int(len(df) * (1 - TEST_FRACTION))
    X_train, y_train = X[:split], y[:split]
    X_test,  y_test  = X[split:], y[split:]

    print(f"Train: {len(X_train):,}  |  Test: {len(X_test):,}\n")

    model = xgb.XGBClassifier(
        n_estimators=500,
        learning_rate=0.04,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.75,
        min_child_weight=10,
        reg_alpha=0.2,
        reg_lambda=1.5,
        scale_pos_weight=1.0,   # balanced classes
        use_label_encoder=False,
        eval_metric='logloss',
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )

    print("Training XGBoost classifier…")
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=50,
    )

    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)

    acc  = accuracy_score(y_test, preds) * 100
    auc  = roc_auc_score(y_test, probs) * 100
    ll   = log_loss(y_test, probs)

    print(f"\n{'─'*45}")
    print(f"  Accuracy : {acc:.1f}%")
    print(f"  ROC-AUC  : {auc:.1f}%")
    print(f"  Log-loss : {ll:.4f}")
    print(f"{'─'*45}")

    os.makedirs(MODEL_DIR, exist_ok=True)
    model.save_model(MODEL_OUT)
    print(f"\n✅  Model saved → {MODEL_OUT}")

    # Save feature list alongside model
    feat_path = os.path.join(MODEL_DIR, 'match_win_features.txt')
    with open(feat_path, 'w') as f:
        f.write('\n'.join(available))
    print(f"✅  Features saved → {feat_path}")
    print("=" * 55)


if __name__ == '__main__':
    train()
