#!/usr/bin/env python3
"""Train final goblin model on ALL graded data and save it for live scoring."""
import pandas as pd, numpy as np, xgboost as xgb, json, pickle
from sklearn.isotonic import IsotonicRegression

FEATS = ['Edge_Pct','OPS_vs','AVG_vs','K_Pct_vs','L5','L10','Streak',
         'Con_Over','PF_Mult','HR_L10','Game_Total','Implied','Temp_F',
         'DEF_ERA','DEF_WHIP','DEF_K9','Wind_Speed','Is_Indoor','Pitch_Hand_R']

def prep(df):
    df = df.copy()
    df['Pitch_Hand_R'] = (df.get('Pitch_Hand') == 'R').astype(float)
    df['Is_Indoor'] = pd.to_numeric(df['Is_Indoor'], errors='coerce').fillna(0).astype(float)
    for c in FEATS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

df = pd.read_csv('output/mlb/graded/training_data.csv')
df = prep(df[(df['result']!='Push') & (df['odds_type']=='goblin')])

# Final model trained on everything (for live use going forward)
m = xgb.XGBClassifier(n_estimators=250, max_depth=4, learning_rate=0.04,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=6,
    reg_lambda=1.5, eval_metric='logloss')
m.fit(df[FEATS], df['hit'])
raw = m.predict_proba(df[FEATS])[:,1]
iso = IsotonicRegression(out_of_bounds='clip').fit(raw, df['hit'])

m.save_model('models/mlb/goblin_model.json')
with open('models/mlb/goblin_calibrator.pkl','wb') as f:
    pickle.dump(iso, f)
with open('models/mlb/goblin_features.json','w') as f:
    json.dump(FEATS, f)

print("SAVED:")
print("  models/mlb/goblin_model.json")
print("  models/mlb/goblin_calibrator.pkl")
print("  models/mlb/goblin_features.json")
print(f"trained on {len(df)} graded goblins across {df['scan_date'].nunique()} days")
