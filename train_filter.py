#!/usr/bin/env python3
"""Train a hit-probability filter per OddsType. Honest time-split eval:
train on early days, test on later days, measure if top-ranked picks
actually hit more than bottom-ranked picks on unseen data."""
import pandas as pd, numpy as np, xgboost as xgb, os

FEATS = ['Edge_Pct','OPS_vs','AVG_vs','K_Pct_vs','L5','L10','Streak',
         'Con_Over','PF_Mult','HR_L10','Game_Total','Implied','Temp_F']

def coerce(df):
    for c in FEATS:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

def run(df, label):
    df = coerce(df.copy())
    days = sorted(df['scan_date'].unique())
    if len(days) < 6:
        print(f"\n[{label}] not enough days"); return
    split = days[int(len(days)*0.7)]
    tr = df[df['scan_date'] < split]
    te = df[df['scan_date'] >= split]
    if len(te) < 50 or tr['hit'].nunique() < 2:
        print(f"\n[{label}] insufficient test data"); return

    Xtr, ytr = tr[FEATS], tr['hit']
    Xte, yte = te[FEATS], te['hit']

    m = xgb.XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, eval_metric='logloss',
        min_child_weight=5, reg_lambda=1.0)
    m.fit(Xtr, ytr)
    te = te.copy(); te['p'] = m.predict_proba(Xte)[:,1]

    base = yte.mean()
    print(f"\n========== {label} ==========")
    print(f"train {len(tr)} (days <{split}) | test {len(te)} (days >={split})")
    print(f"test base hit rate: {base:.3f}")

    # The real test: sort by predicted prob, do top picks hit more than bottom?
    te = te.sort_values('p', ascending=False)
    n = len(te)
    for name, sl in [("TOP 10%", te.head(max(1,n//10))),
                     ("TOP 25%", te.head(max(1,n//4))),
                     ("BOTTOM 25%", te.tail(max(1,n//4))),
                     ("BOTTOM 10%", te.tail(max(1,n//10)))]:
        print(f"  {name:<11} hit {sl['hit'].mean():.3f}  (n={len(sl)})")

    # feature importance
    imp = sorted(zip(FEATS, m.feature_importances_), key=lambda x:-x[1])[:6]
    print("  top features:", ", ".join(f"{f}({w:.2f})" for f,w in imp))

df = pd.read_csv('output/mlb/graded/training_data.csv')
df = df[df['result'] != 'Push']
for t in ['goblin','demon','standard']:
    sub = df[df['odds_type']==t]
    if len(sub) >= 200:
        run(sub, t.upper())
