"""
Standalone calibration backtest for the MLB Sim Explorer's win% output.

Read-only / additive: does NOT modify game_sim.py, game_sim_live.py, app.py,
scan CSVs, Discord, or cron. Writes its own output files
(sim_backtest_calibration_games.csv, sim_backtest_calibration_summary.txt)
in this repo's root and touches nothing else.

Method
------
For a sample of real, COMPLETED MLB games, this script re-runs the exact
same matchup-building pipeline the live Sim Explorer uses
(game_sim.py + game_sim_live.py — no reimplemented rate/shrinkage/blend/
simulation logic), but with `as_of_date` set to each game's own date
instead of "today". Every rate lookup those functions do
(compute_batter_pa_rates, compute_pitcher_pa_rates, build_matchup_lineups's
name_to_id matching) filters on `date < as_of_date`, so the sim only ever
sees data that predates the game — it genuinely does not know the outcome
it's being asked to predict.

"Real lineup/starter" ground truth: the live app uses *today's* live-posted
lineup/probable-pitcher feed, which doesn't exist for past dates. Instead,
for each historical game this script pulls the actual starter (is_starter==1
that date) and the actual batters who appeared (by AB, since this dataset
has no batting-order column — the same gap the live app's "presumed"
fallback already has) straight from this repo's own
batter_training.csv / pitcher_training.csv for that exact date. That's
real, better-than-presumed information about *who played*; it is never
used to look up *how well* they played that day (all rates still come
from the strict trailing window before the game).

Sample & date range
--------------------
Real historical outcomes (final score, winner) come from the MLB Stats API
schedule endpoint. That endpoint is reachable from this sandbox but is
aggressively rate-limited — bursts of requests start returning HTTP 406
within a few calls; single well-spaced requests to arbitrary past dates
succeed. So this script throttles schedule fetches to one per ~6-9s with
retry/backoff, which bounds how many distinct dates are practical to pull
in one run.

Date range picked: 2026-05-16 through 2026-06-14 (30 days), ending the day
before this repo's training data cutoff (batter/pitcher_training.csv both
end 2026-06-15) so every game's trailing-window rates are computed from a
genuinely distinct prior window, not a frozen "as of the data cutoff"
value. All games in the window are used (no further subsampling) so the
result isn't a cherry-picked slice. 30 days (the low end of the "30-60
days" range) was chosen over a longer window purely for runtime: at
~2000 Monte Carlo trials/game plus a throttled ~7s/day schedule fetch,
~30 days of MLB's ~15 games/day (~450 games) already takes on the order
of 40 minutes end to end in this sandbox.
"""

from __future__ import annotations

import os
import sys
import time
import random
from datetime import date as date_cls, timedelta

import numpy as np
import pandas as pd
import requests

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)

from src.sports.mlb import game_sim as gs
from src.sports.mlb import game_sim_live as gsl

START_DATE = date_cls(2026, 5, 16)
END_DATE = date_cls(2026, 6, 14)
N_TRIALS = 2000  # live app defaults to 5000; 2000 trades some precision for
                 # runtime across ~600 games (~4.5s/game at 2000 vs ~13s at 5000)

GAMES_OUT = os.path.join(_BASE, "sim_backtest_calibration_games.csv")
SUMMARY_OUT = os.path.join(_BASE, "sim_backtest_calibration_summary.txt")

_http = requests.Session()
_http.headers.update({"User-Agent": "Mozilla/5.0"})


# ---------------------------------------------------------------------------
# Historical schedule + real final outcomes
# ---------------------------------------------------------------------------

def fetch_schedule(date_str: str, max_retries: int = 5, base_delay: float = 6.0) -> dict | None:
    """Fetch one date's schedule with retry/backoff — the MLB Stats API
    endpoint this sandbox can reach rate-limits bursts of requests (HTTP
    406), so failures back off and retry rather than giving up immediately."""
    for attempt in range(max_retries):
        try:
            r = _http.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": date_str},
                timeout=12,
            )
            if r.status_code == 200:
                return r.json()
            wait = base_delay * (attempt + 1)
            print(f"  [{date_str}] HTTP {r.status_code}, retrying in {wait:.0f}s "
                  f"(attempt {attempt + 1}/{max_retries})...")
            time.sleep(wait)
        except Exception as e:
            print(f"  [{date_str}] fetch error: {e}, retrying...")
            time.sleep(base_delay)
    print(f"  [{date_str}] FAILED after {max_retries} attempts — skipping this date.")
    return None


def get_completed_games(start: date_cls, end: date_cls) -> list[dict]:
    """Real completed (status == Final) MLB games with final scores, one
    schedule call per date, network-throttled to avoid the rate limit."""
    games = []
    d = start
    n_days = (end - start).days + 1
    i = 0
    while d <= end:
        i += 1
        ds = d.strftime("%Y-%m-%d")
        print(f"[{i}/{n_days}] fetching schedule for {ds}...")
        payload = fetch_schedule(ds)
        if payload:
            dates = payload.get("dates", [])
            raw_games = dates[0].get("games", []) if dates else []
            n_final = 0
            for g in raw_games:
                if g.get("status", {}).get("detailedState") != "Final":
                    continue
                home, away = g["teams"]["home"], g["teams"]["away"]
                if "score" not in home or "score" not in away:
                    continue
                games.append({
                    "game_pk": g.get("gamePk"),
                    "date": ds,
                    "home_team_id": home["team"]["id"],
                    "home_team_name": home["team"]["name"],
                    "away_team_id": away["team"]["id"],
                    "away_team_name": away["team"]["name"],
                    "home_score": home["score"],
                    "away_score": away["score"],
                    "home_win": bool(home.get("isWinner")),
                })
                n_final += 1
            print(f"    {n_final} completed games")
        d += timedelta(days=1)
        time.sleep(random.uniform(6, 9))  # stay under the rate limit
    return games


# ---------------------------------------------------------------------------
# Ground-truth "who actually played" for a historical game (real, not
# presumed — but never used to look up that day's own performance)
# ---------------------------------------------------------------------------

def _actual_starter_name(pdf: pd.DataFrame, team_id: int, game_date: str) -> str | None:
    d = pdf[(pdf["team_id"] == team_id) & (pdf["date"] == game_date) & (pdf["is_starter"] == 1)]
    if d.empty:
        return None
    return d.iloc[0]["player_name"]


def _actual_batters(bdf: pd.DataFrame, team_id: int, game_date: str, n: int = 9) -> list[dict]:
    d = bdf[(bdf["team_id"] == team_id) & (bdf["date"] == game_date)]
    if d.empty:
        return []
    d = d.sort_values("AB", ascending=False).head(n)
    return d.to_dict("records")


def _build_bat_orders(away_batters, away_team_name, home_batters, home_team_name) -> dict:
    """Same shape build_matchup_lineups() expects from mlb_context's live
    bat_orders dict — {norm_name: {"team": ..., "bat_order": ...}} — just
    populated from the real historical box score instead of a live feed."""
    bat_orders = {}
    for i, b in enumerate(away_batters):
        bat_orders[gsl._norm(b["player_name"])] = {"team": away_team_name, "bat_order": i + 1}
    for i, b in enumerate(home_batters):
        bat_orders[gsl._norm(b["player_name"])] = {"team": home_team_name, "bat_order": i + 1}
    return bat_orders


# ---------------------------------------------------------------------------
# Matchup building — mirrors app.py's _load_sim_matchup glue exactly,
# reusing the same game_sim.py / game_sim_live.py functions the live Sim
# Explorer calls, just parameterized by the game's own historical date
# instead of "today".
# ---------------------------------------------------------------------------

_league_avg_cache: dict[str, dict] = {}


def _league_averages_cached(bdf, pdf, as_of):
    if as_of not in _league_avg_cache:
        _league_avg_cache[as_of] = gs.compute_league_averages(bdf, pdf, as_of)
    return _league_avg_cache[as_of]


def build_historical_matchup(bdf, pdf, game: dict) -> dict | None:
    as_of = game["date"]
    away_id, home_id = game["away_team_id"], game["home_team_id"]

    away_batters = _actual_batters(bdf, away_id, as_of)
    home_batters = _actual_batters(bdf, home_id, as_of)
    if len(away_batters) < 5 or len(home_batters) < 5:
        return None  # too few real batters on record for this date — skip rather than guess

    away_name = gsl.team_name(away_id)
    home_name = gsl.team_name(home_id)
    bat_orders = _build_bat_orders(away_batters, away_name, home_batters, home_name)

    lineups = gsl.build_matchup_lineups(away_id, home_id, as_of, bdf, pdf, {}, bat_orders)
    if len(lineups["away"]["lineup"]) < 5 or len(lineups["home"]["lineup"]) < 5:
        return None

    away_starter_name = _actual_starter_name(pdf, away_id, as_of)
    home_starter_name = _actual_starter_name(pdf, home_id, as_of)
    away_probable = {"name": away_starter_name} if away_starter_name else None
    home_probable = {"name": home_starter_name} if home_starter_name else None
    away_sp = gsl.resolve_starter(pdf, away_id, as_of, away_probable)
    home_sp = gsl.resolve_starter(pdf, home_id, as_of, home_probable)

    lg = _league_averages_cached(bdf, pdf, as_of)

    home_park = gsl.team_park_abbr(home_id)
    weather = gsl.build_weather_dict(None)  # no live weather feed for historical dates —
                                             # neutral default, same fallback the live app
                                             # itself uses when no context is available
    umpire = gsl.resolve_umpire(gsl.team_park_abbr(away_id), home_park)  # always None for
                                             # historical dates (umpire lookup is a live-only
                                             # stub) — reused as-is, not faked

    def _build_side(batters, opp_sp):
        rates_list, ids = [], []
        opp_pid = opp_sp.get("player_id") if opp_sp else None
        presp = gs.compute_pitcher_pa_rates(pdf, opp_pid, as_of, bdf, window=10) if opp_pid else None
        p_rates, n_p = presp if presp is not None else (lg["batter"], 0)
        p_shrunk = gs.shrink_distribution(p_rates, n_p, lg["batter"], gs.PITCHER_K)

        for b in batters:
            bres = gs.compute_batter_pa_rates(bdf, b["player_id"], as_of, window=20)
            if bres is None:
                rates_list.append(lg["batter"])
            else:
                b_rates, n_b = bres
                b_shrunk = gs.shrink_distribution(b_rates, n_b, lg["batter"], gs.BATTER_K)
                blended = gs.blend_matchup(b_shrunk, p_shrunk, lg["batter"])
                rates_list.append(gs.apply_context_multipliers(blended, home_park, weather, umpire))
            ids.append(b["player_id"])
        return rates_list, ids

    away_rates, away_ids = _build_side(lineups["away"]["lineup"], home_sp)
    home_rates, home_ids = _build_side(lineups["home"]["lineup"], away_sp)

    return {
        "away_rates": away_rates, "away_ids": away_ids,
        "home_rates": home_rates, "home_ids": home_ids,
    }


# ---------------------------------------------------------------------------
# Calibration bucketing
# ---------------------------------------------------------------------------

def bucket_label(pct: float) -> str:
    lo = int(pct // 10) * 10
    lo = min(lo, 90)
    return f"{lo}-{lo + 10}%"


def main():
    print(f"Loading training data (batter_training.csv / pitcher_training.csv)...")
    bdf = pd.read_csv(os.path.join(_BASE, "data", "mlb", "processed", "batter_training.csv"))
    pdf = pd.read_csv(os.path.join(_BASE, "data", "mlb", "processed", "pitcher_training.csv"))
    print(f"  batters: {len(bdf)} rows ({bdf['date'].min()}..{bdf['date'].max()})")
    print(f"  pitchers: {len(pdf)} rows ({pdf['date'].min()}..{pdf['date'].max()})")

    print(f"\nFetching real completed-game outcomes {START_DATE} .. {END_DATE} "
          f"from the MLB Stats API (throttled)...")
    games = get_completed_games(START_DATE, END_DATE)
    print(f"\nFound {len(games)} completed games with final scores.")

    rows = []
    n_skipped_no_data = 0
    n_ok = 0
    t_start = time.time()
    for i, game in enumerate(games):
        matchup = build_historical_matchup(bdf, pdf, game)
        if matchup is None:
            n_skipped_no_data += 1
            continue

        seed = int(game["game_pk"]) % (2**31 - 1) if game["game_pk"] else i
        result = gs.run_monte_carlo(
            matchup["away_rates"], matchup["home_rates"],
            matchup["away_ids"], matchup["home_ids"],
            n_trials=N_TRIALS, seed=seed,
        )

        rows.append({
            "date": game["date"],
            "game_pk": game["game_pk"],
            "away_team": game["away_team_name"],
            "home_team": game["home_team_name"],
            "away_score": game["away_score"],
            "home_score": game["home_score"],
            "actual_home_win": game["home_win"],
            "sim_home_win_pct": result["home_win_pct"],
            "sim_away_win_pct": result["away_win_pct"],
            "sim_tie_pct": result["tie_pct"],
        })
        n_ok += 1
        if n_ok % 25 == 0:
            elapsed = time.time() - t_start
            print(f"  simulated {n_ok}/{len(games)} games ({elapsed:.0f}s elapsed)...")

    print(f"\nSimulated {n_ok} games ({n_skipped_no_data} skipped — fewer than 5 real "
          f"batters/pitcher on record for that team/date in this dataset).")

    df = pd.DataFrame(rows)
    df.to_csv(GAMES_OUT, index=False)
    print(f"Per-game results written to {GAMES_OUT}")

    # ------------------------------------------------------------------
    # Calibration: for the FAVORED side's predicted win% in each game,
    # did the favorite actually win that often? Bucketed by predicted
    # win% range, both directions (home and away rows) pooled together
    # so every simulated team-side is one calibration data point.
    # ------------------------------------------------------------------
    calib_rows = []
    for _, r in df.iterrows():
        calib_rows.append({"pred_pct": r["sim_home_win_pct"], "won": bool(r["actual_home_win"])})
        calib_rows.append({"pred_pct": r["sim_away_win_pct"], "won": not bool(r["actual_home_win"])})
    calib = pd.DataFrame(calib_rows)
    calib["bucket"] = calib["pred_pct"].apply(bucket_label)

    bucket_order = [f"{lo}-{lo+10}%" for lo in range(0, 100, 10)]
    summary_lines = []
    summary_lines.append("MLB Sim Explorer — win% calibration backtest")
    summary_lines.append("=" * 60)
    summary_lines.append(f"Date range: {START_DATE} to {END_DATE} ({(END_DATE - START_DATE).days + 1} days)")
    summary_lines.append(f"Games with real final outcomes found: {len(games)}")
    summary_lines.append(f"Games actually simulated: {n_ok}  (skipped: {n_skipped_no_data})")
    summary_lines.append(f"Monte Carlo trials per game: {N_TRIALS}")
    summary_lines.append(f"Calibration data points (each game contributes 2 — one per side): {len(calib)}")
    summary_lines.append("")
    summary_lines.append(f"{'Bucket':<10}{'N':>6}{'Predicted avg':>16}{'Actual win rate':>18}  {'Flag'}")
    summary_lines.append("-" * 70)

    MIN_N_RELIABLE = 20
    for b in bucket_order:
        sub = calib[calib["bucket"] == b]
        n = len(sub)
        if n == 0:
            continue
        pred_avg = sub["pred_pct"].mean()
        actual_rate = 100.0 * sub["won"].mean()
        flag = "" if n >= MIN_N_RELIABLE else f"LOW-N (<{MIN_N_RELIABLE}) — not reliable"
        pred_str = f"{pred_avg:.1f}%"
        actual_str = f"{actual_rate:.1f}%"
        summary_lines.append(f"{b:<10}{n:>6}{pred_str:>16}{actual_str:>18}  {flag}")

    summary_lines.append("")
    overall_pred = calib["pred_pct"].mean()
    overall_actual = 100.0 * calib["won"].mean()
    summary_lines.append(f"Overall: predicted avg {overall_pred:.1f}% vs actual win rate {overall_actual:.1f}% "
                          f"(sanity check — should be close to 50/50 in aggregate since both sides of "
                          f"every game are included)")

    summary_text = "\n".join(summary_lines)
    print("\n" + summary_text)

    with open(SUMMARY_OUT, "w") as f:
        f.write(summary_text + "\n")
    print(f"\nSummary written to {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
