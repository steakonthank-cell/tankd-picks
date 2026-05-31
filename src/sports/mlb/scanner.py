"""
MLB Props Scanner - AI-Powered Prediction System

Scans today's MLB slate, generates player performance predictions using
trained XGBoost models, and identifies +EV opportunities vs PrizePicks lines.

Usage:
    $ python3 -m src.sports.mlb.scanner
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import requests
import os
import warnings
from datetime import datetime, timedelta

from src.core.odds_providers.prizepicks  import PrizePicksClient
from src.core.odds_providers.pickfinder  import PickFinderClient
from src.core.odds_providers.mlb_splits  import get_todays_splits, get_defensive_matchups
from src.core.odds_providers.mlb_context import get_game_context, pa_factor
from src.sports.mlb.config   import STAT_MAP, MODEL_QUALITY, ACTIVE_TARGETS, PITCHER_STATS, COMBO_STATS
from src.sports.mlb.mappings import normalize_name, STAT_MAPPING, VOLATILITY_MAP
from src.sports.mlb.train    import (
    BATTER_FEATURES, PITCHER_FEATURES,
    BATTER_ROLL_STATS, PITCHER_ROLL_STATS,
    BATTER_WINDOWS, PITCHER_WINDOWS,
)

warnings.filterwarnings('ignore')

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MODEL_DIR = os.path.join(BASE_DIR, 'models', 'mlb')
BATTER_FILE  = os.path.join(BASE_DIR, 'data', 'mlb', 'processed', 'batter_training.csv')
PITCHER_FILE = os.path.join(BASE_DIR, 'data', 'mlb', 'processed', 'pitcher_training.csv')
PROJ_DIR  = os.path.join(BASE_DIR, 'data', 'mlb', 'projections')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output', 'mlb', 'scans')

os.makedirs(PROJ_DIR,   exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

MLB_API = "https://statsapi.mlb.com/api/v1"


# ---------------------------------------------------------------------------
# DATA & MODEL LOADING
# ---------------------------------------------------------------------------

def load_data():
    batters  = None
    pitchers = None

    if os.path.exists(BATTER_FILE):
        batters = pd.read_csv(BATTER_FILE, low_memory=False)
        batters['date'] = pd.to_datetime(batters['date'], errors='coerce')
        batters = batters.sort_values(['player_id', 'date']).reset_index(drop=True)
        batters['clean_name'] = batters['player_name'].apply(normalize_name)
        print(f"   Batter history: {len(batters):,} rows, {batters['clean_name'].nunique():,} players")
    else:
        print("   ⚠️  No batter training data found.")

    if os.path.exists(PITCHER_FILE):
        pitchers = pd.read_csv(PITCHER_FILE, low_memory=False)
        pitchers['date'] = pd.to_datetime(pitchers['date'], errors='coerce')
        pitchers = pitchers.sort_values(['player_id', 'date']).reset_index(drop=True)
        pitchers['clean_name'] = pitchers['player_name'].apply(normalize_name)
        print(f"   Pitcher history: {len(pitchers):,} rows, {pitchers['clean_name'].nunique():,} pitchers")
    else:
        print("   ⚠️  No pitcher training data found.")

    return batters, pitchers


class _EnsembleModel:
    """XGBoost (60%) + LightGBM (40%) ensemble with XGBRegressor interface."""
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

    # Proxy attribute so callers can do model.feature_names_in_
    @property
    def feature_names_in_(self):
        return self.xgb_model.feature_names_in_


def load_models():
    models = {}
    if not os.path.exists(MODEL_DIR):
        return models
    for fname in os.listdir(MODEL_DIR):
        if not fname.endswith('_model.json'):
            continue
        stat      = fname.replace('_model.json', '')
        xgb_path  = os.path.join(MODEL_DIR, fname)
        lgbm_path = os.path.join(MODEL_DIR, f'{stat}_model_lgbm.txt')
        xgb_m = xgb.XGBRegressor()
        xgb_m.load_model(xgb_path)
        if os.path.exists(lgbm_path):
            try:
                import lightgbm as lgb
                lgbm_b = lgb.Booster(model_file=lgbm_path)
                models[stat] = _EnsembleModel(xgb_m, lgbm_b)
            except Exception:
                models[stat] = xgb_m  # fallback to XGB only
        else:
            models[stat] = xgb_m
    ensemble_count = sum(1 for m in models.values() if isinstance(m, _EnsembleModel))
    print(f"   Loaded {len(models)} models ({ensemble_count} ensemble, "
          f"{len(models)-ensemble_count} XGB-only): {', '.join(sorted(models.keys()))}")
    return models


# ---------------------------------------------------------------------------
# FEATURE GENERATION
# ---------------------------------------------------------------------------

def _compute_rolling_features(player_history, roll_stats, windows):
    """Given a player's sorted game history, compute rolling features for next game."""
    features = {}
    for stat in roll_stats:
        if stat not in player_history.columns:
            for w in windows:
                features[f'{stat}_L{w}'] = 0.0
            features[f'{stat}_season_avg'] = 0.0
            continue

        series = player_history[stat].dropna().values
        if len(series) == 0:
            for w in windows:
                features[f'{stat}_L{w}'] = 0.0
            features[f'{stat}_season_avg'] = 0.0
            continue

        for w in windows:
            features[f'{stat}_L{w}'] = float(np.mean(series[-w:])) if len(series) >= 1 else 0.0
        features[f'{stat}_season_avg'] = float(np.mean(series))

    return features


def build_batter_features_for_player(player_history, is_home):
    feats = _compute_rolling_features(player_history, BATTER_ROLL_STATS, BATTER_WINDOWS)
    feats['is_home']      = float(is_home)
    feats['games_played'] = float(len(player_history))
    return feats


def build_pitcher_features_for_player(player_history, is_home, is_starter=1):
    feats = _compute_rolling_features(player_history, PITCHER_ROLL_STATS, PITCHER_WINDOWS)
    feats['is_home']    = float(is_home)
    feats['is_starter'] = float(is_starter)
    feats['apps_season'] = float(len(player_history))
    return feats


# ---------------------------------------------------------------------------
# TODAY'S GAMES
# ---------------------------------------------------------------------------

def get_todays_games(date_str=None):
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
    try:
        r = requests.get(f"{MLB_API}/schedule", params={
            'sportId': 1, 'date': date_str, 'gameType': 'R',
        }, timeout=15)
        data = r.json()
        games = []
        for date_entry in data.get('dates', []):
            for game in date_entry.get('games', []):
                games.append({
                    'gamePk':   game['gamePk'],
                    'home_team': game['teams']['home']['team']['name'],
                    'away_team': game['teams']['away']['team']['name'],
                    'home_id':   game['teams']['home']['team']['id'],
                    'away_id':   game['teams']['away']['team']['id'],
                    'date':      date_str,
                })
        return games
    except Exception as e:
        print(f"   ⚠️  Could not fetch schedule: {e}")
        return []


# ---------------------------------------------------------------------------
# PROJECTIONS
# ---------------------------------------------------------------------------

def _load_pickfinder_enrichment(sport='mlb'):
    """
    Load PickFinder hit-rate, consensus, and line-movement data.
    Returns {(normalized_player, stat_display): {hr_l5, hr_l10, streak, con_over, con_under,
                                                   net_move, line_moved, pf_line}}
    """
    import os
    if not os.getenv('PICKFINDER_EMAIL', ''):
        return {}
    try:
        pf = PickFinderClient()
        df = pf.fetch_board(sport=sport)
        if df.empty:
            return {}

        # Movement summary aggregated across all books
        mv = pf.get_movement_summary(sport=sport)

        # One row per player+stat (PrizePicks book preferred for the line value)
        df_pp = df[df['book'] == 'prizepicks'].copy()
        if df_pp.empty:
            df_pp = df.drop_duplicates(subset=['player_name_normalized', 'stat'])

        lookup = {}
        for _, row in df_pp.iterrows():
            key    = (row['player_name_normalized'], row['stat'])
            mv_dat = mv.get(key, {})
            lookup[key] = {
                'hr_l5':      row.get('hit_rate_l5', -1),
                'hr_l10':     row.get('hit_rate_l10', -1),
                'streak':     row.get('streak', 0),
                'con_over':   row.get('consensus_over_ip', 0),
                'con_under':  row.get('consensus_under_ip', 0),
                'fav_over':   row.get('favorite_count_over', 0),
                'fav_under':  row.get('favorite_count_under', 0),
                'pf_line':    row.get('line'),
                'net_move':   mv_dat.get('net', 0),
                'line_moved': mv_dat.get('line_moved', False),
            }
        moved_count = sum(1 for v in lookup.values() if v['net_move'] != 0 or v['line_moved'])
        print(f"   PickFinder enrichment: {len(lookup)} props loaded  ({moved_count} with line movement)")
        return lookup
    except Exception as e:
        print(f"   PickFinder enrichment skipped: {e}")
        return {}


def get_all_projections(df_batters, df_pitchers, models, date_str=None):
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')

    cutoff = pd.to_datetime(date_str)

    pp = PrizePicksClient(stat_map=STAT_MAP)
    pp_df = pp.fetch_board(league_filter='MLB', include_alts=True)
    if pp_df.empty:
        print("   No MLB lines on PrizePicks today.")
        return pd.DataFrame()

    print(f"   PrizePicks: {len(pp_df)} MLB props")

    pp_df['stat_code'] = pp_df['Stat'].map(STAT_MAPPING)

    # Report props that exist but aren't modeled (combos, unsupported stats)
    unmodeled = pp_df[pp_df['stat_code'].isna()]['Stat'].unique()
    if len(unmodeled):
        print(f"   Skipping (no model): {', '.join(sorted(unmodeled))}")

    pp_df = pp_df.dropna(subset=['stat_code'])
    pp_df = pp_df[pp_df['stat_code'].isin(ACTIVE_TARGETS)]
    pp_df['clean_name'] = pp_df['Player'].apply(normalize_name)

    # Load PickFinder enrichment data (hit rates, streaks, consensus, movement)
    pf_lookup = _load_pickfinder_enrichment(sport='mlb')

    # Load MLB splits (OPS / AVG / K% vs today's opposing pitcher hand)
    splits_lookup = {}
    try:
        splits_lookup = get_todays_splits()
    except Exception as _se:
        print(f"   MLB splits skipped: {_se}")

    # Load defensive matchups (opposing pitcher stats for batters; opposing lineup for pitchers)
    batter_def = {}
    pitcher_def = {}
    try:
        batter_def, pitcher_def = get_defensive_matchups()
    except Exception as _de:
        print(f"   Defensive matchups skipped: {_de}")

    # Load game context: park factors, Vegas totals, weather, batting order, player→team
    team_ctx       = {}
    bat_orders     = {}
    player_to_team = {}
    try:
        team_ctx, bat_orders, player_to_team = get_game_context()
    except Exception as _ce:
        print(f"   Game context skipped: {_ce}")

    results = []

    for _, row in pp_df.iterrows():
        player_name  = row['Player']
        clean        = row['clean_name']
        stat_code    = row['stat_code']
        pp_line      = row['Line']
        stat_display = row['Stat']
        is_pitcher   = stat_code in PITCHER_STATS
        odds_type    = str(row.get('OddsType', 'standard') or 'standard').lower()
        is_goblin    = (odds_type == 'goblin')
        is_demon     = (odds_type == 'demon')

        # Allow combo stats (no single model needed — components summed below)
        if stat_code not in models and stat_code not in COMBO_STATS:
            continue

        if is_pitcher:
            if df_pitchers is None:
                continue
            history = df_pitchers[
                (df_pitchers['clean_name'] == clean) &
                (df_pitchers['date'] < cutoff)
            ].tail(20)
            if len(history) < 3:
                names = df_pitchers['clean_name'].unique()
                best  = _fuzzy_match(clean, names)
                if best:
                    history = df_pitchers[
                        (df_pitchers['clean_name'] == best) &
                        (df_pitchers['date'] < cutoff)
                    ].tail(20)
            if len(history) < 2:
                continue
            feats = build_pitcher_features_for_player(history, is_home=1)
            feat_list = PITCHER_FEATURES
        else:
            if df_batters is None:
                continue
            history = df_batters[
                (df_batters['clean_name'] == clean) &
                (df_batters['date'] < cutoff)
            ].tail(30)
            if len(history) < 3:
                names = df_batters['clean_name'].unique()
                best  = _fuzzy_match(clean, names)
                if best:
                    history = df_batters[
                        (df_batters['clean_name'] == best) &
                        (df_batters['date'] < cutoff)
                    ].tail(30)
            if len(history) < 2:
                continue
            feats = build_batter_features_for_player(history, is_home=1)
            feat_list = BATTER_FEATURES

        feat_cols = [f for f in feat_list if f in feats]

        def _make_feat_vec(model, feats):
            """Build feature vector using exactly the columns the model was trained on."""
            try:
                model_cols = list(model.feature_names_in_)
            except AttributeError:
                model_cols = feat_cols
            return pd.DataFrame([{c: feats.get(c, 0.0) for c in model_cols}])

        # Combo stats — predicted by summing component model projections
        if stat_code in COMBO_STATS:
            component_codes = COMBO_STATS[stat_code]   # e.g. ['H', 'R', 'RBI']
            proj = 0.0
            skip = False
            for comp in component_codes:
                if comp not in models:
                    skip = True
                    break
                try:
                    proj += float(models[comp].predict(_make_feat_vec(models[comp], feats))[0])
                except Exception:
                    skip = True
                    break
            if skip:
                continue
            proj = max(0.0, proj)
        else:
            model = models[stat_code]
            try:
                proj = float(model.predict(_make_feat_vec(model, feats))[0])
                proj = max(0.0, proj)
            except Exception:
                continue

        # --- Game context: park factor / wind / batting order PA adjustment ---
        player_team  = player_to_team.get(normalize_name(player_name), '')
        ctx          = team_ctx.get(player_team, {})

        # Park factor for this stat (average of components for combo stats)
        pf_dict = ctx.get('park_factors', {})
        if stat_code in COMBO_STATS:
            comps   = COMBO_STATS[stat_code]
            pf_mult = sum(pf_dict.get(c, 1.0) for c in comps) / len(comps)
        else:
            pf_mult = pf_dict.get(stat_code, 1.0)

        # Wind boost (HR, TB, HRR — power props — on outdoor parks)
        wind_mult = ctx.get('wind_boost', 1.0) if stat_code in ('HR', 'TB', 'HRR') else 1.0

        # Batting order PA adjustment (counting stats, not pitcher props)
        bat_pos  = bat_orders.get(normalize_name(player_name), {}).get('bat_order', 0)
        pa_mult  = pa_factor(bat_pos) if (not is_pitcher and bat_pos > 0) else 1.0

        # Apply all multipliers to raw model projection
        proj = proj * pf_mult * wind_mult * pa_mult

        edge = proj - pp_line
        safe_denom = max(pp_line, 0.5)
        edge_pct = (abs(edge) / safe_denom) * 100

        tier_info = MODEL_QUALITY.get(stat_code, {})
        threshold = tier_info.get('threshold', 20.0)
        # Always keep demon/goblin lines regardless of edge threshold —
        # they are alt lines the user wants to see separately.
        if edge_pct < threshold and not is_goblin and not is_demon:
            continue

        # PickFinder enrichment (hit rates, streak, consensus, movement)
        pf_key  = (normalize_name(player_name), stat_display)
        pf_data = pf_lookup.get(pf_key, {})

        # Flip net_move sign for UNDER bets (positive net = over pressure)
        is_over  = edge > 0
        net_move = pf_data.get('net_move', 0) or 0
        pf_mov   = net_move if is_over else -net_move

        # MLB splits (OPS / AVG / K% vs today's opposing pitcher hand)
        sp_data = splits_lookup.get(normalize_name(player_name), {})

        # Defensive matchup context
        if is_pitcher:
            def_data = pitcher_def.get(normalize_name(player_name), {})
        else:
            def_data = batter_def.get(normalize_name(player_name), {})

        result = {
            'Player':      player_name,
            'Stat':        stat_code,
            'Stat_Label':  stat_display,
            'Is_Pitcher':  is_pitcher,
            'Is_Goblin':   is_goblin,
            'Is_Demon':    is_demon,
            'PP_Line':     pp_line,
            'AI_Proj':     round(proj, 2),
            'Edge':        round(edge, 2),
            'Edge_Pct':    round(edge_pct, 1),
            'Side':        'Over' if is_over else 'Under',
            'Tier':        tier_info.get('emoji', '') + ' ' + tier_info.get('tier', ''),
            'L5':          round(sum(feats.get(f'{c}_L5', feats.get(f'{c}_L3', 0)) for c in COMBO_STATS[stat_code]), 2)
                           if stat_code in COMBO_STATS else
                           round(feats.get(f'{stat_code}_L5', feats.get(f'{stat_code}_L3', 0)), 2),
            'L10':         round(sum(feats.get(f'{c}_L10', 0) for c in COMBO_STATS[stat_code]), 2)
                           if stat_code in COMBO_STATS else
                           round(feats.get(f'{stat_code}_L10', 0), 2),
            'HR_L10':      pf_data.get('hr_l10', -1),
            'Streak':      pf_data.get('streak', 0),
            'Con_Over':    round(pf_data.get('con_over', 0) * 100, 1) if pf_data else 0,
            'MOV':         pf_mov,
            'LINE_MOVED':  pf_data.get('line_moved', False),
            # Handedness splits (batters only)
            'OPS_vs':      sp_data.get('ops', None),
            'AVG_vs':      sp_data.get('avg', None),
            'AB_vs':       sp_data.get('ab', None),
            'K_Pct_vs':    sp_data.get('k_pct', None),
            'Pitch_Hand':  sp_data.get('hand', ''),
            # Defensive matchup — batter rows: opposing pitcher stats
            #                    pitcher rows: opposing lineup stats
            'DEF_ERA':     def_data.get('era',       None) if not is_pitcher else None,
            'DEF_WHIP':    def_data.get('whip',      None) if not is_pitcher else None,
            'DEF_K9':      def_data.get('k9',        None) if not is_pitcher else None,
            'OPP_PITCHER': def_data.get('opp_pitcher','')  if not is_pitcher else '',
            'DEF_OPS':     def_data.get('team_ops',  None) if is_pitcher else None,
            'DEF_K_PCT':   def_data.get('team_k_pct',None) if is_pitcher else None,
            'OPP_TEAM':    def_data.get('opp_team',  '')   if is_pitcher else '',
            # Game context (park factor, totals, weather, batting order)
            'PF_Mult':     round(pf_mult, 3),
            'BAT_POS':     bat_pos if bat_pos > 0 else None,
            'PA_Mult':     round(pa_mult, 3),
            'Game_Total':  ctx.get('total'),
            'Implied':     ctx.get('implied'),
            'Wind_Speed':  ctx.get('wind_speed'),
            'Wind_Dir':    ctx.get('wind_dir', ''),
            'Temp_F':      ctx.get('temp_f'),
            'Is_Indoor':   ctx.get('is_indoor', False),
        }
        results.append(result)

    return pd.DataFrame(results)


def _fuzzy_match(target, candidates, threshold=0.75):
    from difflib import SequenceMatcher
    best_score = 0.0
    best_name  = None
    for cand in candidates:
        score = SequenceMatcher(None, target, cand).ratio()
        if score > best_score:
            best_score = score
            best_name  = cand
    return best_name if best_score >= threshold else None


# ---------------------------------------------------------------------------
# DISPLAY
# ---------------------------------------------------------------------------

def _print_section(df, title, has_pf, any_move, has_splits, has_def, has_lineup, has_ctx, has_wind, w_player, sep, width):
    """Print one section of results (e.g. Standard Pitcher Plays)."""
    if df.empty:
        return
    df = df.sort_values('Edge_Pct', ascending=False).reset_index(drop=True)
    print(f"\n{'─' * width}")
    print(f"  {title}  ({len(df)} plays)")
    print(f"{'─' * width}")

    if has_pf:
        header = (
            f"{'#':>3}{sep}{'TIER':<12}{sep}{'PLAYER':<{w_player}}{sep}"
            f"{'STAT':<9}{'FLG'}{sep}{'LINE':>5}{sep}{'PROJ':>6}{sep}"
            f"{'EDGE':>7}{sep}{'SIDE':<7}{sep}{'L5':>5}{sep}{'L10':>5}{sep}"
            f"{'HR10':>5}{sep}{'STRK':>5}{sep}{'CON%':>5}"
        )
        if any_move:
            header += f"{sep}{'MOV':>4}"
    else:
        header = (
            f"{'#':>3}{sep}{'TIER':<12}{sep}{'PLAYER':<{w_player}}{sep}"
            f"{'STAT':<9}{'FLG'}{sep}{'LINE':>5}{sep}{'PROJ':>6}{sep}"
            f"{'EDGE':>7}{sep}{'SIDE':<7}{sep}{'L5':>5}{sep}{'L10':>5}"
        )
    if has_splits:
        header += f"{sep}{'vs':>2}{'OPS':>6}{sep}{'AVG':>5}{sep}{'K%':>5}"
    if has_def:
        header += f"{sep}{'DEF1':>5}{sep}{'DEF2':>5}"
    if has_lineup:
        header += f"{sep}{'POS':>3}"
    if has_ctx:
        header += f"{sep}{'TOT':>4}{sep}{'IMP':>4}"
    if has_wind:
        header += f"{sep}{'WIND':>5}{sep}{'TMP':>4}"
    print(header)
    print(f"{'─' * width}")

    for i, row in df.iterrows():
        side_disp  = "▲ Over " if row['Side'] == 'Over' else "▼ Under"
        player     = str(row['Player'])[:w_player]
        is_goblin  = bool(row.get('Is_Goblin', False))
        is_pitcher = bool(row.get('Is_Pitcher', False))
        stat_raw   = str(row.get('Stat_Label', row.get('Stat', '')))[:9]
        stat_flag  = (' G' if is_goblin else '  ') + ('P' if is_pitcher else ' ')
        base = (
            f"{i+1:>3}{sep}{str(row['Tier']):<12}{sep}{player:<{w_player}}{sep}"
            f"{stat_raw:<9}{stat_flag}{sep}{float(row['PP_Line']):>5.1f}{sep}"
            f"{float(row['AI_Proj']):>6.2f}{sep}"
            f"{float(row['Edge_Pct']):>6.1f}%{sep}{side_disp}{sep}"
            f"{float(row['L5']):>5.2f}{sep}{float(row['L10']):>5.2f}"
        )
        if has_pf:
            hr10   = row.get('HR_L10', -1)
            streak = row.get('Streak', 0)
            con    = row.get('Con_Over', 0)
            hr10_s = f"{hr10:.0f}%" if hr10 >= 0 else "  N/A"
            strk_s = f"{int(streak):>5}" if streak else "    0"
            con_s  = f"{con:.0f}%"
            base += f"{sep}{hr10_s:>5}{sep}{strk_s}{sep}{con_s:>5}"
            if any_move:
                mov  = int(row.get('MOV', 0) or 0)
                lm   = bool(row.get('LINE_MOVED', False))
                if lm:
                    mov_s = f"{mov:+d}L" if mov != 0 else "  L"
                elif mov != 0:
                    mov_s = f"{mov:+d}"
                else:
                    mov_s = " --"
                base += f"{sep}{mov_s:>4}"
        if has_splits:
            ops  = row.get('OPS_vs')
            avg  = row.get('AVG_vs')
            kpct = row.get('K_Pct_vs')
            hand = str(row.get('Pitch_Hand', '') or '')
            vs_label = f"v{hand}" if hand else "  "
            ops_s  = f"{ops:.3f}" if ops  is not None else "  ---"
            avg_s  = f"{avg:.3f}" if avg  is not None else "  ---"
            kpct_s = f"{kpct:.1f}%" if kpct is not None else "  ---"
            base += f"{sep}{vs_label:>2}{ops_s:>6}{sep}{avg_s:>5}{sep}{kpct_s:>5}"
        if has_def:
            if is_pitcher:
                d_ops  = row.get('DEF_OPS')
                d_kpct = row.get('DEF_K_PCT')
                col1 = f"{d_ops:.3f}" if d_ops  is not None else "  ---"
                col2 = f"{d_kpct:.1f}%" if d_kpct is not None else "  ---"
            else:
                d_era  = row.get('DEF_ERA')
                d_whip = row.get('DEF_WHIP')
                col1 = f"{d_era:.2f}" if d_era  is not None else "  ---"
                col2 = f"{d_whip:.2f}" if d_whip is not None else "  ---"
            base += f"{sep}{col1:>5}{sep}{col2:>5}"
        if has_lineup:
            pos = row.get('BAT_POS')
            pos_s = f"{int(pos):>3}" if pos is not None else " --"
            base += f"{sep}{pos_s}"
        if has_ctx:
            gt  = row.get('Game_Total')
            imp = row.get('Implied')
            gt_s  = f"{gt:.1f}" if gt  is not None else " ---"
            imp_s = f"{imp:.1f}" if imp is not None else " ---"
            base += f"{sep}{gt_s:>4}{sep}{imp_s:>4}"
        if has_wind:
            ws  = row.get('Wind_Speed')
            wd  = str(row.get('Wind_Dir', '') or '')
            tmp = row.get('Temp_F')
            indoor = bool(row.get('Is_Indoor', False))
            if indoor:
                wind_s = "  IDR"
                tmp_s  = "  --"
            else:
                wind_s = f"{int(ws)}{wd}" if pd.notna(ws) else "  ---"
                tmp_s  = f"{int(tmp)}°"  if pd.notna(tmp) else " --"
            base += f"{sep}{wind_s:>5}{sep}{tmp_s:>4}"
        print(base)

    print(f"{'─' * width}")


def print_results(df, title="MLB AI SCANNER"):
    if df.empty:
        print("\n   No plays found above edge threshold.")
        return

    df = df.sort_values('Edge_Pct', ascending=False).reset_index(drop=True)

    has_pf     = 'HR_L10' in df.columns and (df['HR_L10'] != -1).any()
    any_move   = has_pf and 'MOV' in df.columns and (
        (df['MOV'] != 0).any() or df.get('LINE_MOVED', pd.Series(False)).any()
    )
    has_splits = ('OPS_vs'      in df.columns and df['OPS_vs'].notna().any())
    has_def    = ('DEF_ERA'     in df.columns and df['DEF_ERA'].notna().any()) or \
                 ('DEF_OPS'     in df.columns and df['DEF_OPS'].notna().any())
    has_ctx    = ('Game_Total'  in df.columns and df['Game_Total'].notna().any())
    has_lineup = ('BAT_POS'     in df.columns and df['BAT_POS'].notna().any())
    has_wind   = ('Wind_Speed'  in df.columns and df['Wind_Speed'].notna().any())

    w_player = 24
    sep = " │ "

    width = 96
    if has_pf:      width = 116
    if any_move:    width += 8
    if has_splits:  width += 26
    if has_def:     width += 22
    if has_ctx:     width += 16
    if has_lineup:  width += 6
    if has_wind:    width += 12

    print(f"\n{'═' * width}")
    print(f"  {title}")
    print(f"{'═' * width}")

    # Split into 4 sections: standard/goblin × pitcher/hitter
    std_pitchers  = df[ df['Is_Pitcher'] & ~df['Is_Goblin']]
    std_hitters   = df[~df['Is_Pitcher'] & ~df['Is_Goblin']]
    gob_pitchers  = df[ df['Is_Pitcher'] &  df['Is_Goblin']]
    gob_hitters   = df[~df['Is_Pitcher'] &  df['Is_Goblin']]

    kw = dict(
        has_pf=has_pf, any_move=any_move, has_splits=has_splits,
        has_def=has_def, has_lineup=has_lineup, has_ctx=has_ctx,
        has_wind=has_wind, w_player=w_player, sep=sep, width=width,
    )
    _print_section(std_pitchers, "PITCHER PLAYS  (standard lines)", **kw)
    _print_section(std_hitters,  "HITTER PLAYS   (standard lines)", **kw)
    _print_section(gob_pitchers, "GOBLIN PITCHER PLAYS  (easier lines, lower payout)", **kw)
    _print_section(gob_hitters,  "GOBLIN HITTER PLAYS   (easier lines, lower payout)", **kw)

    print(f"\n{'─' * width}")
    print(f"   GOBLIN lines = lower threshold (easier to hit), lower payout than standard")
    print(f"   FLG: G=Goblin line  P=Pitcher prop")
    print(f"   AI_Proj already includes park factor + wind boost + batting order PA adjustment")
    legend_parts = []
    if has_pf:
        legend_parts.append("HR10=Hit Rate L10 | STRK=streak | CON%=consensus over %")
    if any_move:
        legend_parts.append("MOV=books moved toward your side")
    if has_splits:
        legend_parts.append("vR/vL OPS|AVG|K% = splits vs opp pitcher hand")
    if has_def:
        legend_parts.append("DEF1/DEF2: batters→ERA/WHIP | pitchers→oOPS/oK%")
    if has_lineup:
        legend_parts.append("POS=batting order slot")
    if has_ctx:
        legend_parts.append("TOT=game O/U | IMP=this team's implied runs")
    if has_wind:
        legend_parts.append("WIND=mph+direction | TMP=°F | IDR=indoor/dome")
    if legend_parts:
        for chunk in [legend_parts[i:i+3] for i in range(0, len(legend_parts), 3)]:
            print("   " + " | ".join(chunk))


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

_SESSION_BATTERS  = None
_SESSION_PITCHERS = None
_SESSION_MODELS   = None
_SESSION_LOADED   = False


def _ensure_session():
    global _SESSION_BATTERS, _SESSION_PITCHERS, _SESSION_MODELS, _SESSION_LOADED
    # Only skip reload if data actually loaded successfully
    if _SESSION_LOADED and (_SESSION_BATTERS is not None or _SESSION_PITCHERS is not None):
        return _SESSION_BATTERS, _SESSION_PITCHERS, _SESSION_MODELS
    print("\n   Loading data and models...")
    _SESSION_BATTERS, _SESSION_PITCHERS = load_data()
    _SESSION_MODELS  = load_models()
    _SESSION_LOADED  = True
    return _SESSION_BATTERS, _SESSION_PITCHERS, _SESSION_MODELS


def main():
    print("\n" + "=" * 55)
    print("   ⚾ MLB AI SCANNER")
    print("=" * 55)

    batters, pitchers, models = _ensure_session()

    if not models:
        print("\n❌ No trained models found. Run 'Train Models' first.")
        input("\nPress Enter to continue...")
        return

    today = datetime.now().strftime('%Y-%m-%d')
    print(f"\n   Scanning: {today}")

    games = get_todays_games(today)
    if games:
        print(f"   Today's games: {len(games)}")
        for g in games:
            print(f"      {g['away_team']} @ {g['home_team']}")
    else:
        print("   No games found via MLB API (using PrizePicks as schedule source)")

    print("\n   Fetching PrizePicks lines...")
    proj_df = get_all_projections(batters, pitchers, models, today)

    print_results(proj_df, title=f"MLB AI SCANNER — {today}")

    if not proj_df.empty:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, f'scan_{today}.csv')
        proj_df.to_csv(out_path, index=False)
        print(f"\n   Saved → {out_path}")

    input("\nPress Enter to return to menu...")


if __name__ == "__main__":
    main()
