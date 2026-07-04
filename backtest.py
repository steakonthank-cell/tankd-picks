#!/usr/bin/env python3
"""
backtest.py — Steps 2+3 of MONEYLINE_TODO.md.

Builds pre-game Pythagorean features from game_outcomes.csv (NO same-game data),
runs a TIME-ORDERED walk-forward backtest, and asserts no leakage.

Pythagorean win expectation per team (exponent 1.83) is computed from each team's
runs-scored / runs-allowed BEFORE the current game, via expanding-sum shifted by 1.
The prediction for each game: P(home win) from home & away pre-game pythag.

Usage:
    python3 backtest.py            # full report, no file written
    python3 backtest.py --write    # also writes graded predictions CSV
"""
import sys, os
import numpy as np
import pandas as pd

OUTCOMES = "data/mlb/processed/game_outcomes.csv"
PRED_OUT = "data/mlb/processed/backtest_preds.csv"
EXP = 1.83
MIN_TRAIN_GAMES = 200   # skip earliest test games with too little league history


def long_form(df):
    """One row per (game, team-perspective) with runs scored/allowed and is_home."""
    home = pd.DataFrame({
        "date": df["date"], "game_pk": df["game_pk"],
        "team_id": df["home_team_id"], "rs": df["home_score"], "ra": df["away_score"],
        "is_home": 1,
    })
    away = pd.DataFrame({
        "date": df["date"], "game_pk": df["game_pk"],
        "team_id": df["away_team_id"], "rs": df["away_score"], "ra": df["home_score"],
        "is_home": 0,
    })
    lf = pd.concat([home, away], ignore_index=True)
    # stable order: by date, then game_pk, so shift(1) means "previous game chronologically"
    return lf.sort_values(["team_id", "date", "game_pk"]).reset_index(drop=True)


def add_pregame_pythag(lf):
    """For each team, expanding RS/RA totals BEFORE this game (shift 1)."""
    g = lf.groupby("team_id", group_keys=False)
    lf["rs_prior"] = g["rs"].apply(lambda s: s.expanding().sum().shift(1))
    lf["ra_prior"] = g["ra"].apply(lambda s: s.expanding().sum().shift(1))
    lf["gp_prior"] = g.cumcount()  # games played before this one
    denom = lf["rs_prior"] ** EXP + lf["ra_prior"] ** EXP
    lf["pythag"] = np.where(denom > 0, lf["rs_prior"] ** EXP / denom, np.nan)
    return lf


def assemble(df):
    """Build per-game feature matrix from the long-form pre-game pythag."""
    lf = add_pregame_pythag(long_form(df))
    home = lf[lf["is_home"] == 1][["game_pk", "pythag", "gp_prior", "rs_prior", "ra_prior"]]
    away = lf[lf["is_home"] == 0][["game_pk", "pythag", "gp_prior", "rs_prior", "ra_prior"]]
    home = home.rename(columns=lambda c: "home_" + c if c != "game_pk" else c)
    away = away.rename(columns=lambda c: "away_" + c if c != "game_pk" else c)
    m = df.merge(home, on="game_pk").merge(away, on="game_pk")
    # pythag diff is the single model feature; positive favors home
    m["pythag_diff"] = m["home_pythag"] - m["away_pythag"]
    return m.sort_values(["date", "game_pk"]).reset_index(drop=True)


def leakage_asserts(m):
    """Refuse to proceed if any feature could encode the game's own result."""
    print("  === LEAKAGE ASSERTS ===")
    # 1) prior counts must never include the current game
    #    a team's first-ever game must have gp_prior == 0 and NaN pythag
    firsts = m[(m["home_gp_prior"] == 0)]
    assert firsts["home_pythag"].isna().all(), "home first game has non-null pythag (LEAK)"
    # 2) feature/label correlation sanity — nothing should be near-perfect
    feats = ["pythag_diff", "home_pythag", "away_pythag",
             "home_gp_prior", "away_gp_prior"]
    y = m["home_win"]
    corr = m[feats].apply(lambda c: c.corr(y)).abs().sort_values(ascending=False)
    print("  |feature-vs-home_win| correlation:")
    for k, v in corr.items():
        flag = "  <-- SUSPICIOUS" if v > 0.5 else ""
        print(f"    {k:18s} {v:.3f}{flag}")
    assert corr.max() <= 0.6, "a feature correlates >0.6 with label — likely leakage"
    # 3) scores themselves must NOT be among features
    assert "home_score" not in feats and "away_score" not in feats
    print("  asserts passed.\n")


def walk_forward(m):
    """Time-ordered eval. Pythag needs no fitting; we just require prior history
    on both sides and grade chronologically. (Classifier comes only if pythag
    underperforms, per Step 3.)"""
    # require both teams to have enough prior games for a stable pythag
    usable = m.dropna(subset=["pythag_diff"]).copy()
    usable = usable[(usable["home_gp_prior"] >= 10) & (usable["away_gp_prior"] >= 10)]
    # also drop the very early league window
    usable = usable[usable.index >= MIN_TRAIN_GAMES]

    usable["pred_home_win"] = (usable["pythag_diff"] > 0).astype(int)
    # map pythag_diff to a probability via logistic-ish squash for calibration view
    usable["p_home"] = 1 / (1 + np.exp(-4.0 * usable["pythag_diff"]))

    acc = (usable["pred_home_win"] == usable["home_win"]).mean()
    base = usable["home_win"].mean()
    n = len(usable)

    # calibration: bin p_home, compare to actual home-win rate
    bins = pd.cut(usable["p_home"], np.linspace(0, 1, 11))
    cal = usable.groupby(bins, observed=True).agg(
        n=("home_win", "size"),
        pred=("p_home", "mean"),
        actual=("home_win", "mean"),
    )
    return usable, acc, base, n, cal


def main():
    if not os.path.exists(OUTCOMES):
        sys.exit(f"missing {OUTCOMES} — run build_game_outcomes.py --write first")
    df = pd.read_csv(OUTCOMES)
    print(f"  loaded {len(df):,} games  {df['date'].min()} -> {df['date'].max()}\n")

    m = assemble(df)
    leakage_asserts(m)

    usable, acc, base, n, cal = walk_forward(m)
    print(f"  graded {n:,} games (both teams >=10 prior games)")
    print(f"  pythag straight-up accuracy: {acc:.3f}")
    print(f"  home-win base rate:          {base:.3f}")
    print(f"  edge over base:              {acc - base:+.3f}")
    print(f"\n  >>> SANITY: MLB moneyline models live ~0.55-0.58 straight-up.")
    print(f"      >0.62 means leakage. ~0.50 means no signal yet.\n")
    print("  === CALIBRATION (pred prob vs actual home-win rate) ===")
    print(cal.to_string())

    print("\n  NOTE: this is Step 3 (accuracy/calibration). Step 4 — beating the")
    print("  CLOSING LINE on ROI — is the real gate and needs historical odds,")
    print("  which aren't in game_outcomes.csv. Straight-up accuracy is necessary")
    print("  but NOT sufficient to deploy.\n")

    if "--write" in sys.argv:
        cols = ["date", "game_pk", "home_team_id", "away_team_id",
                "pythag_diff", "p_home", "pred_home_win", "home_win"]
        usable[cols].to_csv(PRED_OUT, index=False)
        print(f"  WROTE -> {PRED_OUT}  ({len(usable):,} graded games)")
    else:
        print("  (no file written — re-run with --write to save graded preds.)")


if __name__ == "__main__":
    main()