"""
Tank'd Picks v2 — Feature Pipeline
====================================
Integrates all feature modules into the existing XGBoost scanner.
This wraps around the current scan output and enriches it with:
- Park factors
- Rest/travel fatigue
- Weather conditions
- Umpire tendencies

Usage:
    python features/pipeline.py                    # Enrich latest scan
    python features/pipeline.py --sport mlb        # MLB only
    python features/pipeline.py --csv path/to.csv  # Specific file
    
Integration with smart_picks.py:
    from features.pipeline import enrich_scan_data
    
    df = pd.read_csv("output/mlb/scans/scan_latest.csv")
    enriched = enrich_scan_data(df, sport="mlb")
"""

import os
import sys
import glob
import argparse
import pandas as pd
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from features.park_factors import get_park_factor, park_adjustment, park_edge_modifier
from features.rest_travel import get_fatigue_score, get_travel_distance
from features.weather import get_game_weather, weather_adjustment
from features.umpire_stats import umpire_adjustment, get_umpire_k_factor


def _k_matchup_mult(k_pct_vs, def_k9, side):
    """Confidence multiplier for Hitter Strikeouts (SO) props.

    K_Pct_vs and DEF_K9 are pulled into the scan CSV (scanner.py) but were
    never wired into scoring — SO props were ranked purely off the batter's
    own rolling SO/AB counts (the model's AI_Proj). Both real matchup signals
    point the same direction: a batter who whiffs more against this pitcher's
    handedness (K_Pct_vs) facing a pitcher who misses more bats than average
    (DEF_K9, the opposing SP's K/9) both raise the odds of MORE strikeouts —
    i.e. they favor Over and work against Under, and vice versa.
    """
    mult = 1.0
    is_over = str(side).strip().lower() == "over"

    if k_pct_vs is not None and not pd.isna(k_pct_vs):
        if k_pct_vs >= 28:    mult *= 1.12 if is_over else 0.88
        elif k_pct_vs >= 24:  mult *= 1.06 if is_over else 0.94
        elif k_pct_vs <= 16:  mult *= 0.88 if is_over else 1.12
        elif k_pct_vs <= 20:  mult *= 0.94 if is_over else 1.06

    if def_k9 is not None and not pd.isna(def_k9):
        if def_k9 >= 10.0:    mult *= 1.10 if is_over else 0.90
        elif def_k9 >= 9.0:   mult *= 1.05 if is_over else 0.95
        elif def_k9 <= 6.5:   mult *= 0.90 if is_over else 1.10
        elif def_k9 <= 7.5:   mult *= 0.95 if is_over else 1.05

    return round(mult, 3)


def enrich_scan_data(df: pd.DataFrame, sport: str = "mlb", game_context: dict = None) -> pd.DataFrame:
    """
    Enrich a scanner output DataFrame with v2 features.
    
    Args:
        df: Scanner CSV with columns like Player, Stat_Label/Stat, 
            Edge_Pct/AI_Edge, Score, Tier, etc.
        sport: "mlb", "wnba", or "nba"
        game_context: Optional dict with today's game metadata:
            {
                "games": [
                    {
                        "away": "NYY", "home": "BOS",
                        "umpire": "Pat Hoberg",
                        "away_prev_city": "SEA",
                        "start_time": "19:10",
                    },
                    ...
                ]
            }
    
    Returns:
        Enriched DataFrame with new columns:
        - park_factor: park factor for the relevant stat
        - park_adj: park-adjusted projection
        - fatigue_score: team fatigue (0-100)
        - fatigue_adj: fatigue multiplier
        - weather_adj: weather multiplier  
        - umpire_adj: umpire K-rate multiplier
        - v2_score: new composite score incorporating all factors
        - v2_edge: adjusted edge percentage
    """
    df = df.copy()
    
    # ─── Normalize column names across sports ───
    col_map = {
        "Stat": "stat_type",
        "Stat_Label": "stat_type", 
        "Edge_Pct": "edge",
        "AI_Edge": "edge",
        "Tier": "tier",
        "Tier_Label": "tier",
        "Score": "score",
        "AI_Proj": "ai_proj",
        "L5": "l5",
        "Avg_L10": "l10",
    }
    
    # Build working columns without clobbering existing ones
    for old_name, new_name in col_map.items():
        if old_name in df.columns and new_name not in df.columns:
            df[new_name] = df[old_name]
    
    # Ensure required columns exist
    for col in ["stat_type", "edge", "score"]:
        if col not in df.columns:
            print(f"  WARNING: Missing column '{col}', using defaults")
            df[col] = 0 if col != "stat_type" else "Unknown"
    
    # ─── Extract team from Player column or Team column ───
    if "Team" in df.columns:
        df["team"] = df["Team"].str.upper()
    elif "Player" in df.columns:
        # Try to parse team from player string if formatted as "Name (TEAM)"
        df["team"] = df["Player"].str.extract(r'\((\w+)\)', expand=False).fillna("UNK").str.upper()
    else:
        df["team"] = "UNK"
    
    # Build game lookup from context
    games = {}
    if game_context and "games" in game_context:
        for g in game_context["games"]:
            games[g.get("away", "").upper()] = g
            games[g.get("home", "").upper()] = g
    
    # ─── Apply features row by row ───
    park_factors = []
    park_adjs = []
    fatigue_scores = []
    fatigue_adjs = []
    weather_adjs = []
    umpire_adjs = []
    k_matchup_adjs = []

    for idx, row in df.iterrows():
        team = row.get("team", "UNK")
        stat = row.get("stat_type", "Unknown")
        proj = float(row.get("ai_proj", 0)) if pd.notna(row.get("ai_proj")) else 0
        
        game = games.get(team, {})
        home_team = game.get("home", team)
        home_team = "" if home_team is None or (isinstance(home_team, float)) else str(home_team)
        
        # 1. Park factors (MLB only, WNBA/NBA indoor)
        if sport.lower() == "mlb":
            pf = get_park_factor(home_team, stat)
            p_adj = park_edge_modifier(home_team, stat)
        else:
            pf = 100
            p_adj = 1.0
        
        park_factors.append(pf)
        park_adjs.append(round(p_adj, 3))
        
        # 2. Fatigue
        if game:
            fatigue = get_fatigue_score(
                team=team,
                prev_city=game.get("away_prev_city"),
                current_city=home_team if team == home_team else team,
                days_rest=game.get("days_rest", 1),
                is_day_after_night=game.get("day_after_night", False),
            )
            fatigue_scores.append(fatigue["fatigue_score"])
            fatigue_adjs.append(fatigue["adjustment"])
        else:
            fatigue_scores.append(0)
            fatigue_adjs.append(1.0)
        
        # 3. Weather (MLB only)
        if sport.lower() == "mlb":
            weather = get_game_weather(home_team)
            w_adj = weather_adjustment(weather, stat)
        else:
            w_adj = 1.0
        weather_adjs.append(round(w_adj, 3))
        
        # 4. Umpire (MLB only, K-related props)
        if sport.lower() == "mlb" and game.get("umpire"):
            u_adj = umpire_adjustment(game["umpire"], stat)
        else:
            u_adj = 1.0
        umpire_adjs.append(round(u_adj, 3))

        # 5. Batter K% (vs today's opposing pitcher hand) + opposing SP's K/9
        #    — Hitter Strikeouts (SO) props only.
        is_hitter_so = (sport.lower() == "mlb"
                         and str(row.get("Stat", "")).upper() == "SO"
                         and not bool(row.get("Is_Pitcher", False)))
        if is_hitter_so:
            k_matchup_adjs.append(_k_matchup_mult(
                row.get("K_Pct_vs"), row.get("DEF_K9"), row.get("Side", "")
            ))
        else:
            k_matchup_adjs.append(1.0)

    # ─── Add columns ───
    df["park_factor"] = park_factors
    df["park_adj"] = park_adjs
    df["fatigue_score"] = fatigue_scores
    df["fatigue_adj"] = fatigue_adjs
    df["weather_adj"] = weather_adjs
    df["umpire_adj"] = umpire_adjs
    df["k_matchup_adj"] = k_matchup_adjs

    # --- Compute base score from v1 signals ---
    df["edge"] = pd.to_numeric(df["edge"], errors="coerce").fillna(0)

    # Edge_Pct (MLB) is an *unsigned* magnitude (scanner.py's edge_pct =
    # abs(proj - line) / line). For goblin/demon alt lines, Side is forced
    # to "Over" independent of the sign of (proj - line) — PrizePicks
    # goblins/demons are Over-only markets — so a projection that lands far
    # BELOW an inflated demon line still reports a huge Edge_Pct, and the
    # score formula below saturates as if that were a strong pick (see the
    # Luke Raley HRR 4.5 case: proj 1.37 vs line 4.5 scored 64.6/DECENT).
    # Flip the sign whenever the raw (proj - line) direction disagrees with
    # the picked Side, so an unfavorable demon/goblin correctly scores low
    # instead of maxing out. No-op for regular lines (Side already agrees
    # with the raw sign there) and for formats without a raw signed "Edge"
    # column (e.g. WNBA's AI_Edge is already signed and is left untouched).
    if "Edge" in df.columns and "Side" in df.columns:
        _raw_edge = pd.to_numeric(df["Edge"], errors="coerce").fillna(0)
        _is_over  = df["Side"].astype(str).str.strip().str.lower() == "over"
        _agrees   = (_raw_edge >= 0) == _is_over
        df["edge"] = df["edge"].where(_agrees, -df["edge"])

    _con = pd.to_numeric(
        df["Con_Over"] if "Con_Over" in df.columns
        else (df["con_over"] if "con_over" in df.columns else pd.Series(50, index=df.index)),
        errors="coerce"
    ).fillna(50)
    _streak = pd.to_numeric(
        df["Streak"] if "Streak" in df.columns
        else (df["streak"] if "streak" in df.columns else pd.Series(0, index=df.index)),
        errors="coerce"
    ).fillna(0).abs()

    # Edge -> 0-45 pts | Consistency -> 0-35 pts | Streak -> 0-20 pts
    df["score"] = (
        (df["edge"].clip(0, 35) / 35 * 45) +
        (_con.clip(0, 100) / 100 * 35) +
        (_streak.clip(0, 8) / 8 * 20)
    ).clip(0, 100).round(1)

    # --- Compute v2 composite score ---
    composite_mult = df["park_adj"] * df["fatigue_adj"] * df["weather_adj"] * df["umpire_adj"] * df["k_matchup_adj"]
    df["v2_score"] = (df["score"] * composite_mult).clip(0, 100).round(1)
    df["v2_edge"] = (df["edge"] * composite_mult).round(2)
    
    # ─── Re-tier based on v2 score ───
    def v2_tier(score):
        if score >= 88:
            return "ELITE"
        elif score >= 75:
            return "STRONG"
        elif score >= 60:
            return "DECENT"
        else:
            return "LEAN"
    
    df["v2_tier"] = df["v2_score"].apply(v2_tier)
    
    return df


def get_latest_scan(sport: str) -> str:
    """Find the most recent scan CSV for a sport."""
    base = f"/root/tankd-picks/output/{sport.lower()}/scans"
    files = sorted(glob.glob(f"{base}/scan_*.csv"))
    if files:
        return files[-1]
    return None


def main():
    parser = argparse.ArgumentParser(description="Enrich scan data with v2 features")
    parser.add_argument("--sport", default="mlb", choices=["mlb", "wnba", "nba"])
    parser.add_argument("--csv", default=None, help="Path to specific CSV")
    parser.add_argument("--output", default=None, help="Output path (default: overwrite)")
    args = parser.parse_args()
    
    # Find CSV
    csv_path = args.csv or get_latest_scan(args.sport)
    if not csv_path or not os.path.exists(csv_path):
        print(f"ERROR: No scan CSV found for {args.sport}")
        sys.exit(1)
    
    print(f"Enriching: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Rows: {len(df)}")
    
    # Enrich
    enriched = enrich_scan_data(df, sport=args.sport)
    
    # Save
    out_path = args.output or csv_path.replace(".csv", "_v2.csv")
    enriched.to_csv(out_path, index=False)
    print(f"  Saved: {out_path}")
    
    # Summary
    print(f"\n=== V2 Enrichment Summary ===")
    print(f"  Original score range: {df['score'].min():.0f} - {df['score'].max():.0f}" if 'score' in df.columns else "")
    print(f"  V2 score range:       {enriched['v2_score'].min():.1f} - {enriched['v2_score'].max():.1f}")
    
    tier_counts = enriched["v2_tier"].value_counts()
    for tier in ["ELITE", "STRONG", "DECENT", "LEAN"]:
        count = tier_counts.get(tier, 0)
        if count:
            print(f"  {tier}: {count} picks")
    
    # Show top 5
    top5 = enriched.nlargest(5, "v2_score")
    print(f"\n=== Top 5 V2 Picks ===")
    cols = ["Player", "stat_type", "v2_score", "v2_edge", "v2_tier", "park_factor", "umpire_adj"]
    display_cols = [c for c in cols if c in top5.columns]
    print(top5[display_cols].to_string(index=False))


if __name__ == "__main__":
    main()
