"""
WNBA Props Scanner — AI + PickFinder Signal Model

Combines trained XGBoost projections with PickFinder hit rates, consensus
odds, and line movement to identify the highest-conviction WNBA plays.

AI projection layer:
  - Loads models from models/wnba/{TARGET}_model.json
  - Builds player feature vector from latest training_dataset.csv row
  - Predicts stat output → computes edge vs PrizePicks line

Signal scoring (0–100):
  - Hit rate L10 vs line (40 pts max)
  - Book consensus % on aligned side (40 pts max)
  - Line movement toward our side (20 pts max)

Usage:
    $ python3 -m src.sports.wnba.scanner
"""

import os
import pandas as pd
import numpy as np
import xgboost as xgb
import unicodedata
import warnings
warnings.filterwarnings('ignore')

from src.core.odds_providers.prizepicks import PrizePicksClient
from src.core.odds_providers.pickfinder  import PickFinderClient
from src.sports.wnba.config import (
    STAT_MAP, ACTIVE_TARGETS, LOG_TRANSFORM_TARGETS, MODEL_QUALITY
)

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
MODEL_DIR = os.path.join(BASE_DIR, 'models', 'wnba')
DATA_FILE = os.path.join(BASE_DIR, 'data',   'wnba', 'processed', 'training_dataset.csv')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output', 'wnba', 'scans')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Calibration factors for log-transformed targets
# (log-transform regression underestimates E[y] due to Jensen's inequality)
# ---------------------------------------------------------------------------
LOG_CALIBRATION = {
    'STL':  1.20,
    'TOV':  1.15,
    'FG3M': 1.18,
    'OREB': 1.25,
    'SB':   1.20,
}

# Stats from features.py that update slowly — forward-fill to get valid values
_SLOW_FEATURES = [
    'PACE_ROLLING', 'OPP_PACE_L5', 'OPP_DEF_RTG_L5', 'OPP_WIN_PCT',
]
_TARGET_STAT_LIST = [
    'PTS', 'REB', 'AST', 'FG3M', 'STL', 'TOV', 'FGM', 'FTM',
    'DREB', 'OREB', 'FPTS', 'PRA', 'PR', 'PA', 'RA', 'SB',
]
for _s in _TARGET_STAT_LIST:
    _SLOW_FEATURES.append(f'OPP_{_s}_ALLOWED')
    _SLOW_FEATURES.append(f'OPP_{_s}_ALLOWED_DIFF')

# ---------------------------------------------------------------------------
# Stat name mapping  (PP display name → PF display name where they differ)
# ---------------------------------------------------------------------------
_PP_TO_PF = {
    'Free Throws Made':       'FT Made',
    'Free Throws Attempted':  'FT Attempts',
    'FG Attempted':           'FG Attempts',
    '3-PT Attempted':         '3-PT Attempts',
    'Fantasy Score':          'Fantasy Score (PP/UD)',
    'Two Pointers Made':      '2-PT Made',
    'Two Pointers Attempted': '2-PT Attempts',
}

STAT_TIERS = {
    'Points':        {'emoji': '💎', 'label': 'LOCK'},
    'Rebounds':      {'emoji': '💎', 'label': 'LOCK'},
    'Assists':       {'emoji': '💎', 'label': 'LOCK'},
    'Pts+Rebs+Asts': {'emoji': '🔥', 'label': 'FIRE'},
    'Pts+Rebs':      {'emoji': '🔥', 'label': 'FIRE'},
    'Pts+Asts':      {'emoji': '🔥', 'label': 'FIRE'},
    'Rebs+Asts':     {'emoji': '🔥', 'label': 'FIRE'},
    'Blks+Stls':     {'emoji': '🔥', 'label': 'FIRE'},
    'Free Throws Made': {'emoji': '🔥', 'label': 'FIRE'},
    'Fantasy Score':  {'emoji': '🔥', 'label': 'FIRE'},
    '3-PT Made':     {'emoji': '✅', 'label': 'SOLID'},
    'Steals':        {'emoji': '✅', 'label': 'SOLID'},
    'Turnovers':     {'emoji': '✅', 'label': 'SOLID'},
    'FG Made':       {'emoji': '✅', 'label': 'SOLID'},
    'Defensive Rebounds': {'emoji': '⚡', 'label': 'RISKY'},
    'Offensive Rebounds': {'emoji': '⚡', 'label': 'RISKY'},
}

MIN_HR_DEVIATION = 10    # hr >= 60% (over) or <= 40% (under)
MIN_CONSENSUS    = 0.52  # 52% consensus required


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    n = unicodedata.normalize('NFKD', str(name))
    return ''.join(c for c in n if not unicodedata.combining(c)).lower().strip()


def _signal_score(hr10, con_aligned, net_move) -> float:
    """0–100 composite signal strength."""
    score = 0.0
    if hr10 >= 0:
        dev = abs(hr10 - 50)
        score += min(dev * 0.8, 40)
    if con_aligned > 0:
        score += min((con_aligned - 0.50) * 160, 40)
    if net_move != 0:
        score += 20 if net_move > 0 else 0
    return round(score, 1)


# ---------------------------------------------------------------------------
# Model & data loading
# ---------------------------------------------------------------------------

class _EnsembleModel:
    """XGBoost (60%) + LightGBM (40%) ensemble."""
    def __init__(self, xgb_model, lgbm_booster):
        self.xgb_model    = xgb_model
        self.lgbm_booster = lgbm_booster
        self._lgbm_feats  = lgbm_booster.feature_name()

    def predict(self, X):
        import pandas as _pd
        xgb_pred  = self.xgb_model.predict(X)
        X_lgbm    = X[self._lgbm_feats] if isinstance(X, _pd.DataFrame) else X
        lgbm_pred = self.lgbm_booster.predict(X_lgbm)
        return 0.60 * xgb_pred + 0.40 * lgbm_pred

    @property
    def feature_names_in_(self):
        return self.xgb_model.feature_names_in_


def load_models():
    """Load all available WNBA XGBoost + LightGBM ensemble models."""
    models = {}
    if not os.path.exists(MODEL_DIR):
        return models
    for target in ACTIVE_TARGETS:
        xgb_path  = os.path.join(MODEL_DIR, f'{target}_model.json')
        lgbm_path = os.path.join(MODEL_DIR, f'{target}_model_lgbm.txt')
        if not os.path.exists(xgb_path):
            continue
        try:
            xgb_m = xgb.XGBRegressor()
            xgb_m.load_model(xgb_path)
            if os.path.exists(lgbm_path):
                try:
                    import lightgbm as lgb
                    lgbm_b = lgb.Booster(model_file=lgbm_path)
                    models[target] = _EnsembleModel(xgb_m, lgbm_b)
                except Exception:
                    models[target] = xgb_m
            else:
                models[target] = xgb_m
        except Exception:
            pass
    ensemble_count = sum(1 for m in models.values() if isinstance(m, _EnsembleModel))
    print(f"   WNBA: {len(models)} models ({ensemble_count} ensemble)")
    return models


def load_training_data():
    """Load WNBA training dataset. Returns DataFrame or None."""
    if not os.path.exists(DATA_FILE):
        return None
    try:
        df = pd.read_csv(DATA_FILE, low_memory=False)
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'], errors='coerce')
        return df
    except Exception:
        return None


def build_player_cache(df):
    """
    Build a {normalized_name: row_dict} lookup from the most recent game row
    per player in the training dataset.  Slow-changing features (pace, DvP)
    are forward-filled so the latest row always has a valid value.

    Returns: dict (norm_name → row_dict)
    """
    slow_present = [f for f in _SLOW_FEATURES if f in df.columns]
    df_sorted = df.sort_values(['PLAYER_ID', 'GAME_DATE']).copy()
    if slow_present:
        df_sorted[slow_present] = df_sorted.groupby('PLAYER_ID')[slow_present].ffill()

    df_latest = df_sorted.drop_duplicates(subset=['PLAYER_ID'], keep='last')

    cache = {}
    for _, row in df_latest.iterrows():
        raw_name = str(row.get('PLAYER_NAME', ''))
        norm = _norm(raw_name)
        cache[norm] = row.to_dict()
    return cache


def predict_stat(model, player_row_dict, target):
    """
    Generate a prediction for `target` given a player's latest feature row.
    Returns a float (predicted stat value) or None on failure.
    """
    if model is None or player_row_dict is None:
        return None
    try:
        feat_names = list(model.feature_names_in_)
        feat = {}
        for f in feat_names:
            val = player_row_dict.get(f, 0)
            feat[f] = 0.0 if (val is None or (isinstance(val, float) and np.isnan(val))) else float(val)
        X = pd.DataFrame([feat])[feat_names]
        raw = float(model.predict(X)[0])
        if target in LOG_TRANSFORM_TARGETS:
            raw = np.expm1(raw) * LOG_CALIBRATION.get(target, 1.0)
        return max(0.0, round(raw, 2))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_wnba(date_str=None):
    from datetime import date
    today = date_str or date.today().strftime('%Y-%m-%d')

    print("\n" + "=" * 55)
    print("   🏀 WNBA SCANNER  (AI + PickFinder)")
    print("=" * 55)
    print(f"\n   Scanning: {today}")

    # --- Load AI models (optional) ---
    models = load_models()
    player_cache = {}
    if models:
        print(f"   Models: {len(models)} loaded ({', '.join(sorted(models))})")
        df_hist = load_training_data()
        if df_hist is not None:
            player_cache = build_player_cache(df_hist)
            print(f"   Player cache: {len(player_cache)} players")
        else:
            print("   ⚠️  Training data not found — AI projections disabled")
            models = {}
    else:
        print("   ℹ️  No trained models found (run train.py first)")

    # --- PrizePicks WNBA board (include goblin/demon alt lines) ---
    pp = PrizePicksClient(stat_map={})
    pp_df = pp.fetch_board(league_filter='WNBA', include_alts=True)
    if pp_df.empty:
        print("\n   No WNBA props on PrizePicks today.")
        input("\nPress Enter to return to menu...")
        return

    pp_df = pp_df[~pp_df['Player'].str.contains(r' \+ ', na=False, regex=False)].copy()
    pp_df = pp_df[~pp_df['Stat'].str.endswith('(Combo)', na=False)].copy()
    pp_df['norm_name'] = pp_df['Player'].apply(_norm)
    pp_df['pf_stat']   = pp_df['Stat'].apply(lambda s: _PP_TO_PF.get(s, s))
    pp_df['is_goblin'] = pp_df.get('OddsType', pd.Series('standard', index=pp_df.index)).apply(
        lambda x: str(x).lower() == 'goblin'
    )
    pp_df['is_demon'] = pp_df.get('OddsType', pd.Series('standard', index=pp_df.index)).apply(
        lambda x: str(x).lower() == 'demon'
    )
    print(f"   PrizePicks: {len(pp_df)} WNBA single-player props")

    # --- PickFinder WNBA board ---
    pf_lookup  = {}
    any_loaded = False
    try:
        pf    = PickFinderClient()
        pf_df = pf.fetch_board(sport='wnba')
        mv    = pf.get_movement_summary(sport='wnba')

        wnba_pf = pf_df[pf_df['league'].str.lower().str.contains('wnba', na=False)].copy()
        if wnba_pf.empty:
            wnba_pf = pf_df

        pp_rows  = wnba_pf[wnba_pf['book'] == 'prizepicks']
        all_rows = wnba_pf.drop_duplicates(subset=['player_name_normalized', 'stat'])
        pf_dedup = pd.concat([pp_rows, all_rows]).drop_duplicates(
            subset=['player_name_normalized', 'stat'], keep='first')

        for _, row in pf_dedup.iterrows():
            norm    = row['player_name_normalized']
            pf_stat = row['stat']
            mv_data = mv.get((norm, pf_stat), {})
            pf_lookup[(norm, pf_stat)] = {
                'hr_l5':     row.get('hit_rate_l5',  -1),
                'hr_l10':    row.get('hit_rate_l10', -1),
                'hr_l15':    row.get('hit_rate_l15', -1),
                'streak':    int(row.get('streak',   0) or 0),
                'avg_l10':   row.get('avg_last10'),
                'diff_l10':  row.get('diff_last10'),
                'con_over':  float(row.get('consensus_over_ip',  0) or 0),
                'con_under': float(row.get('consensus_under_ip', 0) or 0),
                'net_move':  mv_data.get('net', 0),
                'line_moved': mv_data.get('line_moved', False),
                'pf_line':   row.get('line'),
            }
        any_loaded = True
        moved = sum(1 for v in pf_lookup.values() if v['net_move'] != 0 or v['line_moved'])
        print(f"   PickFinder: {len(pf_lookup)} props  ({moved} with line movement)")
    except Exception as e:
        print(f"   PickFinder unavailable: {e}")

    # --- Score & project each prop ---
    results = []

    for _, row in pp_df.iterrows():
        player  = row['Player']
        stat    = row['Stat']
        pf_stat = row['pf_stat']
        line    = float(row['Line'])
        norm    = row['norm_name']
        is_gob  = bool(row.get('is_goblin', False))
        is_dem  = bool(row.get('is_demon',  False))

        # PickFinder lookup
        pf = pf_lookup.get((norm, pf_stat), {})
        if not pf and pf_stat != stat:
            pf = pf_lookup.get((norm, stat), {})
        if not pf:
            continue

        hr10      = float(pf.get('hr_l10', -1))
        hr5       = float(pf.get('hr_l5',  -1))
        con_over  = pf.get('con_over',  0)
        con_under = pf.get('con_under', 0)
        net_move  = int(pf.get('net_move', 0) or 0)
        streak    = pf.get('streak', 0)
        avg_l10   = pf.get('avg_l10')
        line_mvd  = pf.get('line_moved', False)
        pf_line   = pf.get('pf_line')

        # Determine best side
        over_sig  = (hr10 if hr10 >= 0 else 0) + con_over * 100 + (10 if net_move > 0 else 0)
        under_sig = ((100 - hr10) if hr10 >= 0 else 0) + con_under * 100 + (10 if net_move < 0 else 0)

        if is_gob or is_dem:
            # Goblin/demon are Over-only on PrizePicks
            side        = 'Over'
            con_aligned = con_over
            hr_aligned  = hr10
        elif over_sig >= under_sig:
            side       = 'Over'
            con_aligned = con_over
            hr_aligned  = hr10
        else:
            side       = 'Under'
            con_aligned = con_under
            hr_aligned  = 100 - hr10 if hr10 >= 0 else -1
            net_move    = -net_move

        score = _signal_score(hr_aligned, con_aligned, net_move)

        has_hr_signal  = (hr10 >= 0 and abs(hr10 - 50) >= MIN_HR_DEVIATION)
        has_con_signal = (con_aligned >= MIN_CONSENSUS)
        has_mov_signal = (net_move > 0)
        if not (has_hr_signal or has_con_signal or has_mov_signal) and not (is_gob or is_dem):
            continue

        # AI projection
        target_code = STAT_MAP.get(stat)
        ai_proj     = None
        ai_edge     = None
        if models and target_code and target_code in models:
            player_row = player_cache.get(norm)
            if player_row is None:
                # Try fuzzy: first + last name matching
                parts = norm.split()
                if len(parts) >= 2:
                    last = parts[-1]
                    for k in player_cache:
                        if k.endswith(last) and k.split()[0][0] == parts[0][0]:
                            player_row = player_cache[k]
                            break
            if player_row:
                ai_proj = predict_stat(models[target_code], player_row, target_code)
                if ai_proj is not None:
                    ai_edge = round(ai_proj - line, 2)

        tier_info = STAT_TIERS.get(stat, {'emoji': '·', 'label': 'Other'})
        model_tier = MODEL_QUALITY.get(target_code, {}).get('tier', '') if target_code else ''

        results.append({
            'Player':      player,
            'Stat':        stat,
            'Target':      target_code or stat,
            'Tier_Emoji':  tier_info['emoji'],
            'Tier_Label':  tier_info['label'],
            'Model_Tier':  model_tier,
            'PP_Line':     line,
            'PF_Line':     pf_line,
            'AI_Proj':     ai_proj,
            'AI_Edge':     ai_edge,
            'Side':        side,
            'Is_Goblin':   is_gob,
            'Is_Demon':    is_dem,
            'HR5':         hr5,
            'HR10':        hr10,
            'HR_Aligned':  hr_aligned,
            'Streak':      streak,
            'Avg_L10':     avg_l10,
            'Con_Pct':     round(con_aligned * 100, 1),
            'Net_Move':    net_move,
            'Line_Moved':  line_mvd,
            'Signal':      score,
        })

    if not results:
        print("\n   No WNBA plays with sufficient signal today.")
        input("\nPress Enter to return to menu...")
        return

    df = pd.DataFrame(results).sort_values('Signal', ascending=False).reset_index(drop=True)

    # --- Display ---
    sep      = " │ "
    w_player = 22
    w_stat   = 16

    has_ai    = df['AI_Proj'].notna().any()
    has_avg   = df['Avg_L10'].notna().any()
    any_move  = (df['Net_Move'] != 0).any() or df['Line_Moved'].any()

    width = 104
    if has_ai:   width += 14
    if has_avg:  width += 8
    if any_move: width += 7

    def _make_header():
        h = (
            f"{'#':>3}{sep}{'TIER':<6}{sep}{'PLAYER':<{w_player}}{sep}"
            f"{'STAT':<{w_stat}}{sep}{'LINE':>5}{sep}"
        )
        if has_ai:
            h += f"{'AI':>5}{sep}{'EDGE':>5}{sep}"
        h += (
            f"{'SIDE':<8}{sep}"
            f"{'HR5':>4}{sep}{'HR10':>4}{sep}{'STRK':>5}{sep}{'CON%':>5}{sep}{'SIG':>5}"
        )
        if has_avg:  h += f"{sep}{'AVG10':>5}"
        if any_move: h += f"{sep}{'MOV':>4}"
        return h

    def _print_wnba_section(sub_df, section_title):
        if sub_df.empty:
            return
        sub_df = sub_df.sort_values('Signal', ascending=False).reset_index(drop=True)
        print(f"\n{'─' * width}")
        print(f"  {section_title}  ({len(sub_df)} plays)")
        print(f"{'─' * width}")
        header = _make_header()
        print(header)
        print(f"{'─' * width}")
        for i, row in sub_df.iterrows():
            side_s = "▲ Over  " if row['Side'] == 'Over' else "▼ Under "
            gob_s  = 'G' if row['Is_Goblin'] else ' '
            tier_s = f"{row['Tier_Emoji']}{gob_s}"
            hr5_s  = f"{int(row['HR5'])}%"      if row['HR5']  >= 0 else " N/A"
            hr10_s = f"{int(row['HR10'])}%"     if row['HR10'] >= 0 else " N/A"
            strk_s = f"{int(row['Streak']):+d}" if row['Streak'] != 0 else "    0"
            con_s  = f"{row['Con_Pct']:.1f}%"
            sig_s  = f"{row['Signal']:.0f}"
            base = (
                f"{i+1:>3}{sep}{tier_s:<6}{sep}{str(row['Player'])[:w_player]:<{w_player}}{sep}"
                f"{str(row['Stat'])[:w_stat]:<{w_stat}}{sep}"
                f"{float(row['PP_Line']):>5.1f}{sep}"
            )
            if has_ai:
                ai_s   = f"{row['AI_Proj']:.1f}"  if pd.notna(row['AI_Proj'])  else "  ---"
                edge_s = f"{row['AI_Edge']:+.1f}" if pd.notna(row['AI_Edge']) else "  ---"
                base += f"{ai_s:>5}{sep}{edge_s:>5}{sep}"
            base += (
                f"{side_s}{sep}"
                f"{hr5_s:>4}{sep}{hr10_s:>4}{sep}{strk_s:>5}{sep}"
                f"{con_s:>5}{sep}{sig_s:>5}"
            )
            if has_avg:
                avg = row['Avg_L10']
                avg_s = f"{float(avg):.1f}" if pd.notna(avg) else "  ---"
                base += f"{sep}{avg_s:>5}"
            if any_move:
                mov  = int(row['Net_Move'] or 0)
                lm   = bool(row['Line_Moved'])
                if lm:
                    mov_s = f"{mov:+d}L" if mov != 0 else "  L"
                elif mov != 0:
                    mov_s = f"{mov:+d}"
                else:
                    mov_s = " --"
                base += f"{sep}{mov_s:>4}"
            print(base)
        print(f"{'─' * width}")

    print(f"\n{'═' * width}")
    print(f"  WNBA SCANNER — {today}  ({len(df)} total plays with signal)")
    print(f"{'═' * width}")

    std_df = df[~df['Is_Goblin']]
    gob_df = df[ df['Is_Goblin']]

    _print_wnba_section(std_df, "STANDARD PLAYS")
    _print_wnba_section(gob_df, "GOBLIN PLAYS  (easier lines, lower payout)")

    print(f"\n   GOBLIN lines = lower threshold (easier to hit), lower payout than standard")
    print(f"   G=Goblin line  |  Tier: ⭐Core  ✔Combo  ~Other")
    if has_ai:
        print(f"   AI=XGBoost projection  |  EDGE=AI minus PrizePicks line (+= lean Over)")
    print(f"   HR5/HR10=PickFinder hit rate last 5/10 games vs this line")
    print(f"   STRK=consecutive over/under streak  |  CON%=book consensus (direction-aligned)")
    print(f"   AVG10=player average last 10 games  |  SIG=composite signal score (0-100)")
    if any_move:
        print(f"   MOV=net books moved toward your side  L=line number also moved")

    # Save
    from datetime import date as _date
    out_path = os.path.join(OUTPUT_DIR, f'scan_{today}.csv')
    df.to_csv(out_path, index=False)
    print(f"\n   Saved → {out_path}")

    input("\nPress Enter to return to menu...")


# ---------------------------------------------------------------------------
# Session-level lazy cache (avoids re-loading models/dataset on every search)
# ---------------------------------------------------------------------------
_SESSION: dict = {}   # keys: 'models', 'player_cache', 'player_df'

# Defensive matchup cache — built lazily from player_df; keyed by stat group
_WNBA_DEF_CACHE: dict = {}   # key: 'ranks' → {avgs, ranks, lg_avg, n}


def _ensure_session():
    """
    Load models + player cache once per session.  Subsequent calls return
    immediately from the module-level _SESSION dict.
    """
    if 'models' not in _SESSION:
        m = load_models()
        _SESSION['models'] = m
        if m:
            print(f"   Models loaded: {len(m)} ({', '.join(sorted(m))})")
        else:
            print("   ℹ️  No trained models found — AI projections unavailable")

    if 'player_cache' not in _SESSION:
        df = load_training_data()
        if df is not None:
            _SESSION['player_cache'] = build_player_cache(df)
            _SESSION['player_df']    = df
            print(f"   Player cache: {len(_SESSION['player_cache'])} players")
        else:
            _SESSION['player_cache'] = {}
            _SESSION['player_df']    = None
            print("   ⚠️  Training data not found — player history unavailable")

    return _SESSION['models'], _SESSION['player_cache'], _SESSION.get('player_df')


def _build_pf_lookup():
    """Fetch PickFinder WNBA board and return a (norm_name, stat) → data dict."""
    pf_lookup = {}
    try:
        pf    = PickFinderClient()
        pf_df = pf.fetch_board(sport='wnba')
        mv    = pf.get_movement_summary(sport='wnba')

        wnba_pf = pf_df[pf_df['league'].str.lower().str.contains('wnba', na=False)].copy()
        if wnba_pf.empty:
            wnba_pf = pf_df

        pp_rows  = wnba_pf[wnba_pf['book'] == 'prizepicks']
        all_rows = wnba_pf.drop_duplicates(subset=['player_name_normalized', 'stat'])
        pf_dedup = pd.concat([pp_rows, all_rows]).drop_duplicates(
            subset=['player_name_normalized', 'stat'], keep='first')

        for _, row in pf_dedup.iterrows():
            norm    = row['player_name_normalized']
            pf_stat = row['stat']
            mv_data = mv.get((norm, pf_stat), {})
            pf_lookup[(norm, pf_stat)] = {
                'hr_l5':      row.get('hit_rate_l5',  -1),
                'hr_l10':     row.get('hit_rate_l10', -1),
                'streak':     int(row.get('streak',   0) or 0),
                'avg_l10':    row.get('avg_last10'),
                'con_over':   float(row.get('consensus_over_ip',  0) or 0),
                'con_under':  float(row.get('consensus_under_ip', 0) or 0),
                'net_move':   mv_data.get('net', 0),
                'line_moved': mv_data.get('line_moved', False),
                'pf_line':    row.get('line'),
            }
    except Exception as e:
        print(f"   PickFinder unavailable: {e}")
    return pf_lookup


# ---------------------------------------------------------------------------
# Defensive matchup helper
# ---------------------------------------------------------------------------

def _show_def_matchup_wnba():
    """
    Prompt for a WNBA opponent team abbreviation and show a per-stat defensive
    ranking table.  Groups historical game-log data by OPPONENT, computing the
    average stats allowed per game.  Rank 1 = fewest allowed = toughest.

    Skips silently if training data isn't available.
    """
    df_hist = _SESSION.get('player_df')
    if df_hist is None or 'OPPONENT' not in df_hist.columns:
        return

    WNBA_DEF_STATS = [s for s in
                      ['PTS', 'REB', 'AST', 'FG3M', 'STL', 'BLK', 'TOV', 'FGM', 'FTM',
                       'DREB', 'OREB']
                      if s in df_hist.columns]
    if not WNBA_DEF_STATS:
        return

    opp = input("\n   Check opponent matchup? Team abbr (e.g. LVA) or Enter to skip: ").strip().upper()
    if not opp:
        return

    # Build or retrieve cached rankings (one set for all positions — WNBA
    # position data is typically 'Unknown' so no per-position filter)
    if 'ranks' not in _WNBA_DEF_CACHE:
        sub  = df_hist[df_hist['OPPONENT'].notna()].copy()
        avgs = sub.groupby('OPPONENT')[WNBA_DEF_STATS].mean()
        n    = len(avgs)
        _WNBA_DEF_CACHE['ranks']  = avgs.rank(ascending=False, method='min').astype(int)
        _WNBA_DEF_CACHE['avgs']   = avgs
        _WNBA_DEF_CACHE['lg_avg'] = avgs.mean()
        _WNBA_DEF_CACHE['n']      = n

    avgs   = _WNBA_DEF_CACHE['avgs']
    ranks  = _WNBA_DEF_CACHE['ranks']
    lg_avg = _WNBA_DEF_CACHE['lg_avg']
    n      = _WNBA_DEF_CACHE['n']

    if opp not in avgs.index:
        print(f"\n   Team '{opp}' not found.")
        print(f"   Available: {', '.join(sorted(avgs.index))}")
        return

    print(f"\n{'─' * 64}")
    print(f"   DEF MATCHUP: {opp}  (rank 1 = most allowed / WEAK  {n} = fewest / TOUGH)")
    print(f"{'─' * 64}")
    print(f"   {'STAT':<6} {'ALLOWED/G':>9} {'LG AVG':>7} {'DIFF':>6} {'RANK':>5}  VERDICT")
    print(f"{'─' * 64}")

    for stat in WNBA_DEF_STATS:
        if stat not in avgs.columns:
            continue
        allowed = avgs.loc[opp, stat]
        league  = lg_avg[stat]
        diff    = allowed - league
        rank    = int(ranks.loc[opp, stat])
        pct     = rank / n   # low rank (near 1) = most allowed = weak

        if pct <= 0.27:
            verdict = "⚠  WEAK  "
        elif pct >= 0.77:
            verdict = "✓  TOUGH "
        else:
            verdict = "   avg   "

        print(f"   {stat:<6} {allowed:>9.2f} {league:>7.2f} {diff:>+6.2f} {rank:>5}  {verdict}(#{rank}/{n})")

    print(f"{'─' * 64}")
    print(f"   ⚠ WEAK  = allows more than avg  →  favours Over bets")
    print(f"   ✓ TOUGH = allows fewer than avg  →  favours Under bets")


# ---------------------------------------------------------------------------
# Player search
# ---------------------------------------------------------------------------

def search_player():
    """
    Interactive player search.  Shows ALL of a player's current PrizePicks
    props ranked by conviction (signal score → AI edge → absolute HR dev).
    Loops until the user types '0' or 'q'.
    """
    print("\n" + "=" * 60)
    print("   🔍 WNBA PLAYER SEARCH")
    print("=" * 60)

    print("\n   Loading resources...")
    models, player_cache, player_df = _ensure_session()

    # Fetch PrizePicks board (always fresh)
    pp = PrizePicksClient(stat_map={})
    pp_full = pp.fetch_board(league_filter='WNBA', include_alts=True)
    if pp_full.empty:
        print("\n   No WNBA props on PrizePicks right now.")
        input("\nPress Enter to return to menu...")
        return

    pp_full = pp_full[~pp_full['Player'].str.contains(r' \+ ', na=False, regex=False)].copy()
    pp_full = pp_full[~pp_full['Stat'].str.endswith('(Combo)', na=False)].copy()
    pp_full['norm_name'] = pp_full['Player'].apply(_norm)
    pp_full['pf_stat']   = pp_full['Stat'].apply(lambda s: _PP_TO_PF.get(s, s))
    pp_full['is_goblin'] = pp_full.get('OddsType', pd.Series('standard', index=pp_full.index)).apply(
        lambda x: str(x).lower() == 'goblin'
    )

    # Fetch PickFinder data (internally cached 30 min)
    print("   Fetching PickFinder data...")
    pf_lookup = _build_pf_lookup()
    print(f"   PickFinder: {len(pf_lookup)} props loaded")

    # ── Search loop ──────────────────────────────────────────────────────────
    while True:
        print("\n" + "─" * 60)
        query = input("   Player name (or '0' to exit): ").strip()
        if query in ('0', 'q', ''):
            break

        query_norm = _norm(query)

        # 1. Find all PP board entries whose normalized name contains the query
        matches = pp_full[pp_full['norm_name'].str.contains(query_norm, na=False)]
        if matches.empty:
            # Also check training dataset names
            if player_cache:
                training_hits = [n for n in player_cache if query_norm in n]
                if training_hits:
                    print(f"\n   Not on PrizePicks today, but found in training data:")
                    for n in sorted(training_hits)[:8]:
                        raw = player_cache[n].get('PLAYER_NAME', n)
                        print(f"     • {raw}")
                else:
                    print(f"\n   No player found matching '{query}'.")
            else:
                print(f"\n   No player found matching '{query}'.")
            continue

        # 2. Disambiguate if multiple distinct players matched
        unique_names = matches[['Player', 'norm_name']].drop_duplicates('norm_name')
        if len(unique_names) > 1:
            print(f"\n   Multiple players matched:")
            for j, (_, r) in enumerate(unique_names.iterrows(), 1):
                print(f"     {j}. {r['Player']}")
            pick = input("   Enter number (or 0 to skip): ").strip()
            try:
                idx = int(pick) - 1
                if idx < 0 or idx >= len(unique_names):
                    continue
                chosen_norm = unique_names.iloc[idx]['norm_name']
                matches = matches[matches['norm_name'] == chosen_norm]
            except ValueError:
                continue

        chosen_player = matches['Player'].iloc[0]
        chosen_norm   = matches['norm_name'].iloc[0]

        # 3. Pull player context from training data
        hist_row = player_cache.get(chosen_norm)
        if hist_row is None:
            # Fuzzy: first-initial + last-name
            parts = chosen_norm.split()
            if len(parts) >= 2:
                last = parts[-1]
                for k, v in player_cache.items():
                    if k.endswith(last) and k.split()[0][0] == parts[0][0]:
                        hist_row = v
                        chosen_norm = k
                        break

        # 4. Score every prop on the board for this player
        props = []
        for _, row in matches.iterrows():
            stat    = row['Stat']
            pf_stat = row['pf_stat']
            line    = float(row['Line'])
            is_gob  = bool(row.get('is_goblin', False))

            # PickFinder data
            pf_data = pf_lookup.get((chosen_norm, pf_stat), {})
            if not pf_data and pf_stat != stat:
                pf_data = pf_lookup.get((chosen_norm, stat), {})

            hr5       = float(pf_data.get('hr_l5',  -1))
            hr10      = float(pf_data.get('hr_l10', -1))
            con_over  = float(pf_data.get('con_over',  0))
            con_under = float(pf_data.get('con_under', 0))
            net_move  = int(pf_data.get('net_move', 0) or 0)
            streak    = int(pf_data.get('streak', 0) or 0)
            avg_l10   = pf_data.get('avg_l10')
            line_mvd  = pf_data.get('line_moved', False)

            # Determine directional side
            over_sig  = (hr10 if hr10 >= 0 else 0) + con_over * 100 + (10 if net_move > 0 else 0)
            under_sig = ((100 - hr10) if hr10 >= 0 else 0) + con_under * 100 + (10 if net_move < 0 else 0)

            if over_sig >= under_sig:
                side        = 'Over'
                con_aligned = con_over
                hr_aligned  = hr10
                nm_aligned  = net_move
            else:
                side        = 'Under'
                con_aligned = con_under
                hr_aligned  = 100 - hr10 if hr10 >= 0 else -1
                nm_aligned  = -net_move

            signal = _signal_score(hr_aligned, con_aligned, nm_aligned)

            # AI projection
            target_code = STAT_MAP.get(stat)
            ai_proj     = None
            ai_edge     = None
            if models and target_code and target_code in models and hist_row:
                ai_proj = predict_stat(models[target_code], hist_row, target_code)
                if ai_proj is not None:
                    ai_edge = round(ai_proj - line, 2)

            # Combined rank score: signal + bonus for edge agreement with side
            rank_score = signal
            if ai_edge is not None:
                edge_agrees = (side == 'Over' and ai_edge > 0) or (side == 'Under' and ai_edge < 0)
                if edge_agrees:
                    rank_score += min(abs(ai_edge) * 2, 15)  # up to +15 bonus

            tier_info  = STAT_TIERS.get(stat, {'emoji': '·', 'label': 'Other'})
            model_tier = MODEL_QUALITY.get(target_code, {}).get('tier', '') if target_code else ''

            props.append({
                'Stat':        stat,
                'Target':      target_code or stat,
                'Tier_Emoji':  tier_info['emoji'],
                'Model_Tier':  model_tier,
                'Line':        line,
                'Is_Goblin':   is_gob,
                'AI_Proj':     ai_proj,
                'AI_Edge':     ai_edge,
                'Side':        side,
                'HR5':         hr5,
                'HR10':        hr10,
                'HR_Aligned':  hr_aligned,
                'Streak':      streak,
                'Avg_L10':     avg_l10,
                'Con_O_Pct':   round(con_over  * 100, 1),
                'Con_U_Pct':   round(con_under * 100, 1),
                'Con_Aligned': round(con_aligned * 100, 1),
                'Net_Move':    nm_aligned,
                'Line_Moved':  line_mvd,
                'Signal':      signal,
                'RankScore':   rank_score,
            })

        if not props:
            print(f"\n   No props found for {chosen_player}.")
            continue

        props_df = pd.DataFrame(props).sort_values('RankScore', ascending=False).reset_index(drop=True)

        # 5. Print player header
        has_ai  = props_df['AI_Proj'].notna().any()
        has_avg = props_df['Avg_L10'].notna().any()

        last_game = ''
        if hist_row:
            gd = hist_row.get('GAME_DATE', '')
            if gd:
                try:
                    last_game = pd.to_datetime(gd).strftime('%b %d %Y')
                except Exception:
                    last_game = str(gd)[:10]

        print(f"\n{'═' * 70}")
        print(f"   {chosen_player.upper()}")
        if last_game:
            print(f"   Last game in dataset: {last_game}")
            # Quick stat context from hist_row
            ctx_parts = []
            for _s, _lbl in [('PTS_L10', 'pts'), ('REB_L10', 'reb'), ('AST_L10', 'ast')]:
                if hist_row and _s in hist_row and hist_row[_s] not in (None, float('nan')):
                    try:
                        ctx_parts.append(f"{float(hist_row[_s]):.1f} {_lbl}")
                    except Exception:
                        pass
            if ctx_parts:
                print(f"   L10 avg: {' / '.join(ctx_parts)}")
        print(f"   {len(props_df)} prop(s) on PrizePicks today")
        print(f"{'═' * 70}")

        # Column widths
        w_stat = 18
        sep    = " │ "

        width = 52 + w_stat
        if has_ai:   width += 14
        if has_avg:  width += 8

        header  = f"{'#':>3}{sep}{'STAT':<{w_stat}}{sep}{'LINE':>5}{sep}"
        if has_ai:
            header += f"{'AI':>5}{sep}{'EDGE':>5}{sep}"
        header += f"{'SIDE':<8}{sep}{'HR5':>4}{sep}{'HR10':>4}{sep}{'STRK':>5}{sep}{'CON%':>5}{sep}{'SIG':>5}"
        if has_avg:
            header += f"{sep}{'AVG':>5}"

        print(header)
        print("─" * len(header))

        for rank_i, row in props_df.iterrows():
            gob_s    = ' (G)' if row['Is_Goblin'] else ''
            stat_s   = f"{row['Tier_Emoji']} {row['Stat']}{gob_s}"
            side_s   = "▲ Over  " if row['Side'] == 'Over' else "▼ Under "
            hr5_s    = f"{int(row['HR5'])}%"       if row['HR5']  >= 0 else " N/A"
            hr10_s   = f"{int(row['HR10'])}%"      if row['HR10'] >= 0 else " N/A"
            strk_s   = f"{int(row['Streak']):+d}"  if row['Streak'] != 0 else "    0"
            con_s    = f"{row['Con_Aligned']:.1f}%"
            sig_s    = f"{row['Signal']:.0f}"

            line_s   = (
                f"{float(row['Line']):>5.1f}"
            )
            base = (
                f"{rank_i+1:>3}{sep}{stat_s[:w_stat]:<{w_stat}}{sep}"
                f"{line_s}{sep}"
            )
            if has_ai:
                ai_s   = f"{row['AI_Proj']:.1f}"  if pd.notna(row['AI_Proj'])  else "  ---"
                edge_s = f"{row['AI_Edge']:+.1f}" if pd.notna(row['AI_Edge']) else "  ---"
                base += f"{ai_s:>5}{sep}{edge_s:>5}{sep}"
            base += (
                f"{side_s}{sep}"
                f"{hr5_s:>4}{sep}{hr10_s:>4}{sep}{strk_s:>5}{sep}"
                f"{con_s:>5}{sep}{sig_s:>5}"
            )
            if has_avg:
                avg = row['Avg_L10']
                avg_s = f"{float(avg):.1f}" if pd.notna(avg) else "  ---"
                base += f"{sep}{avg_s:>5}"

            # Highlight top play
            prefix = " ★" if rank_i == 0 else "  "
            print(f"{prefix}{base}")

        print("─" * len(header))
        if has_ai:
            print("   AI=XGBoost projection  │  EDGE=AI−Line (+= lean Over)")
        print("   HR=PickFinder hit rate  │  CON%=consensus (direction-aligned)")
        print("   SIG=signal score 0–100  │  ⭐Core  ✔Combo  ~Other  (G)=Goblin line")

        # Defensive matchup breakdown (optional — user can skip with Enter)
        _show_def_matchup_wnba()


def main():
    scan_wnba()


if __name__ == "__main__":
    main()
