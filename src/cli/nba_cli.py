"""
NBA CLI - Main Entry Point for the NBA EV Bot

Provides the interactive menu system connecting all tools:
    1. Super Scanner (Math + AI correlated plays)
    2. Odds Scanner (FanDuel vs PrizePicks arbitrage)
    3. NBA AI Scanner (Standalone AI predictions)

All NBA-specific configuration lives in src/sports/nba/.
Shared tools (FanDuel, PrizePicks, Analyzer) live in src/core/.
"""

import os
import sys
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

from src.core.odds_providers.prizepicks import PrizePicksClient
from src.core.odds_providers.fanduel    import FanDuelClient
from src.core.analyzers.analyzer        import PropsAnalyzer
from src.sports.nba.config import (
    ODDS_API_KEY, SPORT_MAP, REGIONS, ODDS_FORMAT, STAT_MAP,
    MODEL_QUALITY, ACTIVE_TARGETS, print_mode_info
)
from src.sports.nba.train import LOG_TRANSFORM_TARGETS
from src.sports.nba.scanner import LOG_CALIBRATION
from src.sports.nba.mappings import PP_NORMALIZATION_MAP, STAT_MAPPING, VOLATILITY_MAP
import src.sports.nba.scanner as ai_scanner_module
from src.sports.nba.scanner import (
    load_data, load_models, get_games, prepare_features, normalize_name,
    refresh_injuries, get_player_status, auto_refresh_data, get_all_projections
)

# Module-level cache: data and models are loaded once per session.
_SESSION_DF      = None
_SESSION_MODELS  = None
_SESSION_LOADED  = False

# Defensive matchup cache: keyed by ('ranks', pos_filter) → {avgs, ranks, lg_avg, n}
# 'raw_df' key stores the lazily-loaded training DataFrame when _SESSION_DF is None.
_DEF_RANK_CACHE: dict = {}

warnings.filterwarnings('ignore')

# Project root is 3 levels up from src/cli/nba_cli.py
_BASE      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(_BASE, 'output', 'nba', 'scans')


def _ensure_session_data():
    """Load data and models once; reuse for every scanner call in the session."""
    global _SESSION_DF, _SESSION_MODELS, _SESSION_LOADED
    if _SESSION_LOADED:
        return _SESSION_DF, _SESSION_MODELS
    refresh_injuries()
    df = load_data()
    if df is not None:
        df = auto_refresh_data(df)
    models = load_models()
    _SESSION_DF     = df
    _SESSION_MODELS = models
    _SESSION_LOADED = True
    return df, models


# --- HELPER: RUN AI PREDICTIONS ---
def get_ai_predictions():
    """
    Thin wrapper around the canonical get_all_projections() engine.

    Fetches projections for today's and (if different) tomorrow's slate,
    merges them, and returns a DataFrame with columns: Player, Stat, AI_Proj.

    All post-processing (DAYS_REST, fresh pace/opp stats, playoff factor,
    availability scale_factor, correlation constraints) is handled inside
    get_all_projections(), so results here are guaranteed to match the
    AI Scanner and Player Scout output exactly.
    """
    df_history, models = _ensure_session_data()

    if df_history is None or not models:
        return pd.DataFrame()

    today_str = datetime.now().strftime('%Y-%m-%d')

    # Today's (or next available) slate
    first_df = get_all_projections(df_history, models, date_offset=0)

    # Determine the date that was actually used so we can skip a redundant call
    _, first_date = get_games(date_offset=0, require_scheduled=True)

    if first_date and first_date != today_str:
        # get_all_projections already jumped to a future date; offset=1 would
        # resolve to the same slate — no second call needed.
        return first_df

    # Tomorrow's slate (only if it's a different date)
    second_df = get_all_projections(df_history, models, date_offset=1)
    _, second_date = get_games(date_offset=1, require_scheduled=True)

    if second_date and second_date != first_date and not second_df.empty:
        combined = pd.concat([first_df, second_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['Player', 'Stat'], keep='first')
        return combined

    return first_df


# --- TOOL 1: SUPER SCANNER ---
def run_correlated_scanner():
    print("")
    print("\n" + "="*50)
    print("   SUPER SCANNER (Math + AI Correlation)")
    print("="*50)

    # 1. Fetch market odds
    print("\n--- 1. Fetching Market Odds ---")
    try:
        import time

        # --- PrizePicks: retry up to 3 times (403s are usually temporary rate limits) ---
        pp    = PrizePicksClient(stat_map=STAT_MAP)
        pp_df = pd.DataFrame()
        for attempt in range(1, 4):
            pp_df = pp.fetch_board(league_filter='NBA', include_alts=True)
            if not pp_df.empty:
                break
            if attempt < 3:
                print(f"   PrizePicks attempt {attempt}/3 failed. Retrying in 10s...")
                time.sleep(10)

        if pp_df.empty:
            print("PrizePicks unavailable after 3 attempts.")
            input("Press Enter...")
            return

        # --- Preprocessing: 1H Namespacing ---
        # If the row is from NBA1H, prefix the stat so mappings.py can find it as '1H Points' etc.
        def _namespace_stat(row):
            stat = str(row['Stat'])
            league = str(row.get('League', '')).upper()
            if league == 'NBA1H' and not stat.startswith('1H '):
                return f"1H {stat}"
            return stat

        pp_df['Stat'] = pp_df.apply(_namespace_stat, axis=1)
        pp_df['Stat'] = pp_df['Stat'].replace(PP_NORMALIZATION_MAP)

        # --- FanDuel ---
        fd    = FanDuelClient(
            api_key=ODDS_API_KEY, sport_map=SPORT_MAP,
            regions=REGIONS, odds_format=ODDS_FORMAT, stat_map=STAT_MAP
        )
        # Determine the active slate date (handles late-night rollover)
        _, target_date = get_games(date_offset=0, require_scheduled=True)
        print(f"   Active slate: {target_date}")
        fd_df = fd.get_all_odds(target_date=target_date)

        if fd_df.empty:
            print(f"FanDuel odds unavailable for {target_date}.")
            input("Press Enter...")
            return

        analyzer  = PropsAnalyzer(pp_df, fd_df, league='NBA')
        math_bets = analyzer.calculate_edges()

        if math_bets.empty:
            print("No math-based edges found.")
            input("Press Enter...")
            return

        print(f"Found {len(math_bets)} math-based plays.")
        unique_stats = math_bets['Stat'].unique()
        print(f"   Markets: {', '.join(unique_stats)}")

    except Exception as e:
        print(f"Error in Odds Scanner: {e}")
        return

    # 2. AI Projections
    try:
        ai_df = get_ai_predictions()
        if ai_df.empty:
            print("Could not generate AI projections.")
            return
    except Exception as e:
        print(f"Error in AI Scanner: {e}")
        return

    # 3. Correlate
    print("\n--- 3. Correlating Results ---")
    math_bets['Stat']      = math_bets['Stat'].map(STAT_MAPPING).fillna(math_bets['Stat'])
    math_bets['CleanName'] = math_bets['Player'].apply(normalize_name)
    ai_df['CleanName']     = ai_df['Player'].apply(normalize_name)

    merged = pd.merge(math_bets, ai_df, on=['CleanName', 'Stat'], how='inner')
    
    before = len(merged)
    merged = merged.drop_duplicates(
        subset=['CleanName', 'Stat', 'Line', 'Side'],
        keep='first'
    )
    if before > len(merged):
        print(f"   Removed {before - len(merged)} duplicate entries")

    correlated_plays = []

    for _, row in merged.iterrows():
        math_side = row['Side']
        line      = row['Line']
        ai_proj   = row['AI_Proj']
        win_pct   = row['Implied_Win_%']

        ai_diff_raw = abs(ai_proj - line)
        ai_edge_pct = min((ai_diff_raw / line) * 100, 25) if line != 0 else 0

        ai_side = "Over" if ai_proj > line else "Under"
        if math_side == ai_side:
            math_rank    = max(0, min(10, (win_pct - 51) / 5 * 10))
            ai_rank      = max(0, min(10, (ai_edge_pct / 20) * 10))
            stat_weight  = VOLATILITY_MAP.get(row['Stat'], 1.0)
            combined_score = ((math_rank * 0.5) + (ai_rank * 0.5)) * 10 * stat_weight

            tier_info  = MODEL_QUALITY.get(row['Stat'], {})
            tier_text  = tier_info.get('tier', '-')

            correlated_plays.append({
                'Tier': tier_text, 'Player': row['Player_x'], 'Stat': row['Stat'],
                'Line': line, 'Side': math_side, 'Win%': win_pct,
                'AI_Proj': ai_proj, 'Score': round(combined_score, 1),
                'FD_Line': row.get('FD_Line', line),
                'Line_Diff': row.get('Line_Diff', 0.0),
                'OddsType': str(row.get('OddsType', 'standard') or 'standard').lower(),
            })

    # 4. Display results
    if not correlated_plays:
        print("No correlated plays found.")
    else:
        import unicodedata

        def vw(s):
            """Visual (terminal) width — wide chars like ⭐ count as 2."""
            return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in str(s))

        def pad(s, width, align='left'):
            """Pad to visual width so emoji-containing cells stay aligned."""
            s = str(s)
            spaces = max(0, width - vw(s))
            return (' ' * spaces + s) if align == 'right' else (s + ' ' * spaces)

        # Column widths
        W_RANK=3; W_TIER=10; W_PLAYER=24; W_STAT=7; W_LINE=6
        W_SIDE=8; W_WIN=7; W_AI=7; W_SCORE=6; W_LDIFF=5
        SEP = " │ "
        total_w = W_RANK+W_TIER+W_PLAYER+W_STAT+W_LINE+W_SIDE+W_WIN+W_AI+W_SCORE+W_LDIFF + len(SEP)*9

        def print_table(df, title, limit=None):
            """Print a formatted table of correlated plays."""
            rows = df.head(limit) if limit else df
            if rows.empty:
                return
            print(f"\n{'─'*total_w}")
            print(f"  {title}")
            print(f"{'─'*total_w}")
            header = (
                pad('#',       W_RANK,  'right') + SEP +
                pad('TIER',    W_TIER)            + SEP +
                pad('PLAYER',  W_PLAYER)           + SEP +
                pad('STAT',    W_STAT)             + SEP +
                pad('LINE',    W_LINE,  'right')   + SEP +
                pad('SIDE',    W_SIDE)             + SEP +
                pad('WIN %',   W_WIN,   'right')   + SEP +
                pad('AI PROJ', W_AI,    'right')   + SEP +
                pad('SCORE',   W_SCORE, 'right')   + SEP +
                pad('ΔLINE',   W_LDIFF, 'right')
            )
            print(header)
            print(f"{'─'*total_w}")
            for i, row in rows.reset_index(drop=True).iterrows():
                tier   = str(row['Tier'])
                player = str(row['Player'])
                while vw(player) > W_PLAYER:
                    player = player[:-1]
                side      = str(row['Side'])
                side_cell = f"{'▲' if side == 'Over' else '▼'} {side}"
                ld = float(row.get('Line_Diff', 0))
                ld_cell = f"{ld:+.1f}" if ld != 0 else "  ="
                if abs(ld) >= 2.0:
                    ld_cell = f"⚡{ld_cell}"
                print(
                    pad(str(i+1),                    W_RANK,  'right') + SEP +
                    pad(tier,                         W_TIER)           + SEP +
                    pad(player,                       W_PLAYER)         + SEP +
                    pad(str(row['Stat']).replace('_1H', ' 1H').replace('FPTS', 'FSCR'), W_STAT) + SEP +
                    pad(f"{float(row['Line']):.1f}",  W_LINE,  'right') + SEP +
                    pad(side_cell,                    W_SIDE)           + SEP +
                    pad(f"{float(row['Win%']):.2f}%", W_WIN,   'right') + SEP +
                    pad(f"{float(row['AI_Proj']):.2f}",W_AI,   'right') + SEP +
                    pad(f"{float(row['Score']):.1f}", W_SCORE, 'right') + SEP +
                    pad(ld_cell,                      W_LDIFF, 'right')
                )
            print(f"{'─'*total_w}")

        # ── Build the full sorted frame ────────────────────────────────────
        final_df = pd.DataFrame(correlated_plays)
        final_df = final_df.sort_values(by='Score', ascending=False)
        final_df = final_df.drop_duplicates(subset=['Player', 'Stat', 'Line', 'Side'], keep='first')

        if 'OddsType' not in final_df.columns:
            final_df['OddsType'] = 'standard'

        std_df = final_df[final_df['OddsType'].isin(['standard', ''])]
        gob_df = final_df[final_df['OddsType'] == 'goblin']

        # ── Standard plays: top 30 ─────────────────────────────────────────
        print_table(std_df, "TOP CORRELATED PLAYS  --  STANDARD LINES  (Math + AI Confidence)", limit=30)

        # ── Goblin plays section ───────────────────────────────────────────
        if not gob_df.empty:
            print_table(gob_df, "GOBLIN PLAYS  --  Easier Lines, Lower Payout  (Math + AI Confidence)", limit=20)

        # ── Bonus sections: best play(s) for every market NOT in the top 30 ─
        top_stats  = set(std_df.head(30)['Stat'].unique())
        all_stats  = set(std_df['Stat'].unique())
        missing_stats = all_stats - top_stats

        # Friendly display names for stat codes
        STAT_LABELS = {
            'PTS': 'Points', 'REB': 'Rebounds', 'AST': 'Assists',
            'PRA': 'Pts+Rebs+Asts', 'PR': 'Pts+Rebs', 'PA': 'Pts+Asts',
            'RA': 'Rebs+Asts', 'FG3M': '3-Pt Made',
            'BLK': 'Blocks', 'STL': 'Steals', 'SB': 'Blks+Stls',
            'TOV': 'Turnovers', 'FGM': 'FG Made', 'FGA': 'FG Attempted',
            'FTM': 'Free Throws Made', 'FTA': 'Free Throws Attempted',
        }

        if missing_stats:
            print(f"\n  BEST PLAYS BY MARKET  --  standard markets not in top 30")
            for stat in sorted(missing_stats):
                stat_df = std_df[std_df['Stat'] == stat]
                if stat_df.empty:
                    continue
                label = STAT_LABELS.get(stat, stat).replace('_1H', ' 1H').replace('FPTS', 'FSCR')
                print_table(stat_df, f"  {label} ({stat.replace('_1H', ' 1H').replace('FPTS', 'FSCR')})  —  Top 3", limit=3)

        # ── Goblin AI section — AI projection vs goblin lines (no FD needed) ──
        # Goblin lines rarely match FD lines, so we evaluate them by AI edge alone.
        if not pp_df.empty and 'OddsType' in pp_df.columns:
            gob_pp = pp_df[pp_df['OddsType'] == 'goblin'].copy()
            if not gob_pp.empty and not ai_df.empty:
                gob_pp['CleanName'] = gob_pp['Player'].apply(normalize_name)
                gob_pp['Stat'] = gob_pp['Stat'].map(STAT_MAPPING).fillna(gob_pp['Stat'])
                gob_merged = pd.merge(gob_pp, ai_df, on=['CleanName', 'Stat'], how='inner')
                goblin_plays = []
                for _, row in gob_merged.iterrows():
                    line    = float(row['Line'])
                    ai_proj = float(row['AI_Proj'])
                    if line <= 0:
                        continue
                    ai_edge_pct = min((abs(ai_proj - line) / line) * 100, 25)
                    ai_side     = 'Over' if ai_proj > line else 'Under'
                    tier_info   = MODEL_QUALITY.get(row['Stat'], {})
                    goblin_plays.append({
                        'Tier':     tier_info.get('tier', '-'),
                        'Player':   row['Player_x'] if 'Player_x' in row else row['Player'],
                        'Stat':     row['Stat'],
                        'Line':     line,
                        'Side':     ai_side,
                        'Win%':     50.0 + ai_edge_pct,
                        'AI_Proj':  ai_proj,
                        'Score':    round(ai_edge_pct * 4, 1),
                        'FD_Line':  line,
                        'Line_Diff': 0.0,
                        'OddsType': 'goblin',
                    })
                if goblin_plays:
                    gob_ai_df = pd.DataFrame(goblin_plays).sort_values('Score', ascending=False)
                    gob_ai_df = gob_ai_df[gob_ai_df['Score'] >= 20]
                    if not gob_ai_df.empty:
                        print_table(gob_ai_df, "GOBLIN PLAYS  --  AI Projection vs Easier Lines", limit=20)

        # ── Save ───────────────────────────────────────────────────────────
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = os.path.join(OUTPUT_DIR, 'correlated_plays.csv')
        final_df.to_csv(path, index=False)
        print(f"\nSaved to {path}")

    input("\nPress Enter to return to menu...")


# --- TOOL 2: ODDS SCANNER ---
def run_odds_scanner():
    print("")
    print("\n" + "="*40)
    print("   ODDS SCANNER")
    print("="*40)

    try:
        print("--- 1. Fetching PrizePicks Lines ---")
        pp    = PrizePicksClient(stat_map=STAT_MAP)
        pp_df = pp.fetch_board(league_filter='NBA', include_alts=True)
        if not pp_df.empty:
            # --- Preprocessing: 1H Namespacing ---
            def _namespace_stat(row):
                stat = str(row['Stat'])
                league = str(row.get('League', '')).upper()
                if league == 'NBA1H' and not stat.startswith('1H '):
                    return f"1H {stat}"
                return stat
            
            pp_df['Stat'] = pp_df.apply(_namespace_stat, axis=1)
            pp_df['Stat'] = pp_df['Stat'].replace(PP_NORMALIZATION_MAP)
        n_std = len(pp_df[pp_df.get('OddsType', pd.Series('standard', index=pp_df.index)).isin(['standard', ''])]) if not pp_df.empty else 0
        n_gob = len(pp_df[pp_df.get('OddsType', pd.Series('standard', index=pp_df.index)) == 'goblin']) if not pp_df.empty else 0
        print(f"Got {len(pp_df)} PrizePicks props ({n_std} standard, {n_gob} goblin).")

        print("\n--- 2. Fetching FanDuel Odds ---")
        fd    = FanDuelClient(
            api_key=ODDS_API_KEY, sport_map=SPORT_MAP,
            regions=REGIONS, odds_format=ODDS_FORMAT, stat_map=STAT_MAP
        )
        # Determine the active slate date (handles late-night rollover)
        _, target_date = get_games(date_offset=0, require_scheduled=True)
        print(f"   Active slate: {target_date}")
        fd_df = fd.get_all_odds(target_date=target_date)
        print(f"Got {len(fd_df)} FanDuel props.")

        if pp_df.empty or fd_df.empty:
            print("\nStopping: one of the data sources is empty.")
            input("\nPress Enter to return to menu...")
            return

        print("\n--- 3. Analyzing All Lines ---")
        analyzer = PropsAnalyzer(pp_df, fd_df, league='NBA')
        all_bets = analyzer.calculate_edges()

        if not all_bets.empty:
            sorted_bets = all_bets.sort_values(by='Implied_Win_%', ascending=False)

            # Identify goblin rows by joining back to the OddsType from pp_df
            if 'OddsType' in pp_df.columns:
                odds_map = pp_df.set_index(['Player', 'Stat'])['OddsType'].to_dict() if 'OddsType' in pp_df.columns else {}
                sorted_bets['OddsType'] = sorted_bets.apply(
                    lambda r: odds_map.get((r['Player'], r['Stat']), 'standard'), axis=1
                )
            else:
                sorted_bets['OddsType'] = 'standard'

            display_cols = ['Player', 'Stat', 'Side', 'Line']
            if 'FD_Line' in sorted_bets.columns:
                display_cols.append('FD_Line')
            if 'Line_Diff' in sorted_bets.columns:
                display_cols.append('Line_Diff')
            display_cols.append('Implied_Win_%')

            std_bets = sorted_bets[sorted_bets['OddsType'].isin(['standard', ''])]
            gob_bets = sorted_bets[sorted_bets['OddsType'] == 'goblin']

            if not std_bets.empty:
                print(f"\n{'─'*70}")
                print(f"  STANDARD PLAYS — Top {min(20, len(std_bets))} by Win Probability")
                print(f"{'─'*70}")
                print(std_bets[display_cols].head(20).to_string(index=False))

            if not gob_bets.empty:
                print(f"\n{'─'*70}")
                print(f"  GOBLIN PLAYS — Easier lines, lower payout  ({len(gob_bets)} plays)")
                print(f"{'─'*70}")
                print(gob_bets[display_cols].head(20).to_string(index=False))

            if std_bets.empty and gob_bets.empty:
                print("No profitable matches found.")

            os.makedirs(OUTPUT_DIR, exist_ok=True)
            for game_date in sorted_bets['Date'].unique():
                day_data = sorted_bets[sorted_bets['Date'] == game_date]
                day_data.to_csv(os.path.join(OUTPUT_DIR, f"scan_{game_date}.csv"), index=False)
        else:
            print("No profitable matches found.")

    except Exception as e:
        print(f"\nError: {e}")

    input("\nPress Enter to return to menu...")


# --- TOOL 3: AI SCANNER ---
def run_ai_scanner():
    try:
        df, models = _ensure_session_data()
        ai_scanner_module.main_with_data(df, models)
    except Exception as e:
        print(f"Error running AI Scanner: {e}")
        input("Press Enter...")


# --- SETUP: BUILD DATA ---
def run_builder():
    print("\n" + "=" * 55)
    print("   BUILD NBA DATA")
    print("=" * 55)
    print("Downloads NBA game logs and player history via nba_api")
    print("")
    confirm = input("This may take 2-5 minutes. Continue? (y/n): ").strip().lower()
    if confirm != 'y':
        return
    try:
        from src.sports.nba.builder import fetch_all_game_logs, fetch_1h_game_logs, fetch_player_positions
        fetch_all_game_logs()
        fetch_1h_game_logs()
        fetch_player_positions()
        print("\nData build complete!")
        print("   Next: Run 'Engineer Features' then 'Train Models'.")
    except ImportError as e:
        print(f"Builder import error: {e}")
    except Exception as e:
        print(f"\nBuilder error: {e}")
    global _SESSION_LOADED
    _SESSION_LOADED = False  # force reload on next scan
    input("\nPress Enter to continue...")


def run_feature_engineering():
    print("\n" + "=" * 55)
    print("   FEATURE ENGINEERING")
    print("=" * 55)
    print("Building features from raw game logs...")
    print("")
    try:
        from src.sports.nba.features import main as features_main
        features_main()
        print("\nFeatures built!")
        print("   Next: Run 'Train Models'.")
    except ImportError as e:
        print(f"Features import error: {e}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback; traceback.print_exc()
    global _SESSION_LOADED
    _SESSION_LOADED = False  # force reload on next scan (dataset rebuilt)
    input("\nPress Enter to continue...")


def run_training():
    print("\n" + "=" * 55)
    print("   TRAIN NBA MODELS")
    print("=" * 55)
    print(f"Training {len(ACTIVE_TARGETS)} XGBoost models...")
    print("")
    try:
        from src.sports.nba.train import train_and_evaluate
        train_and_evaluate()
    except ImportError as e:
        print(f"Train import error: {e}")
    except Exception as e:
        print(f"\nTraining error: {e}")
        import traceback; traceback.print_exc()
    global _SESSION_LOADED
    _SESSION_LOADED = False  # force model reload on next scan
    input("\nPress Enter to continue...")


# --- REPORTING ---
def view_metrics():
    import pandas as pd

    metrics_path = os.path.join(_BASE, 'models', 'nba', 'model_metrics.csv')

    print("\n" + "=" * 55)
    print("   NBA MODEL METRICS")
    print("=" * 55)

    if not os.path.exists(metrics_path):
        print("No metrics found. Run 'Train Models' first.")
        input("\nPress Enter to continue...")
        return

    df = pd.read_csv(metrics_path)

    has_realistic = 'Directional_Accuracy' in df.columns and 'Legacy_Global_Accuracy' in df.columns

    if has_realistic:
        print(f"\n{'TARGET':<10} {'MAE':>6} {'R²':>6} {'RealDir%':>9} {'GlobalDir%':>11}")
        print("-" * 48)
        for _, row in df.iterrows():
            print(f"{row['Target']:<10} {row['MAE']:>6.3f} {row['R2']:>6.3f} "
                  f"{row['Directional_Accuracy']:>8.1f}%  {row.get('Legacy_Global_Accuracy', 0):>9.1f}%")
        print("\nRealDir%   = Directional accuracy vs player L10-median (realistic line proxy)")
        print("GlobalDir% = Legacy accuracy vs global test median (inflated/misleading)")
    else:
        print(f"\n{'TARGET':<8} {'MAE':>6} {'R²':>6} {'DIR%':>7}")
        print("-" * 35)
        for _, row in df.iterrows():
            print(f"{row['Target']:<8} {row['MAE']:>6.3f} {row['R2']:>6.3f} "
                  f"{row['Directional_Accuracy']:>6.1f}%")
        print("\nMAE  = Mean Absolute Error (lower is better)")
        print("DIR% = Directional accuracy — did we predict Over/Under correctly")

    if 'Last_Updated' in df.columns:
        print(f"\nLast trained: {df['Last_Updated'].iloc[-1]}")

    input("\nPress Enter to continue...")


def run_injury_debug():
    """Test injury report lookups."""
    print("\n" + "=" * 55)
    print("   INJURY REPORT")
    print("=" * 55)

    try:
        refresh_injuries()
        from src.sports.nba.injuries import get_injury_report
        report = get_injury_report()
        if not report:
            print("No injuries reported.")
        else:
            out_players = [p for p in report if report[p] == 'OUT']
            gtd_players = [p for p in report if report[p] != 'OUT']
            print(f"\nOUT ({len(out_players)}):")
            for p in sorted(out_players)[:20]:
                print(f"   {p}")
            if len(out_players) > 20:
                print(f"   ... and {len(out_players) - 20} more")
            if gtd_players:
                print(f"\nGTD / Other ({len(gtd_players)}):")
                for p in sorted(gtd_players)[:10]:
                    print(f"   {p}: {report[p]}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback; traceback.print_exc()

    input("\nPress Enter to continue...")


def run_backtester():
    print("\n" + "=" * 55)
    print("   WALK-FORWARD BACKTESTER")
    print("=" * 55)
    print("Evaluates model accuracy on the held-out 30% test set")
    print("using player L10-median as the proxy betting line.")
    print("")
    try:
        from src.sports.nba.backtester import run_backtest
        run_backtest()
    except Exception as e:
        print(f"Backtester error: {e}")
        import traceback; traceback.print_exc()
    input("\nPress Enter to continue...")


def search_by_market():
    import glob as _glob

    PROJ_DIR = os.path.join(_BASE, 'data', 'nba', 'projections')

    # Find most recent scan file
    dated = sorted(_glob.glob(os.path.join(PROJ_DIR, 'scan_20*.csv')), reverse=True)
    fallback = os.path.join(PROJ_DIR, 'todays_automated_analysis.csv')
    scan_path = dated[0] if dated else (fallback if os.path.exists(fallback) else None)

    if not scan_path:
        print("\nNo scan data found. Run the AI Scanner first (Option 3).")
        input("\nPress Enter to continue...")
        return

    df = pd.read_csv(scan_path)
    if df.empty or 'TARGET' not in df.columns:
        print("\nScan file is empty or missing expected columns.")
        input("\nPress Enter to continue...")
        return

    if df.empty:
        print("\nNo projection data found in scan file.")
        input("\nPress Enter to continue...")
        return

    # Compute PCT_EDGE only for players that have a PrizePicks line.
    # Players without a line get NaN (displayed as '--' in the table).
    # Match the scanner's safe_denominator logic: max(line, 2.0) prevents
    # low lines (e.g. BLK 0.5) from inflating edge% vs what the scanner reports.
    has_line = df['PP'].notna() & (df['PP'] > 0)
    df['PCT_EDGE'] = float('nan')
    df.loc[has_line, 'PCT_EDGE'] = (
        df.loc[has_line, 'EDGE'] / df.loc[has_line, 'PP'].clip(lower=2.0)
    ) * 100

    available = sorted(df['TARGET'].unique())
    labels = {
        'PTS': 'Points', 'REB': 'Rebounds', 'AST': 'Assists',
        'FG3M': '3-PT Made', 'FG3A': '3-PT Attempted',
        'BLK': 'Blocks', 'STL': 'Steals', 'TOV': 'Turnovers',
        'FGM': 'FG Made', 'FGA': 'FG Attempted',
        'FTM': 'FT Made', 'FTA': 'FT Attempted',
        'PRA': 'Pts+Rebs+Asts', 'PR': 'Pts+Rebs', 'PA': 'Pts+Asts',
        'RA': 'Rebs+Asts', 'SB': 'Blks+Stls', 'FPTS': 'Fantasy Score',
        'PTS_1H': '1H Points', 'PRA_1H': '1H PRA', 'FPTS_1H': '1H Fantasy Score',
    }

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n" + "=" * 55)
        print("   SEARCH BY MARKET")
        print(f"   Scan: {os.path.basename(scan_path)}")
        print("=" * 55)
        print("\nAvailable markets:")
        for i, t in enumerate(available, 1):
            n = len(df[df['TARGET'] == t])
            print(f"  {i:>2}. {t:<10} {labels.get(t, ''):<25} ({n} players)")

        print("\n  0. Back")
        choice = input("\nEnter market code or number: ").strip().upper()

        if choice == '0' or choice == '':
            break

        # Allow selection by number or by code
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(available):
                target = available[idx]
            else:
                print("Invalid number."); input("Press Enter..."); continue
        elif choice in available:
            target = choice
        else:
            print(f"'{choice}' not found. Try one of: {', '.join(available)}")
            input("Press Enter..."); continue

        sub = df[df['TARGET'] == target].copy()
        # Players with a line: sort by absolute edge descending.
        # Players without a line: appended after, sorted by AI projection.
        lined   = sub[sub['PCT_EDGE'].notna()].sort_values('PCT_EDGE', key=abs, ascending=False)
        no_line = sub[sub['PCT_EDGE'].isna()].sort_values('AI', ascending=False)
        sub = pd.concat([lined, no_line], ignore_index=True)

        overs  = sub[sub['EDGE'] > 0].sort_values('PCT_EDGE', ascending=False, na_position='last')
        unders = sub[sub['EDGE'] < 0].sort_values('PCT_EDGE', ascending=True,  na_position='last')
        no_line_rows = sub[sub['PP'].isna() | (sub['PP'] <= 0)]

        def _print_market_table(rows, side_label):
            if rows.empty:
                return
            print(f"\n{'─' * 100}")
            print(f"   {side_label}  ({len(rows)} plays)")
            print(f"{'─' * 100}")
            print(f"   {'#':>3}  {'PLAYER':<25} {'PROJ':>6} {'LINE':>6} {'EDGE':>8} {'L5':>4} {'L10':>4} {'L20':>4} {'H2H':>8}")
            print(f"{'─' * 100}")
            is_over = side_label.startswith('OVER')
            for i, (_, row) in enumerate(rows.iterrows(), 1):
                l5  = f"{row['L5_HIT']*100:.0f}%"  if is_over else f"{(1-row['L5_HIT'])*100:.0f}%"
                l10 = f"{row['L10_HIT']*100:.0f}%" if is_over else f"{(1-row['L10_HIT'])*100:.0f}%"
                l20 = f"{row['L20_HIT']*100:.0f}%" if is_over else f"{(1-row['L20_HIT'])*100:.0f}%"
                h2h_n = int(row.get('H2H_N', 0))
                if h2h_n > 0:
                    rate = row['H2H_HIT'] if is_over else 1 - row['H2H_HIT']
                    h2h = f"{rate*100:.0f}%({h2h_n})"
                else:
                    h2h = '--'
                pp_str   = f"{row['PP']:6.1f}" if (row['PP'] > 0 if pd.notna(row['PP']) else False) else '  N/A '
                edge_str = f"{row['PCT_EDGE']:+8.1f}%" if pd.notna(row['PCT_EDGE']) else '      --'
                print(f"   {i:>3}  {str(row['NAME'])[:25]:<25} {row['AI']:>6.1f} {pp_str} "
                      f"{edge_str} {l5:>4} {l10:>4} {l20:>4} {h2h:>8}")
            print(f"{'─' * 100}")

        os.system('cls' if os.name == 'nt' else 'clear')
        mkt_label = labels.get(target, target)
        print(f"\n{'═' * 100}")
        print(f"   {mkt_label} ({target})  —  {len(sub)} players on the board")
        print(f"{'═' * 100}")
        _print_market_table(overs,  f"OVERS  — players projected above the line")
        _print_market_table(unders, f"UNDERS — players projected below the line")
        if not no_line_rows.empty:
            _print_market_table(no_line_rows, f"NO LINE — all other players in today's games")

        input("\nPress Enter to search another market or go back...")


def _show_def_matchup():
    """
    Prompt for an opponent team abbreviation and display a per-stat defensive
    ranking table so the user can judge how favourable the matchup is.

    Groups the training dataset by OPPONENT, computing the average stats
    allowed per game to opposing players.  Rank 1 = fewest allowed = toughest
    defence; rank N = most allowed = weakest.

    An optional position filter (G / F / C) narrows the sample to just guards,
    forwards, or centres so you can ask, e.g., "How does BOS defend Cs?"
    """
    global _SESSION_DF

    # Reuse session data if the scanner already loaded it; otherwise read CSV.
    df_hist = _SESSION_DF
    if df_hist is None:
        if 'raw_df' not in _DEF_RANK_CACHE:
            raw_path = os.path.join(_BASE, 'data', 'nba', 'processed', 'training_dataset.csv')
            if not os.path.exists(raw_path):
                print("   ⚪ Matchup data unavailable — run 'Build Data' first.")
                return
            try:
                _DEF_RANK_CACHE['raw_df'] = pd.read_csv(raw_path, low_memory=False)
            except Exception as e:
                print(f"   Could not load training data: {e}")
                return
        df_hist = _DEF_RANK_CACHE['raw_df']

    if 'OPPONENT' not in df_hist.columns:
        return

    DEF_STATS = [s for s in
                 ['PTS', 'REB', 'AST', 'FG3M', 'STL', 'BLK', 'TOV', 'FGM', 'FTA']
                 if s in df_hist.columns]

    opp = input("\n   Check opponent matchup? Team abbr (e.g. BOS) or Enter to skip: ").strip().upper()
    if not opp:
        return

    # Optional position filter
    pos_filter = None
    if 'POSITION' in df_hist.columns:
        pos_in = input("   Position filter? G / F / C (or Enter for all): ").strip().upper()
        if pos_in in ('G', 'F', 'C'):
            pos_filter = pos_in

    # Build or retrieve cached per-position rankings
    rank_key = ('ranks', pos_filter)
    if rank_key not in _DEF_RANK_CACHE:
        sub = df_hist[df_hist['OPPONENT'].notna()].copy()
        if pos_filter:
            # NBA positions: 'G', 'F', 'C', 'G-F', 'F-C', etc. — match prefix
            sub = sub[sub['POSITION'].str.upper().str.startswith(pos_filter, na=False)]
        if sub.empty:
            print(f"   No data for position filter '{pos_filter}'.")
            return
        avgs   = sub.groupby('OPPONENT')[DEF_STATS].mean()
        n      = len(avgs)
        ranks  = avgs.rank(ascending=False, method='min').astype(int)
        lg_avg = avgs.mean()
        _DEF_RANK_CACHE[rank_key] = {
            'avgs': avgs, 'ranks': ranks, 'lg_avg': lg_avg, 'n': n
        }

    c      = _DEF_RANK_CACHE[rank_key]
    avgs   = c['avgs']
    ranks  = c['ranks']
    lg_avg = c['lg_avg']
    n      = c['n']

    if opp not in avgs.index:
        print(f"\n   Team '{opp}' not found.")
        print(f"   Available: {', '.join(sorted(avgs.index))}")
        return

    pos_label = f" — {pos_filter}s only" if pos_filter else ""
    print(f"\n{'─' * 64}")
    print(f"   DEF MATCHUP: {opp}{pos_label}  (rank 1 = most allowed / WEAK  {n} = fewest / TOUGH)")
    print(f"{'─' * 64}")
    print(f"   {'STAT':<6} {'ALLOWED/G':>9} {'LG AVG':>7} {'DIFF':>6} {'RANK':>5}  VERDICT")
    print(f"{'─' * 64}")

    for stat in DEF_STATS:
        if stat not in avgs.columns:
            continue
        allowed = avgs.loc[opp, stat]
        league  = lg_avg[stat]
        diff    = allowed - league
        rank    = int(ranks.loc[opp, stat])
        pct     = rank / n   # 0..1; low rank (near 1) = most allowed = weak

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


def search_player():
    """
    Search all projections for a specific player by name.
    Reads from the most recent scan CSV, shows every prop sorted by
    absolute edge % (highest conviction first).
    """
    import glob

    PROJ_DIR  = os.path.join(_BASE, 'data', 'nba', 'projections')
    dated     = sorted(glob.glob(os.path.join(PROJ_DIR, 'scan_20*.csv')), reverse=True)
    fallback  = os.path.join(PROJ_DIR, 'todays_automated_analysis.csv')
    scan_path = dated[0] if dated else (fallback if os.path.exists(fallback) else None)

    if not scan_path:
        print("\n   No scan data found. Run the AI Scanner first (Option 3).")
        input("\nPress Enter to continue...")
        return

    df = pd.read_csv(scan_path)
    if df.empty or 'NAME' not in df.columns:
        print("\n   Scan file is empty or missing expected columns.")
        input("\nPress Enter to continue...")
        return

    scan_label = os.path.basename(scan_path).replace('scan_', '').replace('.csv', '')
    if scan_label == 'todays_automated_analysis':
        scan_label = 'today (auto)'

    # Compute percentage edge on the fly (same denominator floor as search_by_market)
    has_pp   = df['PP'].notna() & (df['PP'] > 0)
    df['PCT_EDGE'] = float('nan')
    df.loc[has_pp, 'PCT_EDGE'] = (
        df.loc[has_pp, 'EDGE'] / df.loc[has_pp, 'PP'].clip(lower=2.0)
    ) * 100

    # Friendly stat labels
    _LABELS = {
        'PTS': 'Points',     'REB': 'Rebounds',  'AST': 'Assists',
        'FG3M': '3-PT Made', 'BLK': 'Blocks',    'STL': 'Steals',
        'TOV': 'Turnovers',  'FGM': 'FG Made',   'FTM': 'FT Made',
        'FTA': 'FT Att',     'FGA': 'FG Att',
        'PRA': 'Pts+Reb+Ast','PR': 'Pts+Reb',    'PA': 'Pts+Ast',
        'RA': 'Reb+Ast',     'SB': 'Blk+Stl',    'FPTS': 'Fantasy',
        'PTS_1H': '1H Points','PRA_1H': '1H PRA', 'FPTS_1H': '1H Fantasy',
    }

    print(f"\n{'='*60}")
    print("   🏀 NBA PLAYER SEARCH")
    print(f"   Scan: {scan_label}  |  {len(df):,} total projections")
    print(f"{'='*60}")

    while True:
        print("\n" + "─" * 60)
        query = input("   Player name (or '0' to exit): ").strip()
        if query in ('0', 'q', ''):
            break

        mask    = df['NAME'].str.lower().str.contains(query.lower(), na=False)
        matches = df[mask]

        if matches.empty:
            print(f"\n   No player found matching '{query}'.")
            continue

        # Disambiguate
        unique_names = matches['NAME'].drop_duplicates().reset_index(drop=True)
        if len(unique_names) > 1:
            print(f"\n   Multiple players matched:")
            for j, name in enumerate(unique_names, 1):
                print(f"     {j}. {name}")
            pick = input("   Enter number (or 0 to skip): ").strip()
            try:
                idx = int(pick) - 1
                if idx < 0 or idx >= len(unique_names):
                    continue
                chosen = unique_names[idx]
                matches = matches[matches['NAME'] == chosen]
            except ValueError:
                continue

        chosen_name = matches['NAME'].iloc[0]

        # Sort by |PCT_EDGE| desc, projections without a line come last
        has_line  = matches['PP'].notna() & (matches['PP'] > 0)
        lined     = matches[has_line].copy()
        no_line   = matches[~has_line].copy()
        lined     = lined.sort_values('PCT_EDGE', key=abs, ascending=False)
        no_line   = no_line.sort_values('AI', ascending=False)
        player_df = pd.concat([lined, no_line], ignore_index=True)

        has_h2h   = 'H2H_HIT' in player_df.columns and (player_df['H2H_N'].fillna(0) > 0).any()
        has_l20   = 'L20_HIT' in player_df.columns

        print(f"\n{'═'*72}")
        print(f"   {chosen_name.upper()}")
        print(f"   {len(player_df)} prop(s) in scan  |  {scan_label}")
        print(f"{'═'*72}")

        sep = " │ "
        w_stat = 14
        header  = (f"{'#':>3}{sep}{'STAT':<{w_stat}}{sep}{'LINE':>5}{sep}"
                   f"{'AI':>6}{sep}{'EDGE%':>7}{sep}{'SIDE':<8}{sep}"
                   f"{'L5':>4}{sep}{'L10':>4}")
        if has_l20:   header += f"{sep}{'L20':>4}"
        if has_h2h:   header += f"{sep}{'H2H':>8}"
        print(header)
        print("─" * len(header))

        for rank_i, row in player_df.iterrows():
            target  = str(row.get('TARGET', ''))
            stat_s  = _LABELS.get(target, target)[:w_stat]
            pp_val  = row.get('PP')
            pp_s    = f"{float(pp_val):5.1f}" if pd.notna(pp_val) and pp_val > 0 else "  N/A"
            ai_val  = row.get('AI')
            ai_s    = f"{float(ai_val):6.1f}" if pd.notna(ai_val) else "   ---"
            pct     = row.get('PCT_EDGE')
            pct_s   = f"{float(pct):+6.1f}%" if pd.notna(pct) else "    ---"
            edge    = row.get('EDGE', 0) or 0
            side_s  = "▲ Over  " if edge > 0 else "▼ Under "

            is_over  = edge > 0
            l5_raw   = row.get('L5_HIT',  0) or 0
            l10_raw  = row.get('L10_HIT', 0) or 0
            l5_dir   = l5_raw  if is_over else (1 - l5_raw)
            l10_dir  = l10_raw if is_over else (1 - l10_raw)
            l5_s     = f"{l5_dir*100:.0f}%"  if pd.notna(l5_raw)  else " N/A"
            l10_s    = f"{l10_dir*100:.0f}%" if pd.notna(l10_raw) else " N/A"

            base = (f"{rank_i+1:>3}{sep}{stat_s:<{w_stat}}{sep}"
                    f"{pp_s}{sep}{ai_s}{sep}{pct_s}{sep}{side_s}{sep}"
                    f"{l5_s:>4}{sep}{l10_s:>4}")
            if has_l20:
                l20_raw  = row.get('L20_HIT', 0) or 0
                l20_dir  = l20_raw if is_over else (1 - l20_raw)
                l20_s    = f"{l20_dir*100:.0f}%" if pd.notna(l20_raw) else " N/A"
                base    += f"{sep}{l20_s:>4}"
            if has_h2h:
                h2h_n   = int(row.get('H2H_N', 0) or 0)
                if h2h_n > 0:
                    h2h_r   = row.get('H2H_HIT', 0) or 0
                    h2h_dir = h2h_r if is_over else (1 - h2h_r)
                    h2h_s   = f"{h2h_dir*100:.0f}%({h2h_n})"
                else:
                    h2h_s = "      --"
                base += f"{sep}{h2h_s:>8}"

            prefix = " ★" if rank_i == 0 else "  "
            print(f"{prefix}{base}")

        print("─" * len(header))
        print("   Ranked by |EDGE%|  ★ = top play")
        print("   L5/L10/L20 = hit rate in the projected direction (Over or Under)")
        if has_h2h:
            print("   H2H = historical hit rate vs today's opponent  (n = games played)")

        # Defensive matchup breakdown (optional — user can skip with Enter)
        _show_def_matchup()


def run_grade_all():
    print("\n" + "=" * 55)
    print("   GRADE ALL UNGRADED SCAN FILES")
    print("=" * 55)
    print("Fetches actual NBA results and scores every ungraded scan.")
    print("")
    try:
        from src.sports.nba.grader import grade_all_ungraded
        grade_all_ungraded()
    except Exception as e:
        print(f"Grader error: {e}")
        import traceback; traceback.print_exc()
    input("\nPress Enter to continue...")


# --- STARTUP PIPELINE CHECK ---
def startup_pipeline_check():
    """Auto-refresh data, features, and models on startup if stale."""
    raw_log_path    = os.path.join(_BASE, 'data', 'nba', 'raw', 'raw_game_logs.csv')
    training_path   = os.path.join(_BASE, 'data', 'nba', 'processed', 'training_dataset.csv')
    model_dir       = os.path.join(_BASE, 'models', 'nba')
    first_model     = os.path.join(model_dir, 'PTS_model.json')

    print("\n" + "=" * 55)
    print("   STARTUP DATA CHECK")
    print("=" * 55)

    # --- 1. Check raw data staleness ---
    needs_raw_refresh = True
    days_stale = 999
    if os.path.exists(raw_log_path):
        try:
            df_raw = pd.read_csv(raw_log_path, usecols=['GAME_DATE'])
            last_date = pd.to_datetime(df_raw['GAME_DATE']).max()
            today     = pd.to_datetime(datetime.now().strftime('%Y-%m-%d'))
            days_stale = (today - last_date).days
            needs_raw_refresh = days_stale > 1
            status = "FRESH" if not needs_raw_refresh else f"STALE ({days_stale}d)"
            print(f"   Game logs:  {last_date.date()}  [{status}]")
        except Exception as e:
            print(f"   Game logs:  could not read ({e})")
    else:
        print("   Game logs:  NOT FOUND")

    # --- 2. Refresh raw data if stale ---
    if needs_raw_refresh:
        print("\n   Fetching new game logs from NBA API...")
        try:
            from src.sports.nba.builder import fetch_all_game_logs, fetch_1h_game_logs
            fetch_all_game_logs()
            fetch_1h_game_logs()
            print("   Raw data updated.")
        except Exception as e:
            print(f"   Data fetch failed: {e}")

    # --- 3. Re-engineer features if raw data was refreshed ---
    needs_features = needs_raw_refresh
    if not needs_features and os.path.exists(training_path) and os.path.exists(raw_log_path):
        # Also rebuild if training dataset is older than raw logs
        try:
            raw_mtime  = os.path.getmtime(raw_log_path)
            feat_mtime = os.path.getmtime(training_path)
            needs_features = raw_mtime > feat_mtime
        except Exception:
            pass

    if needs_features:
        print("   Re-engineering features...")
        try:
            from src.sports.nba.features import main as features_main
            features_main()
            print("   Features rebuilt.")
        except Exception as e:
            print(f"   Feature engineering failed: {e}")

    # --- 4. Retrain models if >7 days old ---
    needs_retrain = False
    if os.path.exists(first_model):
        model_age_days = (datetime.now().timestamp() - os.path.getmtime(first_model)) / 86400
        needs_retrain  = model_age_days > 7
        print(f"   Models:     {model_age_days:.1f} days old  [{'RETRAIN' if needs_retrain else 'OK'}]")
    else:
        needs_retrain = True
        print("   Models:     NOT FOUND")

    if needs_retrain:
        print("   Retraining XGBoost models (this takes a few minutes)...")
        try:
            from src.sports.nba.train import train_and_evaluate
            train_and_evaluate()
            print("   Models retrained.")
        except Exception as e:
            print(f"   Training failed: {e}")

    print("=" * 55)
    print("   Ready.")
    print("=" * 55)


# --- MAIN MENU ---
def main_menu():
    startup_pipeline_check()

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')

        print("\n" + "=" * 55)
        print("   NBA EV BOT")
        print("=" * 55)
        print(f"   {datetime.now().strftime('%A, %B %d, %Y')}")
        print("=" * 55)
        print_mode_info()

        print("\nANALYSIS")
        print("1. Super Scanner         -- Math + AI correlated plays")
        print("2. Odds Scanner          -- FanDuel vs PrizePicks")
        print("3. AI Scanner            -- Scan / Scout / Grade")

        print("\nSETUP  (run once in order)")
        print("4. Build Data            -- Download NBA game history")
        print("5. Engineer Features     -- Build training features")
        print("6. Train Models          -- Train all 13 XGBoost models")

        print("\nREPORTING")
        print("7. Model Metrics         -- Accuracy by market")
        print("8. Injury Report         -- Current injury status")
        print("9. Run Backtester        -- Historical win rate & ROI simulation")
        print("A. Grade All Results     -- Grade every ungraded scan file")
        print("B. Search by Market      -- Browse all plays for a specific stat")
        print("C. Search by Player      -- All props for a specific player")

        print("\n" + "=" * 55)
        print("0. Back")
        print("=" * 55)

        choice = input("\nSelect: ").strip().upper()

        if   choice == '1': run_correlated_scanner()
        elif choice == '2': run_odds_scanner()
        elif choice == '3': run_ai_scanner()
        elif choice == '4': run_builder()
        elif choice == '5': run_feature_engineering()
        elif choice == '6': run_training()
        elif choice == '7': view_metrics()
        elif choice == '8': run_injury_debug()
        elif choice == '9': run_backtester()
        elif choice == 'A': run_grade_all()
        elif choice == 'B': search_by_market()
        elif choice == 'C': search_player()
        elif choice == '0': break
        else:
            print("\nInvalid selection.")
            input("Press Enter to try again...")


if __name__ == "__main__":
    main_menu()