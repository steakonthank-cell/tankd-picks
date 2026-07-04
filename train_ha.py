#!/usr/bin/env python3
"""Train a Hits Allowed (HA) projection model for the MLB scanner.
Mirrors K/ER/OUTS: XGBRegressor on PITCHER_FEATURES, target=HA.
Honest time-split validation vs a naive L10-average baseline."""
import os, sys
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.sports.mlb.train import PITCHER_FEATURES

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
TRAIN_CSV = os.path.join(BASE_DIR, "data", "mlb", "processed", "pitcher_training.csv")
OUT_MODEL = os.path.join(BASE_DIR, "models", "mlb", "HA_model.json")
TARGET    = "HA"
PARAMS = dict(n_estimators=400, max_depth=4, learning_rate=0.03, subsample=0.8,
              colsample_bytree=0.8, min_child_weight=5, reg_lambda=1.0,
              objective="reg:squarederror", n_jobs=2)

print("=== HA (Hits Allowed) model trainer ===")
df = pd.read_csv(TRAIN_CSV, low_memory=False)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df = df.dropna(subset=["date", TARGET]).sort_values("date").reset_index(drop=True)
print("loaded", len(df), "pitcher-games,", df["date"].min().date(), "->", df["date"].max().date())

missing = [f for f in PITCHER_FEATURES if f not in df.columns]
if missing:
    print("FATAL: missing feature columns:", missing); sys.exit(1)

df = df.dropna(subset=PITCHER_FEATURES).reset_index(drop=True)
print(len(df), "rows after dropping incomplete-feature rows")

cut = int(len(df) * 0.80)
cut_date = df.iloc[cut]["date"]
train = df[df["date"] < cut_date]
test  = df[df["date"] >= cut_date]
print("train:", len(train), "  test:", len(test), " split at", cut_date.date())

model = xgb.XGBRegressor(**PARAMS)
model.fit(train[PITCHER_FEATURES], train[TARGET])
pred = model.predict(test[PITCHER_FEATURES])
model_mae = mean_absolute_error(test[TARGET], pred)
base_mae  = mean_absolute_error(test[TARGET], test["HA_L10"])

print()
print("held-out MAE (model):      ", round(model_mae, 3), "hits")
print("held-out MAE (L10 avg):    ", round(base_mae, 3), "hits")
print("improvement over baseline: ", round((base_mae - model_mae) / base_mae * 100, 1), "%")
print("test mean HA:", round(test[TARGET].mean(), 2), " std:", round(test[TARGET].std(), 2))

imp = sorted(zip(PITCHER_FEATURES, model.feature_importances_), key=lambda x: x[1], reverse=True)[:10]
print("\ntop features:")
for f, v in imp:
    print("  ", f.ljust(24), round(float(v), 3))

print("\nretraining on full dataset for production...")
full = xgb.XGBRegressor(**PARAMS)
full.fit(df[PITCHER_FEATURES], df[TARGET])
full.save_model(OUT_MODEL)
print("saved ->", OUT_MODEL)
