#!/usr/bin/env python3
"""Goblin hit-probability model. Compares baseline vs +extra-features,
honest time-split, isotonic-calibrated. Keeps what improves held-out separation."""
import pandas as pd, numpy as np, xgboost as xgb
from sklearn.isotonic import IsotonicRegression

BASE = ['Edge_Pct','OPS_vs','AVG_vs','K_Pct_vs','L5','L10','Streak',
        'Con_Over','PF_Mult','HR_L10','Game_Total','Implied','Temp_F']
EXTRA = ['DEF_ERA','DEF_WHIP','DEF_K9','Wind_Speed','Is_Indoor','Pitch_Hand_R']

def prep(df):
    df = df.copy()
    df['Pitch_Hand_R'] = (df.get('Pitch_Hand') == 'R').astype(float)
    df['Is_Indoor'] = df['Is_Indoor'].astype(float)
    for c in BASE + EXTRA:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

def evaluate(df, feats, label):
    days = sorted(df['scan_date'].unique())
    split = days[int(len(days)*0.7)]
    tr = df[df['scan_date'] < split]; te = df[df['scan_date'] >= split].copy()
    m = xgb.XGBClassifier(n_estimators=250, max_depth=4, learning_rate=0.04,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=6,
        reg_lambda=1.5, eval_metric='logloss')
    m.fit(tr[feats], tr['hit'])
    # calibrate on the train set's own out-of-fold-ish predictions (simple: fit iso on train)
    raw_tr = m.predict_proba(tr[feats])[:,1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(raw_tr, tr['hit'])
    te['p'] = iso.transform(m.predict_proba(te[feats])[:,1])
    te = te.sort_values('p', ascending=False)
    n = len(te); base = te['hit'].mean()
    top10 = te.head(max(1,n//10))['hit'].mean()
    top25 = te.head(max(1,n//4))['hit'].mean()
    bot25 = te.tail(max(1,n//4))['hit'].mean()
    bot10 = te.tail(max(1,n//10))['hit'].mean()
    spread = top10 - bot10
    print(f"\n[{label}]  features={len(feats)}  test base={base:.3f}")
    print(f"  TOP10 {top10:.3f} | TOP25 {top25:.3f} | BOT25 {bot25:.3f} | BOT10 {bot10:.3f}")
    print(f"  >>> top10-bot10 spread: {spread:.3f}")
    return m, iso, spread, top10

df = pd.read_csv('output/mlb/graded/training_data.csv')
df = prep(df[(df['result']!='Push') & (df['odds_type']=='goblin')])

_,_,s_base,_ = evaluate(df, BASE, "BASELINE 13 feats")
have_extra = [f for f in EXTRA if f in df.columns]
m,iso,s_full,top10 = evaluate(df, BASE+have_extra, f"+EXTRA ({len(have_extra)} added)")

print(f"\n==== VERDICT ====")
print(f"baseline spread {s_base:.3f}  vs  +extra spread {s_full:.3f}")
print("Extra features HELP" if s_full > s_base + 0.01 else
      "Extra features do NOT improve separation — keep baseline")

# importances of the full model
imp = sorted(zip(BASE+have_extra, m.feature_importances_), key=lambda x:-x[1])[:10]
print("\nTop features (full model):")
for f,w in imp: print(f"  {f:<14} {w:.3f}")
