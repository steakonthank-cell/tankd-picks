"""
WNBA Feature Engineering Pipeline

Transforms raw WNBA game logs into ML-ready training data.
Defensive matchup features (OPP_PACE_L5, OPP_DEF_RTG_L5, OPP_{STAT}_ALLOWED)
are built in from the start.

Key differences from NBA pipeline:
    - L5 / L10 windows (WNBA season = ~40 games, not 82)
    - No 1st-half box scores (not available via nba_api WNBA)
    - Shorter EWMA spans (span=7 for recent, span=20 for season)
    - 5-game min for rolling (vs NBA's 10)

Output:
    data/wnba/processed/training_dataset.csv

Usage:
    $ python3 -m src.sports.wnba.features
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOGS_FILE     = os.path.join(BASE_DIR, 'data', 'wnba', 'raw',       'raw_game_logs.csv')
POS_FILE      = os.path.join(BASE_DIR, 'data', 'wnba', 'processed', 'player_positions.csv')
OUTPUT_FILE   = os.path.join(BASE_DIR, 'data', 'wnba', 'processed', 'training_dataset.csv')

TARGET_STATS = ['PTS', 'REB', 'AST', 'FG3M', 'STL', 'TOV', 'FGM', 'FTM',
                'DREB', 'OREB', 'FPTS', 'PRA', 'PR', 'PA', 'RA', 'SB']


# ---------------------------------------------------------------------------
# Load & merge
# ---------------------------------------------------------------------------

def load_and_merge():
    print("...Loading data")
    if not os.path.exists(LOGS_FILE):
        print(f"❌  {LOGS_FILE} not found. Run builder.py first.")
        return None

    df = pd.read_csv(LOGS_FILE, low_memory=False)
    df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'], errors='coerce')
    df = df.dropna(subset=['GAME_DATE', 'MATCHUP']).copy()
    df = df.sort_values(['PLAYER_ID', 'GAME_DATE']).reset_index(drop=True)

    # Merge positions
    if os.path.exists(POS_FILE):
        pos = pd.read_csv(POS_FILE)
        df = df.merge(pos[['PLAYER_ID', 'POSITION']], on='PLAYER_ID', how='left')
        df['POSITION'] = df['POSITION'].fillna('Unknown')
    else:
        df['POSITION'] = 'Unknown'

    # Combo stats
    df['FPTS'] = (df['PTS'] * 1.0 + df['REB'] * 1.2 + df['AST'] * 1.5
                  + df.get('BLK', pd.Series(0, index=df.index)) * 3
                  + df.get('STL', pd.Series(0, index=df.index)) * 3
                  - df.get('TOV', pd.Series(0, index=df.index)))
    df['PRA'] = df['PTS'] + df['REB'] + df['AST']
    df['PR']  = df['PTS'] + df['REB']
    df['PA']  = df['PTS'] + df['AST']
    df['RA']  = df['REB'] + df['AST']
    df['SB']  = df.get('STL', 0) + df.get('BLK', 0)

    if 'DREB' not in df.columns and all(c in df.columns for c in ['REB', 'OREB']):
        df['DREB'] = (df['REB'] - df['OREB']).clip(lower=0)
    elif 'DREB' not in df.columns:
        df['DREB'] = 0
    if 'OREB' not in df.columns:
        df['OREB'] = 0

    print(f"   Loaded {len(df):,} rows  |  {df['PLAYER_ID'].nunique():,} players")
    return df


# ---------------------------------------------------------------------------
# Context features
# ---------------------------------------------------------------------------

def add_context(df):
    print("...Adding context features")
    df = df.copy()
    df['IS_HOME']   = df['MATCHUP'].str.contains(r'vs\.', na=False).astype(int)
    df['OPPONENT']  = df['MATCHUP'].str.split().str[-1]
    df['DAYS_REST'] = df.groupby('PLAYER_ID')['GAME_DATE'].diff().dt.days.fillna(3).clip(upper=7)
    df['IS_B2B']    = (df['DAYS_REST'] == 1).astype(int)
    df['IS_FRESH']  = (df['DAYS_REST'] >= 3).astype(int)
    if 'WL' in df.columns:
        df['TEAM_WIN'] = (df['WL'] == 'W').astype(int)
        df['OPP_WIN_PCT'] = 1.0 - df.groupby(['OPPONENT', 'SEASON_ID'])['TEAM_WIN'].transform(
            lambda x: x.shift(1).expanding(min_periods=1).mean()).fillna(0.5)
    else:
        df['OPP_WIN_PCT'] = 0.5
    return df


# ---------------------------------------------------------------------------
# Rolling averages (L5, L10, L15, Season)
# ---------------------------------------------------------------------------

def add_rolling(df):
    print("...Calculating rolling averages")
    df = df.copy()
    df['CAREER_GAMES'] = df.groupby('PLAYER_ID').cumcount() + 1

    stats = [s for s in TARGET_STATS + ['MIN', 'FGA', 'FTA', 'OREB']
             if s in df.columns]
    stats = list(dict.fromkeys(stats))

    # Mask low-minute stints (< 5 min) to avoid DNP pollution
    qualified = df.copy()
    qualified.loc[qualified['MIN'] < 5, stats] = float('nan')
    grp = qualified.groupby('PLAYER_ID')

    cols = {}
    for stat in stats:
        cols[f'{stat}_L5']     = grp[stat].transform(lambda x: x.shift(1).rolling(5,  min_periods=3).mean())
        cols[f'{stat}_L10']    = grp[stat].transform(lambda x: x.shift(1).rolling(10, min_periods=5).mean())
        cols[f'{stat}_L15']    = grp[stat].transform(lambda x: x.shift(1).rolling(15, min_periods=7).mean())
        cols[f'{stat}_Season'] = grp[stat].transform(lambda x: x.shift(1).ewm(span=20, min_periods=1, adjust=False).mean())
        cols[f'{stat}_L5_Median']  = grp[stat].transform(lambda x: x.shift(1).rolling(5,  min_periods=3).median())
        cols[f'{stat}_L10_Median'] = grp[stat].transform(lambda x: x.shift(1).rolling(10, min_periods=5).median())

    df = pd.concat([df, pd.DataFrame(cols, index=df.index)], axis=1)
    return df


# ---------------------------------------------------------------------------
# Pace features
# ---------------------------------------------------------------------------

def add_pace(df):
    print("...Calculating team pace")
    df = df.copy()
    if not all(c in df.columns for c in ['FGA', 'FTA', 'TOV', 'MIN']):
        return df
    oreb = df['OREB'] if 'OREB' in df.columns else 0
    df['POSS_EST'] = (df['FGA'] + 0.44 * df['FTA'] - oreb + df['TOV']).clip(lower=1)
    df['PACE_PER_40'] = (df['POSS_EST'] / df['MIN'].replace(0, 0.1) * 40).clip(0, 200)
    team_pace = df.groupby(['TEAM_ID', 'GAME_ID']).agg(
        PACE_PER_40=('PACE_PER_40', 'mean'), GAME_DATE=('GAME_DATE', 'first')
    ).reset_index().sort_values(['TEAM_ID', 'GAME_DATE'])
    team_pace['PACE_ROLLING'] = team_pace.groupby('TEAM_ID')['PACE_PER_40'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    df = df.merge(team_pace[['GAME_ID', 'TEAM_ID', 'PACE_ROLLING']], on=['GAME_ID', 'TEAM_ID'], how='left')
    df['PACE_ROLLING'] = df['PACE_ROLLING'].fillna(df['PACE_ROLLING'].median())
    df.drop(columns=['POSS_EST', 'PACE_PER_40'], errors='ignore', inplace=True)
    return df


# ---------------------------------------------------------------------------
# Defense vs position  (OPP_{STAT}_ALLOWED, L5 rolling)
# ---------------------------------------------------------------------------

def add_defense_vs_position(df):
    print("...Calculating defense vs. position (L5)")
    df = df.copy()
    available = [s for s in TARGET_STATS if s in df.columns]
    cols = {}
    for stat in available:
        col = f'OPP_{stat}_ALLOWED'
        cols[col] = df.groupby(['OPPONENT', 'POSITION'])[stat].transform(
            lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    df = pd.concat([df, pd.DataFrame(cols, index=df.index)], axis=1)

    # Normalize vs. league-position median
    for stat in available:
        col = f'OPP_{stat}_ALLOWED'
        lg_avg = df.groupby(['POSITION', 'SEASON_ID'])[stat].transform('median')
        df[col] = df[col].fillna(lg_avg)
        df[f'{col}_DIFF'] = df[col] - lg_avg

    return df


# ---------------------------------------------------------------------------
# Opponent pace & defensive rating  (OPP_PACE_L5, OPP_DEF_RTG_L5)
# ---------------------------------------------------------------------------

def add_opp_pace_defrtg(df):
    print("...Calculating opponent pace & defensive rating")
    df = df.copy()
    req = ['FGA', 'FTA', 'OREB', 'TOV', 'PTS', 'TEAM_ID', 'GAME_ID', 'GAME_DATE']
    if not all(c in df.columns for c in req):
        return df

    tg = df.groupby(['TEAM_ID', 'GAME_ID', 'GAME_DATE']).agg(
        T_FGA=('FGA', 'sum'), T_FTA=('FTA', 'sum'),
        T_OREB=('OREB', 'sum'), T_TOV=('TOV', 'sum'), T_PTS=('PTS', 'sum'),
    ).reset_index()
    tg['T_POSS'] = (tg['T_FGA'] + 0.44 * tg['T_FTA'] - tg['T_OREB'] + tg['T_TOV']).clip(lower=1)

    opp = tg[['GAME_ID', 'TEAM_ID', 'T_POSS', 'T_PTS']].rename(columns={
        'TEAM_ID': 'OPP_TEAM_ID', 'T_POSS': 'OPP_POSS', 'T_PTS': 'OPP_T_PTS'
    })
    matchups = tg.merge(opp, on='GAME_ID').query('TEAM_ID != OPP_TEAM_ID').copy()
    matchups['GAME_DEF_RTG'] = (matchups['OPP_T_PTS'] / matchups['OPP_POSS'] * 100).clip(60, 140)

    matchups = matchups.sort_values(['TEAM_ID', 'GAME_DATE'])
    matchups['PACE_L5']    = matchups.groupby('TEAM_ID')['T_POSS'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    matchups['DEF_RTG_L5'] = matchups.groupby('TEAM_ID')['GAME_DEF_RTG'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=3).mean())

    team_stats = matchups[['GAME_ID', 'TEAM_ID', 'PACE_L5', 'DEF_RTG_L5']].drop_duplicates()
    game_opp   = matchups[['GAME_ID', 'TEAM_ID', 'OPP_TEAM_ID']].drop_duplicates()
    opp_stats  = team_stats.rename(columns={
        'TEAM_ID':    'OPP_TEAM_ID',
        'PACE_L5':    'OPP_PACE_L5',
        'DEF_RTG_L5': 'OPP_DEF_RTG_L5',
    })
    player_opp = game_opp.merge(opp_stats, on=['GAME_ID', 'OPP_TEAM_ID'], how='left')[
        ['GAME_ID', 'TEAM_ID', 'OPP_PACE_L5', 'OPP_DEF_RTG_L5']
    ]

    saved = df.index
    df    = df.reset_index(drop=True)
    df    = df.merge(player_opp, on=['GAME_ID', 'TEAM_ID'], how='left')
    df['OPP_PACE_L5']    = df['OPP_PACE_L5'].fillna(df['OPP_PACE_L5'].median())
    df['OPP_DEF_RTG_L5'] = df['OPP_DEF_RTG_L5'].fillna(df['OPP_DEF_RTG_L5'].median())
    assert len(df) == len(saved)
    df.index = saved
    return df


# ---------------------------------------------------------------------------
# Head-to-head vs opponent
# ---------------------------------------------------------------------------

def add_h2h(df):
    print("...Adding head-to-head stats")
    df = df.copy()
    for stat in ['PTS', 'REB', 'AST']:
        df[f'{stat}_VS_OPP'] = df.groupby(['PLAYER_ID', 'OPPONENT'])[stat].transform(
            lambda x: x.shift(1).expanding(min_periods=1).mean())
        sea = f'{stat}_Season'
        if sea in df.columns:
            df[f'{stat}_VS_OPP'] = df[f'{stat}_VS_OPP'].fillna(df[sea])
    return df


# ---------------------------------------------------------------------------
# Role features
# ---------------------------------------------------------------------------

def add_role(df):
    print("...Adding role features")
    df = df.copy()
    team_mins = df.groupby(['GAME_ID', 'TEAM_ID'])['MIN'].transform('sum')
    df['MIN_SHARE']   = df['MIN'] / (team_mins + 0.1)
    df['IS_STARTER']  = df.groupby(['GAME_ID', 'TEAM_ID'])['MIN'].transform(
        lambda x: (x >= x.nlargest(5).min()).astype(int))
    df['USAGE_RATE']  = (100 * (df['FGA'] + 0.44 * df.get('FTA', 0) + df.get('TOV', 0))
                         / (df['MIN'].replace(0, 0.1))).clip(0, 50)
    df['USAGE_RATE_L5'] = df.groupby('PLAYER_ID')['USAGE_RATE'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=3).mean()).fillna(20)
    df['USAGE_RATE_Season'] = df.groupby('PLAYER_ID')['USAGE_RATE'].transform(
        lambda x: x.shift(1).ewm(span=20, min_periods=1, adjust=False).mean()).fillna(20)
    return df


# ---------------------------------------------------------------------------
# Home/away splits
# ---------------------------------------------------------------------------

def add_home_away(df):
    print("...Adding home/away splits")
    df = df.copy()
    for stat in ['PTS', 'REB', 'AST', 'FG3M', 'PRA']:
        df[f'{stat}_LOC_MEAN'] = df.groupby(['PLAYER_ID', 'IS_HOME'])[stat].transform(
            lambda x: x.shift(1).expanding(min_periods=1).mean())
        sea = f'{stat}_Season'
        if sea in df.columns:
            df[f'{stat}_LOC_MEAN'] = df[f'{stat}_LOC_MEAN'].fillna(df[sea])
    return df


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

def add_momentum(df):
    print("...Adding momentum features")
    df = df.copy()
    for stat in ['PTS', 'REB', 'AST']:
        l5_col = f'{stat}_L5'
        sea_col = f'{stat}_Season'
        if l5_col in df.columns and sea_col in df.columns:
            df[f'{stat}_HOT_STREAK'] = (df[l5_col] - df[sea_col]).fillna(0)
    return df


# ---------------------------------------------------------------------------
# Quality check
# ---------------------------------------------------------------------------

def validate(df):
    print("...Running data quality checks")
    df = df.replace([np.inf, -np.inf], np.nan)
    nan_pct = df.isna().mean()
    bad = nan_pct[nan_pct > 0.6].index.tolist()
    if bad:
        print(f"   ⚠️  High NaN% columns: {bad[:10]}")
    return df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    start = datetime.now()
    print(f"\n{'='*55}")
    print("   WNBA FEATURE ENGINEERING PIPELINE")
    print(f"{'='*55}\n")

    df = load_and_merge()
    if df is None:
        return

    print("\n--- STAGE 1: CONTEXT ---")
    df = add_context(df)
    df = add_pace(df)

    print("\n--- STAGE 2: ROLLING AVERAGES ---")
    df = df.sort_values(['PLAYER_ID', 'GAME_DATE'])
    df = add_rolling(df)

    print("\n--- STAGE 3: ROLE & LOCATION ---")
    df = add_role(df)
    df = add_home_away(df)
    df = add_momentum(df)

    print("\n--- STAGE 4: DEFENSIVE MATCHUPS ---")
    df = add_defense_vs_position(df)
    df = add_opp_pace_defrtg(df)
    df = add_h2h(df)

    print("\n--- STAGE 5: QUALITY & SAVE ---")
    df = validate(df)

    # Filter low-minute games
    n0 = len(df)
    df = df[df['MIN'] >= 5]
    df = df.dropna(subset=['PTS', 'REB', 'AST'])
    print(f"   Filtered {n0 - len(df):,} rows (< 5 min or missing targets)")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'='*55}")
    print("   ✅  DONE")
    print(f"{'='*55}")
    print(f"   Rows:     {len(df):,}")
    print(f"   Features: {len(df.columns)}")
    print(f"   Players:  {df['PLAYER_ID'].nunique():,}")
    print(f"   Runtime:  {elapsed:.1f}s")
    print(f"   Output:   {OUTPUT_FILE}")
    print(f"\n   Next: python3 -m src.sports.wnba.train")


if __name__ == '__main__':
    main()
