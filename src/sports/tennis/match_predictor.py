"""
Tennis Match Win Predictor
Given two player names + surface, returns win probability for each.

Usage:
    from src.sports.tennis.match_predictor import predict_match
    result = predict_match("Novak Djokovic", "Carlos Alcaraz", surface="clay")
    # {'p1_name': ..., 'p1_win_pct': 44.2, 'p2_name': ..., 'p2_win_pct': 55.8}
"""

import os
import numpy as np
import pandas as pd
import xgboost as xgb

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MODEL_PATH   = os.path.join(BASE_DIR, 'models', 'tennis', 'match_win_model.json')
FEAT_PATH    = os.path.join(BASE_DIR, 'models', 'tennis', 'match_win_features.txt')
CACHE_PATH   = os.path.join(BASE_DIR, 'data',   'tennis', 'processed', 'player_cache.parquet')

_model   = None
_cache   = None
_features = None


def _load():
    global _model, _cache, _features
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Match win model not found: {MODEL_PATH}\nRun match_win_train.py first.")
        _model = xgb.XGBClassifier()
        _model.load_model(MODEL_PATH)

    if _features is None:
        with open(FEAT_PATH) as f:
            _features = [l.strip() for l in f if l.strip()]

    if _cache is None:
        df = pd.read_parquet(CACHE_PATH)
        # index is player_name (lower) → keep most-recent row per player
        _cache = df


def _fuzzy_lookup(name: str):
    """Case-insensitive partial match on player name index."""
    _load()
    nl = name.lower().strip()
    # exact match first
    if nl in _cache.index:
        return _cache.loc[nl]
    # partial
    matches = [idx for idx in _cache.index if nl in idx or idx in nl]
    if matches:
        # pick the one with most career_matches (best-known player)
        rows = _cache.loc[matches]
        return rows.sort_values('career_matches', ascending=False).iloc[0]
    return None


def get_all_players() -> list[str]:
    """Return sorted list of all player names in cache."""
    _load()
    return sorted([str(n).title() for n in _cache.index.tolist()])


def predict_match(p1: str, p2: str, surface: str = 'hard',
                  best_of: int = 3, round_ord: int = 3) -> dict:
    """
    Predict win probability for p1 vs p2 on given surface.

    Returns dict:
        p1_name, p1_win_pct, p2_name, p2_win_pct,
        confidence (str), found_p1, found_p2
    """
    _load()

    r1 = _fuzzy_lookup(p1)
    r2 = _fuzzy_lookup(p2)

    surf_map = {
        'hard': (1, 0, 0, 0),
        'clay': (0, 1, 0, 0),
        'grass': (0, 0, 1, 0),
        'carpet': (0, 0, 0, 1),
    }
    sh, sc, sg, scp = surf_map.get(surface.lower(), (1, 0, 0, 0))

    def _row_to_dict(row, opp_row):
        """Build feature dict for a player facing opp."""
        d = {}
        if row is not None:
            for col in row.index:
                d[col] = row[col]
        # Override surface
        d['surface_hard']   = sh
        d['surface_clay']   = sc
        d['surface_grass']  = sg
        d['surface_carpet'] = scp
        d['is_best_of_5']   = int(best_of == 5)
        d['round_ordinal']  = round_ord

        if row is not None and opp_row is not None:
            rp = float(row.get('player_rank', 100) or 100)
            ro = float(opp_row.get('player_rank', 100) or 100)
            d['opp_rank']    = ro
            d['rank_delta']  = rp - ro
            d['rank_ratio']  = rp / max(ro, 1)
            d['log_rank']    = np.log1p(rp)
            d['log_opp_rank']= np.log1p(ro)
            # Seed opp rolling stats from opponent's player stats
            for stat in ['total_games', 'games_won', 'aces', 'double_faults', 'bp_won', 'bp_faced']:
                for w in ['L5', 'L20']:
                    d[f'opp_{stat}_{w}'] = opp_row.get(f'{stat}_{w}', 0) or 0
            for stat in ['aces', 'double_faults', 'total_games', 'games_won', 'bp_won']:
                for surf in ['hard', 'clay', 'grass']:
                    d[f'opp_{stat}_{surf}_L10'] = opp_row.get(f'{stat}_{surf}_L10', 0) or 0
        return d

    d1 = _row_to_dict(r1, r2)
    d2 = _row_to_dict(r2, r1)

    def _to_vector(d):
        return np.array([float(d.get(f, 0) or 0) for f in _features]).reshape(1, -1)

    x1 = _to_vector(d1)
    x2 = _to_vector(d2)

    # Average both perspectives: P(p1 wins) = avg(model(p1_feats), 1 - model(p2_feats))
    prob1_fwd = float(_model.predict_proba(x1)[0, 1])
    prob2_fwd = float(_model.predict_proba(x2)[0, 1])

    # From p2's perspective prob2_fwd is prob of p2 winning
    p1_win = (prob1_fwd + (1 - prob2_fwd)) / 2
    p1_win = max(0.01, min(0.99, p1_win))
    p2_win = 1 - p1_win

    gap = abs(p1_win - p2_win)
    if gap >= 0.20:
        conf = "HIGH"
    elif gap >= 0.10:
        conf = "MEDIUM"
    else:
        conf = "LOW"

    p1_display = str(r1.name).title() if r1 is not None else p1
    p2_display = str(r2.name).title() if r2 is not None else p2

    return {
        'p1_name':    p1_display,
        'p1_win_pct': round(p1_win * 100, 1),
        'p2_name':    p2_display,
        'p2_win_pct': round(p2_win * 100, 1),
        'confidence': conf,
        'found_p1':   r1 is not None,
        'found_p2':   r2 is not None,
        'p1_rank':    int(r1.get('player_rank', 0) or 0) if r1 is not None else None,
        'p2_rank':    int(r2.get('player_rank', 0) or 0) if r2 is not None else None,
        'surface':    surface,
    }
