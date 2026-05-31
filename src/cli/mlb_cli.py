"""
MLB CLI - Main Entry Point for the MLB EV Bot

Menu:
    1. AI Scanner            -- Today's MLB props vs AI projections
    2. Build Data            -- Download MLB game logs (one-time, ~10 min)
    3. Engineer Features     -- Build training features
    4. Train Models          -- Train XGBoost models
    5. Model Metrics         -- View current accuracy

Usage:
    Called from main.py → main_menu()
"""

import os
import warnings
import pandas as pd
from datetime import datetime

warnings.filterwarnings('ignore')

_BASE      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(_BASE, 'output', 'mlb', 'scans')

# Standard MLB Stats API team IDs → abbreviations
_MLB_TEAM_MAP = {
    108: 'LAA', 109: 'ARI', 110: 'BAL', 111: 'BOS', 112: 'CHC',
    113: 'CIN', 114: 'CLE', 115: 'COL', 116: 'DET', 117: 'HOU',
    118: 'KC',  119: 'LAD', 120: 'WSH', 121: 'NYM', 133: 'OAK',
    134: 'PIT', 135: 'SD',  136: 'SEA', 137: 'SF',  138: 'STL',
    139: 'TB',  140: 'TEX', 141: 'TOR', 142: 'MIN', 143: 'PHI',
    144: 'ATL', 145: 'CWS', 146: 'MIA', 147: 'NYY', 158: 'MIL',
}
# Reverse map: abbreviation → team_id (for user input)
_MLB_ABBR_TO_ID = {v: k for k, v in _MLB_TEAM_MAP.items()}

# Defensive matchup cache — lazily populated from batter_training.csv
_MLB_DEF_CACHE: dict = {}


def run_scanner():
    try:
        from src.sports.mlb.scanner import main as scanner_main
        scanner_main()
    except ImportError as e:
        print(f"Import error: {e}")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"Scanner error: {e}")
        import traceback; traceback.print_exc()
        input("\nPress Enter to continue...")


def run_builder():
    print("\n" + "=" * 55)
    print("   BUILD MLB DATA")
    print("=" * 55)
    print("Downloads MLB game logs via MLB Stats API (free, no key)")
    print("Fetches batting + pitching logs for 2022-present")
    print("")
    print("⚠️  This takes 10-15 minutes on first run.")
    confirm = input("\nContinue? (y/n): ").strip().lower()
    if confirm != 'y':
        return

    try:
        from src.sports.mlb.builder import fetch_batting_logs, fetch_pitching_logs
        print("\n--- Batting logs ---")
        fetch_batting_logs()
        print("\n--- Pitching logs ---")
        fetch_pitching_logs()
        print("\n✅  Data build complete! Next: Engineer Features → Train Models")
    except Exception as e:
        print(f"\nBuilder error: {e}")
        import traceback; traceback.print_exc()

    input("\nPress Enter to continue...")


def run_feature_engineering():
    print("\n" + "=" * 55)
    print("   FEATURE ENGINEERING")
    print("=" * 55)
    print("Building rolling-average features from raw game logs...")
    print("")

    try:
        from src.sports.mlb.features import main as features_main
        features_main()
        print("\n✅  Features built! Next: Train Models")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback; traceback.print_exc()

    input("\nPress Enter to continue...")


def run_training():
    print("\n" + "=" * 55)
    print("   TRAIN MLB MODELS")
    print("=" * 55)
    print("Training XGBoost models for batter and pitcher stats...")
    print("")

    try:
        from src.sports.mlb.train import train_and_evaluate
        train_and_evaluate()
    except Exception as e:
        print(f"\nTraining error: {e}")
        import traceback; traceback.print_exc()

    input("\nPress Enter to continue...")


def view_metrics():
    metrics_path = os.path.join(_BASE, 'models', 'mlb', 'model_metrics.csv')

    print("\n" + "=" * 55)
    print("   MLB MODEL METRICS")
    print("=" * 55)

    if not os.path.exists(metrics_path):
        print("No metrics found. Run 'Train Models' first.")
        input("\nPress Enter to continue...")
        return

    df = pd.read_csv(metrics_path)
    print(f"\n{'TARGET':<8} {'GROUP':<10} {'MAE':>6} {'R²':>6} {'DIR%':>7} {'TRAIN':>8}")
    print("-" * 50)
    for _, row in df.iterrows():
        print(f"{row['target']:<8} {row['group']:<10} {row['mae']:>6.3f} "
              f"{row['r2']:>6.3f} {row['dir_accuracy']:>6.1f}% {int(row['train_rows']):>7,}")

    print("\nMAE  = Mean Absolute Error (lower is better)")
    print("DIR% = Did we predict Over/Under correctly")
    if 'trained_at' in df.columns:
        print(f"\nLast trained: {df['trained_at'].iloc[-1]}")

    input("\nPress Enter to continue...")


def search_player():
    """
    Search all MLB scan results for a specific player.
    Reads the most recent scan CSV; if the player isn't found there
    (e.g. their edge was below threshold), falls back to a fresh
    PrizePicks board fetch + on-the-fly projection.
    """
    import glob
    from src.sports.mlb.scanner import (
        _ensure_session, get_all_projections, normalize_name as mlb_norm
    )

    scan_dir  = os.path.join(_BASE, 'output', 'mlb', 'scans')
    dated     = sorted(glob.glob(os.path.join(scan_dir, 'scan_20*.csv')), reverse=True)
    scan_path = dated[0] if dated else None

    # Load scan CSV if available
    df = pd.DataFrame()
    scan_label = 'none'
    if scan_path:
        try:
            df = pd.read_csv(scan_path)
            scan_label = os.path.basename(scan_path).replace('scan_', '').replace('.csv', '')
        except Exception:
            pass

    has_pf     = 'HR_L10'  in df.columns and (df['HR_L10'] != -1).any() if not df.empty else False
    has_splits = 'OPS_vs'  in df.columns and df['OPS_vs'].notna().any()  if not df.empty else False
    has_ctx    = 'Game_Total' in df.columns and df['Game_Total'].notna().any() if not df.empty else False

    print(f"\n{'='*60}")
    print("   ⚾ MLB PLAYER SEARCH")
    if not df.empty:
        print(f"   Scan: {scan_label}  |  {len(df):,} plays above threshold")
    else:
        print("   No scan file found — will run live projection for any search")
    print(f"{'='*60}")

    while True:
        print("\n" + "─" * 60)
        query = input("   Player name (or '0' to exit): ").strip()
        if query in ('0', 'q', ''):
            break

        # Search in scan CSV first
        matches = pd.DataFrame()
        if not df.empty and 'Player' in df.columns:
            mask    = df['Player'].str.lower().str.contains(query.lower(), na=False)
            matches = df[mask]

        if matches.empty:
            # Fallback: run a fresh low-threshold projection for this player
            print(f"\n   Not found in today's scan — running live projection...")
            try:
                batters, pitchers, models = _ensure_session()
                all_proj = get_all_projections(batters, pitchers, models)
                if not all_proj.empty and 'Player' in all_proj.columns:
                    mask2 = all_proj['Player'].str.lower().str.contains(query.lower(), na=False)
                    matches = all_proj[mask2].copy()
                    # Override Edge_Pct / Stat_Label columns expected below
                    if not matches.empty:
                        if 'Edge_Pct' not in matches.columns and 'Edge' in matches.columns and 'PP_Line' in matches.columns:
                            matches['Edge_Pct'] = (matches['Edge'].abs() / matches['PP_Line'].clip(lower=0.5)) * 100
                        if 'Stat_Label' not in matches.columns and 'Stat' in matches.columns:
                            matches['Stat_Label'] = matches['Stat']
                        has_pf     = 'HR_L10'    in matches.columns and (matches['HR_L10'] != -1).any()
                        has_splits = 'OPS_vs'    in matches.columns and matches['OPS_vs'].notna().any()
                        has_ctx    = 'Game_Total' in matches.columns and matches['Game_Total'].notna().any()
            except Exception as e:
                print(f"   Live projection failed: {e}")

            if matches.empty:
                print(f"\n   No player found matching '{query}' on today's PrizePicks board.")
                continue

        # Disambiguate
        unique_names = matches['Player'].drop_duplicates().reset_index(drop=True)
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
                matches = matches[matches['Player'] == chosen]
            except ValueError:
                continue

        chosen_name = matches['Player'].iloc[0]
        player_df   = matches.sort_values('Edge_Pct', key=abs, ascending=False).reset_index(drop=True)

        is_pitcher  = bool(player_df['Is_Pitcher'].any()) if 'Is_Pitcher' in player_df.columns else False
        role_label  = "⚾ Pitcher" if is_pitcher else "🏏 Batter"

        print(f"\n{'═'*74}")
        print(f"   {chosen_name.upper()}  {role_label}")
        print(f"   {len(player_df)} prop(s) above threshold  |  {scan_label}")
        print(f"{'═'*74}")

        sep    = " │ "
        w_stat = 16
        header = (f"{'#':>3}{sep}{'STAT':<{w_stat}}{sep}{'FLG':<4}{sep}"
                  f"{'LINE':>5}{sep}{'AI':>6}{sep}{'EDGE%':>7}{sep}{'SIDE':<8}{sep}"
                  f"{'L5':>5}{sep}{'L10':>5}")
        if has_pf:
            header += f"{sep}{'HR10':>5}{sep}{'STRK':>5}{sep}{'CON%':>5}"
        if has_splits:
            header += f"{sep}{'OPS':>6}{sep}{'AVG':>5}"
        if has_ctx:
            header += f"{sep}{'TOT':>4}{sep}{'IMP':>4}"
        print(header)
        print("─" * len(header))

        for rank_i, row in player_df.iterrows():
            stat_s    = str(row.get('Stat_Label', row.get('Stat', '')))[:w_stat]
            is_gob    = bool(row.get('Is_Goblin', False))
            is_pit    = bool(row.get('Is_Pitcher', False))
            flg_s     = ('G' if is_gob else ' ') + ('P' if is_pit else ' ') + '  '
            line_s    = f"{float(row['PP_Line']):5.1f}"
            ai_s      = f"{float(row['AI_Proj']):6.2f}"
            pct_s     = f"{float(row['Edge_Pct']):+6.1f}%"
            side_s    = "▲ Over  " if row.get('Side') == 'Over' else "▼ Under "
            l5_s      = f"{float(row['L5']):5.2f}"  if pd.notna(row.get('L5'))  else "  ---"
            l10_s     = f"{float(row['L10']):5.2f}" if pd.notna(row.get('L10')) else "  ---"

            base = (f"{rank_i+1:>3}{sep}{stat_s:<{w_stat}}{sep}{flg_s:<4}{sep}"
                    f"{line_s}{sep}{ai_s}{sep}{pct_s}{sep}{side_s}{sep}"
                    f"{l5_s}{sep}{l10_s}")
            if has_pf:
                hr10   = row.get('HR_L10', -1)
                streak = int(row.get('Streak', 0) or 0)
                con    = float(row.get('Con_Over', 0) or 0)
                hr10_s = f"{hr10:.0f}%"    if hr10 >= 0 else "  N/A"
                strk_s = f"{streak:>+5}"   if streak    else "    0"
                con_s  = f"{con:.0f}%"
                base  += f"{sep}{hr10_s:>5}{sep}{strk_s}{sep}{con_s:>5}"
            if has_splits:
                ops  = row.get('OPS_vs')
                avg  = row.get('AVG_vs')
                hand = str(row.get('Pitch_Hand', '') or '')
                vs_s  = f"v{hand}" if hand else "  "
                ops_s = f"{ops:.3f}" if pd.notna(ops) else "  ---"
                avg_s = f"{avg:.3f}" if pd.notna(avg) else "  ---"
                base += f"{sep}{vs_s}{ops_s:>4}{sep}{avg_s:>5}"
            if has_ctx:
                gt    = row.get('Game_Total')
                imp   = row.get('Implied')
                gt_s  = f"{gt:.1f}" if pd.notna(gt)  else " ---"
                imp_s = f"{imp:.1f}" if pd.notna(imp) else " ---"
                base += f"{sep}{gt_s:>4}{sep}{imp_s:>4}"

            prefix = " ★" if rank_i == 0 else "  "
            print(f"{prefix}{base}")

        print("─" * len(header))
        print("   Ranked by |EDGE%|  ★ = top play  FLG: G=Goblin line  P=Pitcher  GP=both")
        if has_pf:
            print("   HR10=hit rate L10 over line  |  STRK=streak  |  CON%=consensus over %")
        if has_splits:
            print("   vR/vL OPS|AVG = batter splits vs today's opposing pitcher hand")
        if has_ctx:
            print("   TOT=game O/U  |  IMP=this team's implied runs")
        print("   L5/L10 = rolling average (actual stat value, not hit rate)")

        # Defensive matchup breakdown (optional — user can skip with Enter)
        _show_def_matchup_mlb(is_pitcher=is_pitcher)


def _show_def_matchup_mlb(is_pitcher=False):
    """
    Prompt for an opponent team abbreviation and show how their pitching (for
    batters) or lineup (for pitchers) has performed this season.

    Source: data/mlb/processed/batter_training.csv
      — Group by opponent_id → compute mean batter stats allowed per game
      — Rank 30 teams: rank 1 = fewest allowed = toughest pitching / lineup

    For batters  : higher H/TB/HR/RBI/R allowed = weaker pitching  (⚠ WEAK)
    For pitchers : higher H/HR/R produced by opponent batters = tougher lineup
    """
    batter_path = os.path.join(_BASE, 'data', 'mlb', 'processed', 'batter_training.csv')
    if not os.path.exists(batter_path):
        return

    opp_in = input("\n   Check opponent matchup? Team abbr (e.g. NYY) or Enter to skip: ").strip().upper()
    if not opp_in:
        return

    # Accept abbreviation OR numeric ID
    if opp_in.isdigit():
        opp_id = int(opp_in)
    else:
        opp_id = _MLB_ABBR_TO_ID.get(opp_in)
        if opp_id is None:
            # Try partial match (e.g. "CHI" → match CHC or CWS)
            matches = {k: v for k, v in _MLB_ABBR_TO_ID.items() if opp_in[:2] in k}
            if matches:
                print(f"   '{opp_in}' not found. Did you mean: {', '.join(sorted(matches))}?")
            else:
                print(f"   '{opp_in}' not found. Available: {', '.join(sorted(_MLB_ABBR_TO_ID))}")
            return

    # Load and cache batter training data
    if 'df' not in _MLB_DEF_CACHE:
        try:
            _MLB_DEF_CACHE['df'] = pd.read_csv(batter_path, low_memory=False)
        except Exception as e:
            print(f"   Could not load MLB training data: {e}")
            return

    df = _MLB_DEF_CACHE['df']

    # Build per-opponent rankings (cached)
    if 'ranks' not in _MLB_DEF_CACHE:
        BAT_STATS = [s for s in ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB']
                     if s in df.columns]
        sub  = df[df['opponent_id'].notna()].copy()
        sub['opponent_id'] = sub['opponent_id'].astype(int)
        avgs = sub.groupby('opponent_id')[BAT_STATS].mean()
        n    = len(avgs)
        _MLB_DEF_CACHE['avgs']    = avgs
        _MLB_DEF_CACHE['ranks']   = avgs.rank(ascending=False, method='min').astype(int)
        _MLB_DEF_CACHE['lg_avg']  = avgs.mean()
        _MLB_DEF_CACHE['n']       = n
        _MLB_DEF_CACHE['stats']   = BAT_STATS

    avgs    = _MLB_DEF_CACHE['avgs']
    ranks   = _MLB_DEF_CACHE['ranks']
    lg_avg  = _MLB_DEF_CACHE['lg_avg']
    n       = _MLB_DEF_CACHE['n']
    stats   = _MLB_DEF_CACHE['stats']

    if opp_id not in avgs.index:
        known = [f"{_MLB_TEAM_MAP.get(int(i), str(i))}" for i in sorted(avgs.index)]
        print(f"   Team ID {opp_id} not in training data.")
        print(f"   Available: {', '.join(known)}")
        return

    opp_abbr = _MLB_TEAM_MAP.get(opp_id, str(opp_id))

    if is_pitcher:
        header_label = f"LINEUP OFFENSE: {opp_abbr}  (what their batters produce vs pitchers)"
        weak_label   = "⚠  HIGH  "   # high offensive output = tough for pitcher
        tough_label  = "✓  LOW   "
        weak_note    = "⚠ HIGH = potent lineup (bad for pitcher Overs like K, OUTS)"
        tough_note   = "✓ LOW  = weak lineup (favours pitcher Overs)"
    else:
        header_label = f"PITCHING MATCHUP: {opp_abbr}  (how many batter stats they allow)"
        weak_label   = "⚠  WEAK  "   # weak pitching = allows lots of hits/HR = good for batter Overs
        tough_label  = "✓  TOUGH "
        weak_note    = "⚠ WEAK = leaky pitching  →  favours batter Over bets"
        tough_note   = "✓ TOUGH = stingy pitching  →  favours batter Under bets"

    print(f"\n{'─' * 65}")
    print(f"   {header_label}")
    print(f"   (rank 1 = most produced / WEAK pitching  {n} = fewest / TOUGH)")
    print(f"{'─' * 65}")
    print(f"   {'STAT':<5} {'PER GAME':>8} {'LG AVG':>7} {'DIFF':>6} {'RANK':>5}  VERDICT")
    print(f"{'─' * 65}")

    for stat in stats:
        if stat not in avgs.columns:
            continue
        allowed = avgs.loc[opp_id, stat]
        league  = lg_avg[stat]
        diff    = allowed - league
        rank    = int(ranks.loc[opp_id, stat])
        pct     = rank / n   # low rank (near 1) = most produced = weak pitching

        if pct <= 0.27:
            verdict = weak_label
        elif pct >= 0.77:
            verdict = tough_label
        else:
            verdict = "   avg   "

        print(f"   {stat:<5} {allowed:>8.3f} {league:>7.3f} {diff:>+6.3f} {rank:>5}  {verdict}(#{rank}/{n})")

    print(f"{'─' * 65}")
    print(f"   {weak_note}")
    print(f"   {tough_note}")
    print(f"   SO/BB shown from batter perspective (SO = batter strikeout)")


def startup_pipeline_check():
    batter_model  = os.path.join(_BASE, 'models', 'mlb', 'H_model.json')
    pitcher_model = os.path.join(_BASE, 'models', 'mlb', 'K_model.json')
    batter_data   = os.path.join(_BASE, 'data',   'mlb', 'processed', 'batter_training.csv')
    pitcher_data  = os.path.join(_BASE, 'data',   'mlb', 'processed', 'pitcher_training.csv')

    print("\n" + "=" * 55)
    print("   MLB STARTUP CHECK")
    print("=" * 55)

    models_ready = os.path.exists(batter_model) and os.path.exists(pitcher_model)
    data_ready   = os.path.exists(batter_data) and os.path.exists(pitcher_data)

    if not data_ready:
        print("   Data:   NOT FOUND — run Option 2 (Build Data) then Option 3")
    else:
        print("   Data:   ✅  Ready")

    if not models_ready:
        print("   Models: NOT FOUND — run Option 3 (Engineer Features) then Option 4")
    else:
        age_days = (datetime.now().timestamp() - os.path.getmtime(batter_model)) / 86400
        status   = "OK" if age_days < 14 else f"STALE ({age_days:.0f}d old)"
        print(f"   Models: ✅  Ready [{status}]")

    print("=" * 55)


def main_menu():
    startup_pipeline_check()

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')

        print("\n" + "=" * 55)
        print("   ⚾ MLB EV BOT")
        print("=" * 55)
        print(f"   {datetime.now().strftime('%A, %B %d, %Y')}")
        print("=" * 55)

        print("\nANALYSIS")
        print("1. AI Scanner            -- Today's MLB props vs AI")
        print("6. Player Search         -- All props for a specific player")

        print("\nSETUP  (run once in order)")
        print("2. Build Data            -- Download batting + pitching logs")
        print("3. Engineer Features     -- Build rolling-average features")
        print("4. Train Models          -- Train XGBoost models")

        print("\nREPORTING")
        print("5. Model Metrics         -- Accuracy by stat")

        print("\n" + "=" * 55)
        print("0. Back")
        print("=" * 55)

        choice = input("\nSelect: ").strip()

        if   choice == '1': run_scanner()
        elif choice == '2': run_builder()
        elif choice == '3': run_feature_engineering()
        elif choice == '4': run_training()
        elif choice == '5': view_metrics()
        elif choice == '6': search_player()
        elif choice == '0': break
        else:
            print("\nInvalid selection.")
            input("Press Enter to try again...")


if __name__ == "__main__":
    main_menu()
