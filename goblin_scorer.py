"""Live goblin scoring — loads saved model, returns calibrated hit prob + grade."""
import os, json, pickle
import numpy as np, pandas as pd, xgboost as xgb

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "mlb")
_model = None; _iso = None; _feats = None

def _load():
    global _model, _iso, _feats
    if _model is not None: return
    _feats = json.load(open(os.path.join(_DIR, "goblin", "features.json")))
    _model = xgb.XGBClassifier()
    _model.load_model(os.path.join(_DIR, "goblin", "model.json"))
    _iso = pickle.load(open(os.path.join(_DIR, "goblin", "calibrator.pkl"), "rb"))

def score_goblins(df):
    """Given a scan DataFrame, return dict {row_index: (prob, grade)} for goblin rows."""
    try:
        _load()
    except Exception as e:
        print(f"[goblin_scorer] model load failed: {e}")
        return {}
    gob = df[df.get("Is_Goblin") == True].copy()
    if gob.empty: return {}
    gob["Pitch_Hand_R"] = (gob.get("Pitch_Hand") == "R").astype(float)
    if "Is_Indoor" in gob.columns:
        gob["Is_Indoor"] = pd.to_numeric(gob["Is_Indoor"], errors="coerce").fillna(0).astype(float)
    for c in _feats:
        if c not in gob.columns: gob[c] = np.nan
        gob[c] = pd.to_numeric(gob[c], errors="coerce")
    raw = _model.predict_proba(gob[_feats])[:, 1]
    prob = _iso.transform(raw)
    out = {}
    lines = pd.to_numeric(gob["PP_Line"], errors="coerce")
    projs = pd.to_numeric(gob["AI_Proj"], errors="coerce") if "AI_Proj" in gob.columns else pd.Series(dtype=float)
    for idx, pr in zip(gob.index, prob):
        ln = lines.get(idx, 0)
        trivial = (ln is not None and ln <= 0.5)  # floor bets: high prob, no value
        if trivial:
            grade = "FLOOR"            # near-automatic, not a headline pick
        elif pr >= 0.70:   grade = "LOCK"
        elif pr >= 0.62:   grade = "STRONG"
        elif pr >= 0.55:   grade = "LEAN"
        else:              grade = "SKIP"
        # Goblins are Over-only markets, but Edge_Pct (this model's edge
        # feature, computed unsigned in scanner.py) can't tell "proj far
        # above the line" from "proj far below it", so a confident
        # LOCK/STRONG/LEAN can surface on a proj-below-line pick (health
        # check CHECK 1: Jack Perkins OUTS 14.5, Michael Wacha ER 2.5).
        # Suppress to SKIP rather than inventing an unvalidated flip --
        # there's no Under side to flip a goblin pick to.
        proj = projs.get(idx)
        if grade in ("LOCK", "STRONG", "LEAN") and pd.notna(proj) and pd.notna(ln) and proj < ln:
            grade = "SKIP"
        out[idx] = (round(float(pr), 3), grade)
    return out

if __name__ == "__main__":
    # quick self-test on the latest scan
    import glob
    f = sorted(glob.glob("output/mlb/scans/scan_2026-*.csv"))[-1]
    df = pd.read_csv(f)
    s = score_goblins(df)
    print(f"scored {len(s)} goblins from {f}")
    from collections import Counter
    print("grade dist:", Counter(g for _, g in s.values()))
    # show a few LOCKs
    locks = [(df.loc[i,'Player'], df.loc[i,'Stat_Label'], df.loc[i,'PP_Line'], df.loc[i,'Side'], p)
             for i,(p,g) in s.items() if g=="LOCK"][:8]
    print("\nSample LOCKs:")
    for pl,st,ln,sd,p in locks: print(f"  {p:.0%}  {pl:<22} {st} {sd} {ln}")
