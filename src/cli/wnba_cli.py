"""
WNBA CLI - Main Entry Point for the WNBA Props Bot

Menu:
    ANALYSIS
        1. WNBA Scanner  -- Today's WNBA props (AI + PickFinder)

    MODEL PIPELINE
        2. Build Data     -- Download game logs & positions via nba_api
        3. Engineer Features -- Build ML training dataset with defensive matchups
        4. Train Models   -- Train XGBoost models (one per target stat)
        5. View Metrics   -- Show model performance from last training run

Usage:
    Called from main.py → main_menu()
"""

import os
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
METRICS_FILE = os.path.join(BASE_DIR, 'models', 'wnba', 'model_metrics.csv')


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def run_scanner():
    try:
        from src.sports.wnba.scanner import scan_wnba
        scan_wnba()
    except ImportError as e:
        print(f"Import error: {e}")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"Scanner error: {e}")
        import traceback; traceback.print_exc()
        input("\nPress Enter to continue...")


def run_player_search():
    try:
        from src.sports.wnba.scanner import search_player
        search_player()
    except ImportError as e:
        print(f"Import error: {e}")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"Player search error: {e}")
        import traceback; traceback.print_exc()
        input("\nPress Enter to continue...")


def run_builder():
    try:
        from src.sports.wnba.builder import main as builder_main
        builder_main()
    except ImportError as e:
        print(f"Import error: {e}")
    except Exception as e:
        print(f"Builder error: {e}")
        import traceback; traceback.print_exc()
    input("\nPress Enter to continue...")


def run_features():
    try:
        from src.sports.wnba.features import main as features_main
        features_main()
    except ImportError as e:
        print(f"Import error: {e}")
    except Exception as e:
        print(f"Features error: {e}")
        import traceback; traceback.print_exc()
    input("\nPress Enter to continue...")


def run_train():
    try:
        from src.sports.wnba.train import train_and_evaluate
        train_and_evaluate()
    except ImportError as e:
        print(f"Import error: {e}")
    except Exception as e:
        print(f"Training error: {e}")
        import traceback; traceback.print_exc()
    input("\nPress Enter to continue...")


def view_metrics():
    import pandas as pd
    if not os.path.exists(METRICS_FILE):
        print("\n   No metrics file found.")
        print(f"   Expected: {METRICS_FILE}")
        print("   Run option 4 (Train Models) first.")
        input("\nPress Enter to continue...")
        return

    df = pd.read_csv(METRICS_FILE)
    print(f"\n{'='*65}")
    print("   WNBA MODEL METRICS")
    print(f"{'='*65}")
    print(f"\n   Last trained: {df['trained_at'].max()}")
    print(f"\n{'─'*65}")
    print(f"   {'TARGET':<8} {'TIER':<8} {'MAE':>6} {'R²':>7} {'DIR%':>6} {'ROWS':>7} {'FEATS':>6}")
    print(f"{'─'*65}")

    tier_order = {'ELITE': 0, 'STRONG': 1, 'DECENT': 2, 'RISKY': 3, 'UNKNOWN': 4}
    df_sorted = df.sort_values('tier', key=lambda s: s.map(tier_order).fillna(4))

    for _, row in df_sorted.iterrows():
        tier = row.get('tier', 'UNKNOWN')
        log_s = ' [log]' if row.get('log_transform') else ''
        print(
            f"   {str(row['target']):<8} {tier:<8} "
            f"{float(row['mae']):>6.3f} {float(row['r2']):>7.4f} "
            f"{float(row['dir_accuracy']):>5.1f}% "
            f"{int(row['train_rows']):>7,} "
            f"{int(row['features']):>6}{log_s}"
        )

    print(f"{'─'*65}")
    n = len(df)
    avg_mae = df['mae'].mean()
    avg_dir = df['dir_accuracy'].mean()
    print(f"   {n} models  |  Avg MAE: {avg_mae:.3f}  |  Avg DIR: {avg_dir:.1f}%")
    print(f"{'='*65}")
    input("\nPress Enter to continue...")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def main_menu():
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')

        # Check pipeline status
        data_ok   = os.path.exists(os.path.join(BASE_DIR, 'data',   'wnba', 'raw',       'raw_game_logs.csv'))
        feats_ok  = os.path.exists(os.path.join(BASE_DIR, 'data',   'wnba', 'processed', 'training_dataset.csv'))
        models_ok = os.path.exists(os.path.join(BASE_DIR, 'models', 'wnba', 'PTS_model.json'))

        data_s   = "✅" if data_ok   else "⚪"
        feats_s  = "✅" if feats_ok  else "⚪"
        models_s = "✅" if models_ok else "⚪"

        print("\n" + "=" * 55)
        print("   🏀 WNBA PROPS BOT")
        print("=" * 55)
        print(f"   {datetime.now().strftime('%A, %B %d, %Y')}")
        print(f"   Pipeline: Data {data_s}  Features {feats_s}  Models {models_s}")
        print("=" * 55)

        print("\nANALYSIS")
        print("1. WNBA Scanner       -- Today's props (AI + PickFinder)")
        print("6. Player Search      -- Look up any player's props & ratings")

        print("\nMODEL PIPELINE")
        print(f"2. Build Data          {data_s}  Download game logs (5–10 min)")
        print(f"3. Engineer Features   {feats_s}  Build training dataset")
        print(f"4. Train Models        {models_s}  Train XGBoost models")
        print( "5. View Metrics           Show model performance")

        print("\n" + "=" * 55)
        print("0. Back")
        print("=" * 55)

        choice = input("\nSelect: ").strip()

        if   choice == '1': run_scanner()
        elif choice == '2': run_builder()
        elif choice == '3': run_features()
        elif choice == '4': run_train()
        elif choice == '5': view_metrics()
        elif choice == '6': run_player_search()
        elif choice == '0': break
        else:
            print("\nInvalid selection.")
            input("Press Enter to try again...")


if __name__ == "__main__":
    main_menu()
