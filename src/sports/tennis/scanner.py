"""
Tennis Props Scanner - AI-Powered Prediction System

Scans upcoming ATP/WTA matches, generates predictions using trained XGBoost
models, and identifies profitable PrizePicks opportunities.

Zero external API dependencies beyond PrizePicks:
    - Rankings:  Sackmann GitHub (free, same source as training data)
    - Surface:   Derived from tournament name via built-in lookup table
    - Schedule:  Driven entirely by PrizePicks lines (if PP has a line, there's a match)

Features:
    1. Scan today's matches
    2. Scan tomorrow's matches (with auto forward-search)
    3. Grade past results
    4. Scout specific player

Usage:
    $ python3 -m src.sports.tennis.scanner
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import os
try:
    import lightgbm as lgb
    _LGBM_AVAILABLE = True
except ImportError:
    _LGBM_AVAILABLE = False
import warnings
import unicodedata
import re
from datetime import datetime, timedelta

from src.core.odds_providers.prizepicks  import PrizePicksClient
from src.core.odds_providers.pickfinder  import PickFinderClient
from src.sports.tennis.config   import STAT_MAP, STAT_MAP_REVERSE, MODEL_QUALITY, ACTIVE_TARGETS
from src.sports.tennis.mappings import STAT_MAPPING
from src.sports.tennis.rankings import TennisRankings

warnings.filterwarnings('ignore')

# --- PATHS ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MODEL_DIR  = os.path.join(BASE_DIR, 'models', 'tennis')
DATA_FILE  = os.path.join(BASE_DIR, 'data',   'tennis', 'processed', 'training_dataset.csv')
PROJ_DIR   = os.path.join(BASE_DIR, 'data',   'tennis', 'projections')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output', 'tennis', 'scans')


os.makedirs(PROJ_DIR,   exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

# IOC 3-letter code → flag emoji (regional indicator letters A=🇦, Z=🇿)
def _ioc_to_flag(ioc: str) -> str:
    """Convert IOC/ISO 3-letter country code to flag emoji. Falls back to empty string."""
    _IOC_TO_ISO2 = {
        'AUS':'AU','USA':'US','ESP':'ES','SRB':'RS','RUS':'RU','GBR':'GB','FRA':'FR',
        'GER':'DE','ITA':'IT','CZE':'CZ','POL':'PL','ARG':'AR','BLR':'BY','SUI':'CH',
        'CAN':'CA','JPN':'JP','CHN':'CN','BEL':'BE','NED':'NL','DEN':'DK','NOR':'NO',
        'SWE':'SE','FIN':'FI','AUT':'AT','GRE':'GR','POR':'PT','ROU':'RO','BUL':'BG',
        'HUN':'HU','CRO':'HR','SLO':'SI','SVK':'SK','UKR':'UA','KAZ':'KZ','UZB':'UZ',
        'TUN':'TN','MAR':'MA','RSA':'ZA','EGY':'EG','BOL':'BO','CHI':'CL','COL':'CO',
        'ECU':'EC','MEX':'MX','BRA':'BR','PER':'PE','VEN':'VE','URU':'UY','PAR':'PY',
        'DOM':'DO','PUR':'PR','BAH':'BS','JAM':'JM','TRI':'TT','NZL':'NZ','KOR':'KR',
        'TPE':'TW','THA':'TH','IND':'IN','ISR':'IL','LBA':'LY','ALG':'DZ','SEN':'SN',
        'NGR':'NG','KEN':'KE','ETH':'ET','CMR':'CM','CIV':'CI','ZIM':'ZW','MDA':'MD',
        'LTU':'LT','LAT':'LV','EST':'EE','GEO':'GE','ARM':'AM','AZE':'AZ','MNE':'ME',
        'BIH':'BA','MKD':'MK','ALB':'AL','LUX':'LU','MLT':'MT','CYP':'CY','ISL':'IS',
        'IRL':'IE','MON':'MC','SMR':'SM','AND':'AD','LIE':'LI','SIN':'SG','INA':'ID',
        'PHI':'PH','MAS':'MY','VIE':'VN','PAK':'PK','SRI':'LK','BAN':'BD','NEP':'NP',
        'UAE':'AE','QAT':'QA','KUW':'KW','BRN':'BH','OMA':'OM','JOR':'JO','LIB':'LB',
        'IRQ':'IQ','IRN':'IR','ISR':'IL','ERI':'ER','DJI':'DJ','SOM':'SO',
    }
    if not ioc:
        return ''
    iso2 = _IOC_TO_ISO2.get(ioc.upper(), '')
    if not iso2 and len(ioc) == 2:
        iso2 = ioc.upper()
    if len(iso2) != 2:
        return ''
    return chr(0x1F1E6 + ord(iso2[0]) - ord('A')) + chr(0x1F1E6 + ord(iso2[1]) - ord('A'))


def normalize_name(name):
    if not name:
        return ""
    n = unicodedata.normalize('NFD', str(name))
    n = ''.join(c for c in n if unicodedata.category(c) != 'Mn')
    n = re.sub(r"[^a-zA-Z\s]", '', n)
    return ' '.join(n.lower().split())


def get_betting_indicator(proj, line):
    if line is None or line <= 0:
        return "⚪ NO LINE"
    diff = proj - line
    if diff > 0:
        return f"🟢 OVER  (+{diff:.2f})"
    return f"🔴 UNDER ({diff:.2f})"


def _map_pp_stat_to_target(pp_stat):
    """Map PrizePicks stat name to internal target (with flexible matching)."""
    if not pp_stat:
        return None
    target = STAT_MAPPING.get(pp_stat)
    if target:
        return target
    # Already a target code (e.g. PP returns 'total_games')
    if pp_stat in STAT_MAPPING.values():
        return pp_stat
    pp_lower = str(pp_stat).strip().lower()
    for key, val in STAT_MAPPING.items():
        if key.lower() == pp_lower:
            return val
    return None


def _target_display_name(target):
    """Convert internal target (e.g. total_games) to display name (e.g. Total Games)."""
    return STAT_MAP_REVERSE.get(target, target.replace('_', ' ').title())


# ---------------------------------------------------------------------------
# LOAD DATA & MODELS
# ---------------------------------------------------------------------------

PLAYER_CACHE_FILE = os.path.join(BASE_DIR, 'data', 'tennis', 'processed', 'player_cache.parquet')

def load_data():
    if not os.path.exists(DATA_FILE):
        print(f"❌  Training data not found: {DATA_FILE}")
        print("    Run builder.py → features.py first.")
        return None
    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['tourney_date'] = pd.to_datetime(df['tourney_date'], errors='coerce')
    df = df.sort_values(['player_name', 'tourney_date']).reset_index(drop=True)
    print(f"   ✅  Loaded history: {len(df):,} matches | {df['player_name'].nunique():,} players")
    return df


def load_player_cache():
    """Load pre-built player lookup from disk (fast path). Returns dict or None."""
    if not os.path.exists(PLAYER_CACHE_FILE):
        return None
    try:
        df = pd.read_parquet(PLAYER_CACHE_FILE)
        cache = df.to_dict('index')
        print(f"   ✅  Player cache loaded from disk ({len(cache)} players) — skipping full CSV load")
        return cache
    except Exception as e:
        print(f"   ⚠️  Cache read failed: {e}")
        return None


def save_player_cache(lookup: dict):
    """Persist player lookup to disk for fast future loads."""
    try:
        pd.DataFrame.from_dict(lookup, orient='index').to_parquet(PLAYER_CACHE_FILE)
        print(f"   💾  Player cache saved ({len(lookup)} players) → {PLAYER_CACHE_FILE}")
    except Exception as e:
        print(f"   ⚠️  Could not save player cache: {e}")


class _EnsembleModel:
    """60% XGBoost + 40% LightGBM blend."""
    def __init__(self, xgb_model, lgbm_booster):
        self.xgb  = xgb_model
        self.lgbm = lgbm_booster

    def predict(self, X):
        xgb_p  = self.xgb.predict(X)
        lgbm_p = self.lgbm.predict(X)
        return 0.60 * xgb_p + 0.40 * lgbm_p

    @property
    def feature_names_in_(self):
        return self.xgb.feature_names_in_


def load_models():
    models = {}
    ensemble_count = 0
    for target in ACTIVE_TARGETS:
        xgb_path  = os.path.join(MODEL_DIR, f'{target}_model.json')
        lgbm_path = os.path.join(MODEL_DIR, f'{target}_model_lgbm.txt')
        if not os.path.exists(xgb_path):
            print(f"   ⚠️  Model not found: {target}")
            continue
        xgb_m = xgb.XGBRegressor()
        xgb_m.load_model(xgb_path)
        if _LGBM_AVAILABLE and os.path.exists(lgbm_path):
            lgbm_b = lgb.Booster(model_file=lgbm_path)
            models[target] = _EnsembleModel(xgb_m, lgbm_b)
            ensemble_count += 1
        else:
            models[target] = xgb_m
    print(f"   ✅  Loaded {len(models)}/{len(ACTIVE_TARGETS)} models "
          f"({ensemble_count} ensemble, {len(models)-ensemble_count} XGB-only)")
    return models


# ---------------------------------------------------------------------------
# PRIZEPICKS FETCH WITH DATE FORWARD-SEARCH
# ---------------------------------------------------------------------------

def get_pp_lines(date_offset=0, max_days_forward=7):
    """
    Fetch PrizePicks tennis lines for the next available date.

    Strategy:
        1. Fetch the FULL board once (uses 30-min disk cache — no repeated API calls)
        2. Filter for tennis using case-insensitive league name match
        3. Search dates in the filtered results

    Returns:
        (pp_board DataFrame, actual_date_str)
    """
    pp_client    = PrizePicksClient(stat_map=STAT_MAP)
    initial_date = datetime.now() + timedelta(days=date_offset)

    print("...Fetching PrizePicks board (full, single request)...")

    # --- Fetch full board once — cache handles repeat calls ---
    full_board = pp_client.fetch_board(include_alts=True)  # include goblin/demon lines

    if full_board.empty:
        print("❌  PrizePicks board unavailable (rate limited or down).")
        print("    Wait 30 seconds and try again.")
        return pd.DataFrame(), None

    # --- Filter for tennis with case-insensitive match, standard + goblin only ---
    tennis_board = full_board[
        full_board['League'].str.lower().str.contains('tennis', na=False)
    ].copy()
    if 'OddsType' in tennis_board.columns:
        tennis_board = tennis_board[
            tennis_board['OddsType'].str.lower().isin(['standard', 'goblin', ''])
        ]

    if tennis_board.empty:
        # Show what leagues ARE available so user knows what's on the board
        available = full_board['League'].dropna().unique().tolist()
        print(f"   ⚠️  No tennis lines on PrizePicks right now.")
        print(f"   Available leagues: {available[:10]}")
        print(f"   Tennis lines are posted 1-2 days before matches.")
        return pd.DataFrame(), None

    print(f"   ✅  Found {len(tennis_board)} tennis lines for {tennis_board['Player'].nunique()} players")

    # --- Find lines for the target date (or nearest future date) ---
    tennis_board['Date'] = pd.to_datetime(tennis_board['Date'], errors='coerce')
    target_start = initial_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # Group by date, find closest date >= target
    available_dates = sorted(tennis_board['Date'].dropna().unique())
    chosen_date_ts  = None

    for d in available_dates:
        if pd.Timestamp(d) >= pd.Timestamp(target_start):
            chosen_date_ts = d
            break

    if chosen_date_ts is None:
        # All dates are in the past — just take the most recent
        if available_dates:
            chosen_date_ts = available_dates[-1]
        else:
            print("   ⚠️  Could not determine match date from PP lines.")
            chosen_date_str = initial_date.strftime('%Y-%m-%d')
            return tennis_board.reset_index(drop=True), chosen_date_str

    chosen_date_str = pd.Timestamp(chosen_date_ts).strftime('%Y-%m-%d')
    day_name        = pd.Timestamp(chosen_date_ts).strftime('%A')

    # Filter to just that date
    date_board = tennis_board[tennis_board['Date'].dt.strftime('%Y-%m-%d') == chosen_date_str]

    if date_board.empty:
        # PP lines don't have dates — return all tennis lines
        date_board = tennis_board
        chosen_date_str = initial_date.strftime('%Y-%m-%d')

    # Count unique markets (stats) in the board
    stats_in_board = date_board['Stat'].dropna().unique().tolist()
    print(f"   📅 Lines found for: {day_name}, {chosen_date_str} ({len(date_board)} lines, {date_board['Player'].nunique()} players)")
    if stats_in_board:
        print(f"   📊 Markets: {', '.join(str(s) for s in stats_in_board)}")
    return date_board.reset_index(drop=True), chosen_date_str


# ---------------------------------------------------------------------------
# FEATURE PREPARATION
# ---------------------------------------------------------------------------

def build_player_lookup(df_history):
    """
    Pre-build a dictionary for O(1) player lookups.
    Returns: {normalized_name: latest_row_series}
    """
    print("...Building player lookup table (this may take 5-10s)")
    # Sort by date so the last entry is the latest
    df_sorted = df_history.sort_values('tourney_date')
    
    # 1. Create normalized name column
    # Vectorized normalization is hard because of regex/unicode, 
    # but we can do it once for unique names only.
    unique_names = df_sorted['player_name'].unique()
    norm_map = {n: normalize_name(n) for n in unique_names}
    
    # 2. Group by normalized name and take the last row
    # We can't easily group by a mapped value without adding a column
    df_sorted['norm_name'] = df_sorted['player_name'].map(norm_map)
    
    # Drop duplicates keeping the last (latest)
    latest_rows = df_sorted.drop_duplicates(subset=['norm_name'], keep='last')
    
    # Convert to dictionary: norm_name -> row
    # set_index to norm_name, then to_dict('index')
    lookup = latest_rows.set_index('norm_name').to_dict('index')
    
    # Also add last-name lookups for partial matching (only if unique)
    # Be careful not to overwrite full match
    # Actually, let's just stick to full match first, logic for partial is tricky in a dict.
    # We can add a secondary lookup for last names.
    
    return lookup

# Removed get_player_latest_row (Replaced by dictionary lookup)


def build_feature_row(player_row, surface='Hard', opp_rank=50.0, player_rank=50.0,
                       is_best_of_5=0, round_ordinal=3, is_atp=1, days_rest=2,
                       opp_row=None):
    latest = player_row.to_dict()

    # Clean rank values
    if not player_rank or player_rank <= 0 or (isinstance(player_rank, float) and np.isnan(player_rank)):
        player_rank = 50.0
    if not opp_rank or opp_rank <= 0 or (isinstance(opp_rank, float) and np.isnan(opp_rank)):
        opp_rank = 50.0

    latest.update({
        'surface_hard':   1 if surface == 'Hard'   else 0,
        'surface_clay':   1 if surface == 'Clay'   else 0,
        'surface_grass':  1 if surface == 'Grass'  else 0,
        'surface_carpet': 1 if surface == 'Carpet' else 0,
        'is_best_of_5':   is_best_of_5,
        'round_ordinal':  round_ordinal,
        'is_atp':         is_atp,
        'player_rank':    player_rank,
        'opp_rank':       opp_rank,
        'rank_delta':     player_rank - opp_rank,
        'rank_ratio':     player_rank / (opp_rank + 1),
        'log_rank':       np.log1p(player_rank),
        'log_opp_rank':   np.log1p(opp_rank),
        'days_rest':      days_rest,
        'is_b2b':         1 if days_rest <= 1 else 0,
    })

    # ── Opponent rolling stats (from actual opponent's player cache row) ──
    # The model was trained with opp_{stat}_{window} features; seeding these
    # with real opponent data instead of zeros meaningfully improves accuracy
    # on aces, double_faults, games_won (all opponent-strength-dependent).
    if opp_row is not None:
        surf_lc = surface.lower()
        for stat in ['total_games', 'games_won', 'aces', 'double_faults', 'bp_won', 'bp_faced']:
            for w in ['L5', 'L20']:
                key = f'opp_{stat}_{w}'
                src = f'{stat}_{w}'
                latest[key] = float(opp_row.get(src, 0) or 0)
        for stat in ['aces', 'double_faults', 'total_games', 'games_won', 'bp_won']:
            key = f'opp_{stat}_{surf_lc}_L10'
            src = f'{stat}_{surf_lc}_L10'
            latest[key] = float(opp_row.get(src, 0) or 0)

    return pd.DataFrame([latest])


def predict(player_row, models, surface, opp_rank, player_rank,
            is_best_of_5, round_ordinal, is_atp, opp_row=None):
    """Run all models for one player. Returns dict of {target: prediction}."""
    feat_row = build_feature_row(
        player_row, surface=surface, opp_rank=opp_rank, player_rank=player_rank,
        is_best_of_5=is_best_of_5, round_ordinal=round_ordinal, is_atp=is_atp,
        opp_row=opp_row,
    )
    preds = {}
    for target, model in models.items():
        model_features = [f for f in model.feature_names_in_ if f in feat_row.columns]
        X = feat_row.reindex(columns=model_features, fill_value=0)
        try:
            preds[target] = float(model.predict(X)[0])
        except Exception:
            pass
    return preds


# ---------------------------------------------------------------------------
# SCAN ALL
# ---------------------------------------------------------------------------

def scan_all(df_history, models, rankings: TennisRankings, is_tomorrow=False, max_days_forward=7):
    offset       = 1 if is_tomorrow else 0
    pp_board, actual_date = get_pp_lines(date_offset=offset, max_days_forward=max_days_forward)

    if pp_board.empty or actual_date is None:
        try: input("\nPress Enter to continue...")
        except (EOFError, OSError): pass
        return

    scan_date_obj = datetime.strptime(actual_date, '%Y-%m-%d')
    print(f"\n📅 Scanning tennis for: {scan_date_obj.strftime('%A, %B %d, %Y')}")
    print(f"   {pp_board['Player'].nunique()} players | {len(pp_board)} total lines\n")

    # --- Extract tournament context from PrizePicks board if available ---
    # PP sometimes includes a league/tournament column
    tournament_name = ''
    if 'League' in pp_board.columns:
        leagues = pp_board['League'].dropna().unique()
        if len(leagues) > 0:
            tournament_name = str(leagues[0])

    surface      = rankings.get_surface(tournament_name)
    is_slam      = rankings.is_slam(tournament_name)
    round_ord    = 3   # default to R32 equivalent

    # Detect per-player surface from their latest match in training data
    # (PrizePicks only says 'TENNIS', never gives the actual tournament)
    def _player_surface(player_row):
        if player_row is not None and 'surface' in player_row.index:
            s = str(player_row.get('surface', '')).strip().title()
            if s in ('Hard', 'Clay', 'Grass', 'Carpet'):
                return s
        return surface  # fallback to global default

    if tournament_name:
        print(f"   🏆 Tournament: {tournament_name}")
    print(f"   🎾 Surface:    Per-player (from recent matches)")
    if is_slam:
        print(f"   📌 Grand Slam — men play best-of-5")

    # --- Build player-centric lines dict (like NBA: player -> {target: line}) ---
    norm_lines     = {}   # norm_name -> {target: line}
    display_names  = {}   # norm_name -> display name for output
    for _, pp_row in pp_board.iterrows():
        pp_name = pp_row.get('Player', '')
        pp_stat = pp_row.get('Stat',   '')
        line    = pp_row.get('Line')
        target  = _map_pp_stat_to_target(pp_stat)
        if not target or target not in models:
            continue
        if line is None or float(line) <= 0:
            continue
        norm = normalize_name(pp_name)
        display_names[norm] = pp_name
        norm_lines.setdefault(norm, {})[target] = float(line)

    # --- PickFinder Tennis enrichment ---
    # Provides hit rates (L5/L10), streak, and book consensus per player+stat
    pf_lookup = {}   # (norm_name, pp_stat_display) → enrichment dict
    try:
        pf_client = PickFinderClient()
        pf_df     = pf_client.fetch_board(sport='tennis')
        pf_mv     = pf_client.get_movement_summary(sport='tennis')

        if not pf_df.empty:
            # Prefer PrizePicks book rows; fall back to first occurrence per player+stat
            pp_rows  = pf_df[pf_df['book'] == 'prizepicks']
            all_rows = pf_df.drop_duplicates(subset=['player_name_normalized', 'stat'])
            pf_dedup = pd.concat([pp_rows, all_rows]).drop_duplicates(
                subset=['player_name_normalized', 'stat'], keep='first')

            for _, _row in pf_dedup.iterrows():
                _pf_norm = _row['player_name_normalized']
                _pf_stat = _row['stat']
                _mv_data = pf_mv.get((_pf_norm, _pf_stat), {})
                pf_lookup[(_pf_norm, _pf_stat)] = {
                    'hr_l5':     _row.get('hit_rate_l5',  -1),
                    'hr_l10':    _row.get('hit_rate_l10', -1),
                    'streak':    int(_row.get('streak', 0) or 0),
                    'avg_l10':   _row.get('avg_last10'),
                    'con_over':  float(_row.get('consensus_over_ip',  0) or 0),
                    'con_under': float(_row.get('consensus_under_ip', 0) or 0),
                    'net_move':  _mv_data.get('net', 0),
                }
            moved = sum(1 for v in pf_lookup.values() if v['net_move'] != 0)
            print(f"   PickFinder: {len(pf_lookup)} tennis props  ({moved} with movement)")
    except Exception as _pf_err:
        print(f"   PickFinder unavailable: {_pf_err}")

    # --- Generate predictions (player-centric, like NBA: one predict per player, all markets) ---
    print("🚀 Generating Predictions...")
    best_bets       = []
    all_projections = []
    skipped         = []

    # --- Pre-build lookup table for speed (use disk cache if available) ---
    player_lookup = load_player_cache()
    if player_lookup is None:
        player_lookup = build_player_lookup(df_history)
        save_player_cache(player_lookup)

    # --- Build opponent map from PrizePicks board ---
    # PP lists both players in a matchup — we pair them by matching opponent
    # fields if available, else infer from same-slate players alphabetically.
    # Key: norm_name → best-guess opponent norm_name
    opp_map = {}
    if 'Opponent' in pp_board.columns:
        for _, pp_row in pp_board.iterrows():
            pn  = normalize_name(pp_row.get('Player', ''))
            opp = normalize_name(pp_row.get('Opponent', ''))
            if pn and opp:
                opp_map[pn] = opp
    # Fallback: PrizePicks sometimes doesn't expose the opponent column but
    # the slate is small — pair players by index (1st vs 2nd, 3rd vs 4th…)
    if not opp_map:
        all_norm = list(norm_lines.keys())
        for i in range(0, len(all_norm) - 1, 2):
            opp_map[all_norm[i]]   = all_norm[i + 1]
            opp_map[all_norm[i+1]] = all_norm[i]

    def _lookup_player(norm):
        data = player_lookup.get(norm)
        if data is None:
            last = norm.split()[-1] if norm else ''
            if len(last) > 3:
                for k in player_lookup:
                    if k.endswith(' ' + last) or k == last:
                        return player_lookup[k]
        return data

    for norm_name, lines_for_player in norm_lines.items():
        pp_name = display_names.get(norm_name, norm_name)

        player_data = _lookup_player(norm_name)
        if player_data is None:
            skipped.append(pp_name)
            continue

        player_row = pd.Series(player_data)

        # Rankings from Sackmann GitHub
        player_rank    = rankings.get_rank(pp_name)
        player_country = rankings.get_country(pp_name)
        player_flag    = _ioc_to_flag(player_country)
        tour           = rankings.get_tour(pp_name)
        is_atp         = 1 if tour == 'atp' else 0
        bo5         = 1 if (is_slam and is_atp) else 0

        # ── Opponent rank lookup ──────────────────────────────────────────
        # Use actual opponent from PP board; fall back to rank-50 placeholder
        opp_norm    = opp_map.get(norm_name)
        opp_pp_name = display_names.get(opp_norm, opp_norm or '')
        opp_rank    = rankings.get_rank(opp_pp_name) if opp_pp_name else 50.0
        if opp_rank <= 0 or (isinstance(opp_rank, float) and opp_rank != opp_rank):
            opp_rank = 50.0

        # Also factor opponent's surface-specific rolling stats into projection
        opp_data = _lookup_player(opp_norm) if opp_norm else None
        opp_row  = pd.Series(opp_data) if opp_data is not None else None

        preds = predict(player_row, models,
                        surface=_player_surface(player_row), opp_rank=opp_rank,
                        player_rank=player_rank, is_best_of_5=bo5,
                        round_ordinal=round_ord, is_atp=is_atp,
                        opp_row=opp_row)

        player_surf = _player_surface(player_row)

        # For each market PrizePicks has for this player, create a bet
        for target, line in lines_for_player.items():
            proj = preds.get(target)
            if proj is None:
                continue

            rec       = get_betting_indicator(proj, line)
            edge      = proj - line
            pct_edge  = (edge / line) * 100
            tier_info = MODEL_QUALITY.get(target, {})

            # PickFinder lookup: convert internal target → PP display name for key
            _pp_stat_disp = STAT_MAP_REVERSE.get(target, target)
            _pf_data      = pf_lookup.get((norm_name, _pp_stat_disp), {})
            if not _pf_data:   # fallback: try raw target string
                _pf_data = pf_lookup.get((norm_name, target), {})

            all_projections.append({
                'REC':     rec,
                'NAME':    pp_name,
                'TARGET':  target,
                'SURFACE': player_surf,
                'AI':      round(proj, 2),
                'PP':      round(float(line), 2),
                'EDGE':    round(edge, 2),
                'RANK':    int(player_rank) if player_rank != 50.0 else '?',
                'PF_HR10': _pf_data.get('hr_l10', -1),
                'PF_STRK': int(_pf_data.get('streak', 0) or 0),
            })

            best_bets.append({
                'REC':           rec,
                'NAME':          pp_name,
                'FLAG':          player_flag,
                'OPPONENT':      opp_pp_name or '—',
                'TARGET':        target,
                'TARGET_DISPLAY': _target_display_name(target),
                'SURFACE':       player_surf,
                'AI':            round(proj, 2),
                'PP':            round(float(line), 2),
                'EDGE':          edge,
                'PCT_EDGE':      pct_edge,
                'TIER_KEY':      tier_info.get('tier', 'UNKNOWN'),
                'TIER':          tier_info.get('emoji', '~') + ' ' + tier_info.get('tier', 'UNKNOWN'),
                'THRESHOLD':     tier_info.get('threshold', 2.5),
                'PF_HR5':        float(_pf_data.get('hr_l5',  -1)),
                'PF_HR10':       float(_pf_data.get('hr_l10', -1)),
                'PF_STRK':       int(_pf_data.get('streak', 0) or 0),
                'PF_CON_O':      float(_pf_data.get('con_over',  0) or 0),
                'PF_CON_U':      float(_pf_data.get('con_under', 0) or 0),
                'PF_NET_MOV':    int(_pf_data.get('net_move', 0) or 0),
            })

    # --- Warn about missing players ---
    if skipped:
        unique_skipped = list(set(skipped))
        print(f"\n   ⚠️  {len(unique_skipped)} player(s) not in training history:")
        for n in unique_skipped[:5]:
            print(f"      - {n}")
        if len(unique_skipped) > 5:
            print(f"      ... and {len(unique_skipped)-5} more")

    if not best_bets:
        print("\n⚠️  No predictions generated.")
        try: input("\nPress Enter to continue...")
        except (EOFError, OSError): pass
        return

    # --- Deduplicate ---
    seen, deduped = set(), []
    for bet in best_bets:
        key = (bet['NAME'], bet['TARGET'], bet['PP'])
        if key not in seen:
            seen.add(key)
            deduped.append(bet)

    removed = len(best_bets) - len(deduped)
    if removed:
        print(f"   🧹 Removed {removed} duplicate entries")

    # --- Sort: tier first, then edge % ---
    tier_order = {'ELITE': 0, 'STRONG': 1, 'DECENT': 2, 'RISKY': 3}
    deduped.sort(key=lambda x: (tier_order.get(x['TIER_KEY'], 9), -abs(x['PCT_EDGE'])))

    overs_raw  = [b for b in deduped if b['EDGE'] > 0]
    unders_raw = [b for b in deduped if b['EDGE'] < 0]

    # Ensure market variety: take best per market first, then fill to 10 (like NBA shows diverse stats)
    def _diverse_top(bets, n=10):
        if len(bets) <= n:
            return bets[:n]
        by_market = {}
        for b in bets:
            t = b['TARGET']
            if t not in by_market or abs(b['PCT_EDGE']) > abs(by_market[t]['PCT_EDGE']):
                by_market[t] = b
        result = list(by_market.values())
        seen = {(x['NAME'], x['TARGET'], x['PP']) for x in result}
        for b in bets:
            key = (b['NAME'], b['TARGET'], b['PP'])
            if key not in seen and len(result) < n:
                result.append(b)
                seen.add(key)
        result.sort(key=lambda x: (tier_order.get(x['TIER_KEY'], 9), -abs(x['PCT_EDGE'])))
        return result[:n]

    top_overs  = _diverse_top(overs_raw)
    top_unders = _diverse_top(unders_raw)

    # Determine if PickFinder hit rate data is available
    _has_pfhr = any(b.get('PF_HR10', -1) >= 0 for b in deduped)

    def _fmt_bet_row(b):
        is_over = b['EDGE'] > 0
        mkt     = b.get('TARGET_DISPLAY', _target_display_name(b['TARGET']))
        base    = (f" {b['TIER']:<12} | {b['NAME'][:20]:<20} | {mkt:<18} | "
                   f"{b['AI']:>6.2f} vs {b['PP']:>6.2f} | {b['PCT_EDGE']:>6.1f}%")
        if _has_pfhr:
            pf_hr10 = b.get('PF_HR10', -1)
            pf_strk = b.get('PF_STRK', 0) or 0
            if pf_hr10 >= 0:
                aligned = pf_hr10 if is_over else (100 - pf_hr10)
                phr_s   = f"{int(aligned)}%"
            else:
                phr_s   = " --"
            strk_s = f"{pf_strk:+d}" if pf_strk != 0 else "  0"
            base += f" | {phr_s:>4} {strk_s:>4}"
        return base

    _sep_w = 100 if _has_pfhr else 86

    # Table format — match NBA scanner (see nba/scanner.py lines 430-441)
    print("\n🔥 TOP 10 OVERS (Highest Value)")
    print()
    hdr = f" {'TIER':<12} | {'PLAYER':<20} | {'MARKET':<18} | {'AI vs PP':<15} | {'EDGE %':<8}"
    if _has_pfhr:
        hdr += " |  PHR  STK"
    print(hdr)
    print("-" * _sep_w)
    for b in top_overs:
        print(_fmt_bet_row(b))

    print("\n❄️ TOP 10 UNDERS (Lowest Value)")
    print()
    print(hdr)
    print("-" * _sep_w)
    for b in top_unders:
        print(_fmt_bet_row(b))

    if _has_pfhr:
        print()
        print("   PHR = PickFinder hit rate L10 (direction-aligned) | STK = over/under streak")

    # --- Save ---
    save_path = os.path.join(PROJ_DIR, f"scan_{actual_date}.csv")
    pd.DataFrame(all_projections).to_csv(save_path, index=False)
    print(f"\n✅  Full analysis ({len(all_projections)} rows) saved to {save_path}")

    # Also save rich best_bets to OUTPUT_DIR for the web app
    bets_path = os.path.join(OUTPUT_DIR, f"scan_{actual_date}.csv")
    pd.DataFrame(deduped).to_csv(bets_path, index=False)
    print(f"✅  Best bets ({len(deduped)} rows) saved to {bets_path}")

    try: input("\nPress Enter to continue...")
    except (EOFError, OSError): pass


# ---------------------------------------------------------------------------
# SCOUT SPECIFIC PLAYER
# ---------------------------------------------------------------------------

def scout_player(df_history, models, rankings: TennisRankings):
    print("\n🔎 --- TENNIS PLAYER SCOUT ---")

    d_choice = input("Scan date (1=Today, 2=Tomorrow): ").strip()
    offset   = 1 if d_choice == '2' else 0

    pp_board, actual_date = get_pp_lines(date_offset=offset, max_days_forward=7)

    if actual_date is None:
        print("❌  No tennis lines found.")
        return

    scan_date_obj = datetime.strptime(actual_date, '%Y-%m-%d')
    print(f"\n📅 Scouting for: {scan_date_obj.strftime('%A, %B %d, %Y')}")

    # Derive surface from PP board tournament
    tournament_name = ''
    if not pp_board.empty and 'League' in pp_board.columns:
        leagues = pp_board['League'].dropna().unique()
        if len(leagues) > 0:
            tournament_name = str(leagues[0])

    surface  = rankings.get_surface(tournament_name)
    is_slam  = rankings.is_slam(tournament_name)

    # Build PP line lookup: normalized_name → {target: line} (all markets per player)
    pp_lines_lookup = {}
    if not pp_board.empty:
        for _, row in pp_board.iterrows():
            norm   = normalize_name(row.get('Player', ''))
            target = _map_pp_stat_to_target(row.get('Stat', ''))
            line   = row.get('Line')
            if norm and target and line:
                pp_lines_lookup.setdefault(norm, {})[target] = float(line)

    # PickFinder scout data (uses 30-min cache — no extra network call if scan already ran)
    pf_scout = {}   # (norm_name, pp_stat_display) → enrichment dict
    try:
        _pfc = PickFinderClient()
        _pf_scout_df = _pfc.fetch_board(sport='tennis')
        if not _pf_scout_df.empty:
            _pp_rows  = _pf_scout_df[_pf_scout_df['book'] == 'prizepicks']
            _all_rows = _pf_scout_df.drop_duplicates(subset=['player_name_normalized', 'stat'])
            _pf_dd    = pd.concat([_pp_rows, _all_rows]).drop_duplicates(
                subset=['player_name_normalized', 'stat'], keep='first')
            for _, _r in _pf_dd.iterrows():
                pf_scout[(_r['player_name_normalized'], _r['stat'])] = {
                    'hr_l5':  _r.get('hit_rate_l5',  -1),
                    'hr_l10': _r.get('hit_rate_l10', -1),
                    'streak': int(_r.get('streak', 0) or 0),
                    'avg_l10': _r.get('avg_last10'),
                }
    except Exception:
        pass

    scouting = True
    
    # Pre-build lookup for scouting too (or pass it in?)
    # Scouting is interactive, so building it once is fine, or just searching raw DF.
    # Searching raw DF for scouting is O(k) but we do it once per user input.
    # The slowdown complaint was about "Generating Predictions" (batch scan).
    # We can leave scouting as is or optimize it. Scouting searches by substring usually.
    
    while scouting:
        print("\n(Type '0' to return to menu)")
        query = input("Enter player name: ").strip().lower()
        if query == '0':
            break
        if not query:
            continue

        # Search history
        mask       = df_history['player_name'].apply(lambda n: query in normalize_name(n))
        matches_df = df_history[mask]

        if matches_df.empty:
            print(f"❌  No player found matching '{query}'.")
            continue

        unique = matches_df['player_name'].drop_duplicates().tolist()
        if len(unique) > 1:
            print("\nMultiple matches:")
            for i, name in enumerate(unique[:10], 1):
                print(f"  {i}. {name}")
            try:
                chosen_name = unique[int(input("Select number: ")) - 1]
            except (ValueError, IndexError):
                print("❌  Invalid.")
                continue
        else:
            chosen_name = unique[0]

        player_row  = df_history[df_history['player_name'] == chosen_name].iloc[-1]
        player_rank = rankings.get_rank(chosen_name)
        tour        = rankings.get_tour(chosen_name)
        is_atp      = 1 if tour == 'atp' else 0
        bo5         = 1 if (is_slam and is_atp) else 0
        pp_lines    = pp_lines_lookup.get(normalize_name(chosen_name), {})
        # Detect surface from player's recent match
        player_surf = surface  # default
        if 'surface' in player_row.index:
            s = str(player_row.get('surface', '')).strip().title()
            if s in ('Hard', 'Clay', 'Grass', 'Carpet'):
                player_surf = s

        scout_norm = normalize_name(chosen_name)
        print(f"\n{'='*76}")
        print(f"📊 SCOUTING: {chosen_name}  ({tour.upper()})")
        print(f"   Date:       {actual_date}")
        print(f"   Surface:    {player_surf}")
        print(f"   World Rank: #{int(player_rank) if player_rank != 50.0 else 'Unknown'}")
        if tournament_name:
            print(f"   Tournament: {tournament_name}")
        print(f"{'='*76}")
        print(f"{'TIER':<6} | {'MARKET':<22} | {'AI PROJ':>8} | {'PP LINE':>8} | {'HR10':>5} | {'STK':>4} | CALL")
        print("-" * 76)

        preds = predict(player_row, models, surface=player_surf, opp_rank=50.0,
                        player_rank=player_rank, is_best_of_5=bo5,
                        round_ordinal=3, is_atp=is_atp)

        for target, proj in preds.items():
            tier_emoji  = MODEL_QUALITY.get(target, {}).get('emoji', '?')
            line        = pp_lines.get(target)
            rec         = get_betting_indicator(proj, line)
            line_str    = f"{line:.2f}" if line else "  N/A"
            mkt         = _target_display_name(target)
            _pp_disp    = STAT_MAP_REVERSE.get(target, target)
            _pf_s       = pf_scout.get((scout_norm, _pp_disp), {})
            hr10        = float(_pf_s.get('hr_l10', -1))
            strk        = int(_pf_s.get('streak', 0) or 0)
            hr10_s      = f"{int(hr10)}%" if hr10 >= 0 else "  --"
            strk_s      = f"{strk:+d}" if strk != 0 else "   0"
            print(f"{tier_emoji:<6} | {mkt:<22} | {proj:>8.2f} | {line_str:>8} | {hr10_s:>5} | {strk_s:>4} | {rec}")

        print(f"{'='*76}")
        print("   HR10 = PickFinder hit rate last 10 games vs this line | STK = streak")

        if input("\nScout another player? (y/n): ").strip().lower() != 'y':
            scouting = False


# ---------------------------------------------------------------------------
# GRADE RESULTS
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# MAIN MENU
# ---------------------------------------------------------------------------

def main():
    print("...Initializing Tennis Scanner")
    df_history = load_data()
    models     = load_models()

    if df_history is None or not models:
        print("❌  Setup failed. Run builder → features → train first.")
        return

    # Load rankings once at startup
    print("...Loading Rankings")
    rankings = TennisRankings()
    rankings.load()

    while True:
        print("\n" + "="*35)
        print("   🎾 TENNIS AI SCANNER")
        print("="*35)
        print("1. 🚀 Scan TODAY's Matches (Current day only)")
        print("2. 🔮 Scan NEXT POSSIBLE Match")
        print("3. 🔎 Scout Specific Player")
        print("0. 🚪 Exit")

        choice = input("\nSelect: ").strip()

        if   choice == '1': scan_all(df_history, models, rankings, is_tomorrow=False, max_days_forward=0)
        elif choice == '2': scan_all(df_history, models, rankings, is_tomorrow=True, max_days_forward=7)
        elif choice == '3': scout_player(df_history, models, rankings)
        elif choice == '0': break
        else:
            print("❌  Invalid selection.")


if __name__ == "__main__":
    main()