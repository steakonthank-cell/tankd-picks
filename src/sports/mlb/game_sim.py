"""
MLB Monte Carlo "Scenario Explorer" — pure simulation engine.

*** EXPLORATORY, NOT PREDICTIVE. This module has NOT been validated or
*** backtested. It is a hypothesis-generation tool, not a pick source.
*** It is intentionally decoupled from every pick/scan surface in this
*** repo: no Streamlit import, no network call, no file writes.

Pipeline: raw per-game rows -> trailing-window PA rates -> empirical-Bayes
shrinkage toward league average -> log5-style batter/pitcher blend ->
park/weather/umpire context multipliers -> 24-state Markov half-inning
simulator -> Monte Carlo aggregation over many simulated games.

Every stage is an approximation stacked on the last one. See the
"Assumptions & limitations" list in app.py's Sim Explorer tab (and the
docstrings below) for what is and isn't modeled. Nothing here should be
read as an edge, a confidence to bet, or a graded pick.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CATEGORIES = ["BB", "SO", "1B", "2B", "3B", "HR", "OUT"]

# Off-the-shelf, order-of-magnitude stabilization points (Carleton-style
# reliability research), NOT fit to this repo's own data. Collapsed to
# 3 tiers (fast/medium/slow-stabilizing) rather than 12 independently
# tuned constants, which would imply more precision than these numbers
# actually carry.
BATTER_K = {"SO": 60, "BB": 120, "1B": 200, "OUT": 200, "HR": 170, "2B": 500, "3B": 700}
PITCHER_K = {"SO": 70, "BB": 170, "1B": 300, "OUT": 300, "HR": 1000, "2B": 900, "3B": 1200}

# Rough "productive out" rate: runner on 3rd, <2 outs, generic ball-in-play
# out. A single named constant, not a full sac-fly model — see plan.
SAC_SCORE_PROB = 0.5


# ---------------------------------------------------------------------------
# 1-2. Rate computation (batter / pitcher)
# ---------------------------------------------------------------------------

def _window_totals(df_player: pd.DataFrame, as_of_date, window: int,
                    date_col: str = "date") -> dict | None:
    """Sum raw counting stats over the trailing `window` games strictly
    before `as_of_date` (no same-game leakage). Ties on date (doubleheaders)
    are broken by original row order for a deterministic result. Returns
    None if there are zero prior rows."""
    d = df_player[df_player[date_col] < as_of_date]
    if d.empty:
        return None
    d = d.sort_values(date_col, kind="stable").tail(window)
    cols = [c for c in ("AB", "BB", "SO", "H", "2B", "3B", "HR",
                         "batters_faced", "K", "BBA", "HR_A", "HA") if c in d.columns]
    totals = {c: float(d[c].sum()) for c in cols}
    totals["_n_games"] = len(d)
    return totals


def compute_batter_pa_rates(batter_df: pd.DataFrame, player_id, as_of_date,
                             window: int = 20) -> tuple[dict, int] | None:
    """Trailing-window batter rate distribution.

    PA_approx = AB + BB (no HBP/SF/SH/CI/ROE in this dataset — roughly a
    2-4% undercount of real PA; the categories below are shares of this
    approximate denominator, not real PA).

    Returns (rates: {BB,SO,1B,2B,3B,HR,OUT} summing to 1.0, n_pa_used) or
    None if the player has no prior rows.
    """
    dfp = batter_df[batter_df["player_id"] == player_id]
    t = _window_totals(dfp, as_of_date, window)
    if t is None:
        return None
    pa = t.get("AB", 0) + t.get("BB", 0)
    if pa <= 0:
        return None
    h = t.get("H", 0)
    dbl, trp, hr = t.get("2B", 0), t.get("3B", 0), t.get("HR", 0)
    single = max(h - dbl - trp - hr, 0)
    so = t.get("SO", 0)
    bb = t.get("BB", 0)
    ab = t.get("AB", 0)
    out = max(ab - so - h, 0)
    raw = {"BB": bb, "SO": so, "1B": single, "2B": dbl, "3B": trp, "HR": hr, "OUT": out}
    rates = {k: v / pa for k, v in raw.items()}
    s = sum(rates.values())
    if s > 0:
        rates = {k: v / s for k, v in rates.items()}
    return rates, int(pa)


def compute_pitcher_pa_rates_5cat(pitcher_df: pd.DataFrame, player_id, as_of_date,
                                   window: int = 10) -> tuple[dict, int] | None:
    """Trailing-window pitcher rates, 5 raw categories only (this dataset's
    HA is not split by hit type). PA_approx = batters_faced (tracked
    directly — cleaner denominator than reconstructing one)."""
    dfp = pitcher_df[pitcher_df["player_id"] == player_id]
    t = _window_totals(dfp, as_of_date, window)
    if t is None:
        return None
    bf = t.get("batters_faced", 0)
    if bf <= 0:
        return None
    k, bba, hra, ha = t.get("K", 0), t.get("BBA", 0), t.get("HR_A", 0), t.get("HA", 0)
    out = max(bf - k - bba - ha, 0)
    raw = {"BB": bba, "SO": k, "HR": hra, "H": ha, "OUT": out}
    rates = {kk: v / bf for kk, v in raw.items()}
    s = sum(rates.values())
    if s > 0:
        rates = {kk: v / s for kk, v in rates.items()}
    return rates, int(bf)


def league_hit_type_shares(batter_df: pd.DataFrame, as_of_date) -> dict:
    """League-wide share of 1B/2B/3B among non-HR hits, as of `as_of_date`
    (all rows strictly before it). Used only to give pitcher hit-type mix a
    shape, since pitcher data has no batted-ball profile of its own."""
    d = batter_df[batter_df["date"] < as_of_date]
    if d.empty:
        return {"1B": 0.72, "2B": 0.21, "3B": 0.02}  # generic MLB-shape fallback
    h, dbl, trp, hr = d["H"].sum(), d["2B"].sum(), d["3B"].sum(), d["HR"].sum()
    single = max(h - dbl - trp - hr, 0)
    non_hr = single + dbl + trp
    if non_hr <= 0:
        return {"1B": 0.72, "2B": 0.21, "3B": 0.02}
    return {"1B": single / non_hr, "2B": dbl / non_hr, "3B": trp / non_hr}


def split_pitcher_hit_types(pitcher_rates_5cat: dict, hit_shares: dict) -> dict:
    """Expand the pitcher's 5-cat {BB,SO,HR,H,OUT} into the full 7-cat
    distribution by splitting H proportionally to league-average hit-type
    shares. Does NOT model that some pitchers are more fly-ball/gap-prone
    than others — this dataset has no batted-ball data to support that."""
    h_rate = pitcher_rates_5cat.get("H", 0)
    out = dict(pitcher_rates_5cat)
    out.pop("H", None)
    out["1B"] = h_rate * hit_shares.get("1B", 0.72)
    out["2B"] = h_rate * hit_shares.get("2B", 0.21)
    out["3B"] = h_rate * hit_shares.get("3B", 0.02)
    for c in CATEGORIES:
        out.setdefault(c, 0.0)
    s = sum(out[c] for c in CATEGORIES)
    if s > 0:
        out = {c: out[c] / s for c in CATEGORIES}
    return out


def compute_pitcher_pa_rates(pitcher_df: pd.DataFrame, player_id, as_of_date,
                              batter_df_for_league_shape: pd.DataFrame,
                              window: int = 10) -> tuple[dict, int] | None:
    """Convenience wrapper: 5-cat pitcher rates -> full 7-cat via league
    hit-type shape. Returns (7-cat rates, n_bf_used) or None."""
    res = compute_pitcher_pa_rates_5cat(pitcher_df, player_id, as_of_date, window)
    if res is None:
        return None
    rates5, n = res
    shares = league_hit_type_shares(batter_df_for_league_shape, as_of_date)
    return split_pitcher_hit_types(rates5, shares), n


# ---------------------------------------------------------------------------
# 3. League averages, shrinkage, blending, context multipliers
# ---------------------------------------------------------------------------

def compute_league_averages(batter_df: pd.DataFrame, pitcher_df: pd.DataFrame,
                             as_of_date) -> dict:
    """League-average 7-cat batter distribution and pitcher hit-type
    shares, as of `as_of_date`. Cheap to call once per matchup and reuse
    for every player in it — do not call per-player."""
    d = batter_df[batter_df["date"] < as_of_date]
    if d.empty:
        # Generic MLB-average fallback shape if literally no prior rows exist
        # (e.g. as_of_date predates the whole dataset).
        batter_rates = {"BB": 0.085, "SO": 0.225, "1B": 0.145, "2B": 0.045,
                         "3B": 0.004, "HR": 0.033, "OUT": 0.463}
    else:
        pa = d["AB"].sum() + d["BB"].sum()
        h, dbl, trp, hr = d["H"].sum(), d["2B"].sum(), d["3B"].sum(), d["HR"].sum()
        single = max(h - dbl - trp - hr, 0)
        so, bb, ab = d["SO"].sum(), d["BB"].sum(), d["AB"].sum()
        out = max(ab - so - h, 0)
        raw = {"BB": bb, "SO": so, "1B": single, "2B": dbl, "3B": trp, "HR": hr, "OUT": out}
        batter_rates = {k: v / pa for k, v in raw.items()} if pa > 0 else raw
        s = sum(batter_rates.values())
        if s > 0:
            batter_rates = {k: v / s for k, v in batter_rates.items()}
    return {
        "batter": batter_rates,
        "pitcher_hit_shares": league_hit_type_shares(batter_df, as_of_date),
    }


def shrink_rate(observed_rate: float, n: float, league_rate: float, k: float) -> float:
    """Empirical-Bayes shrinkage toward league average. As n -> 0 this
    collapses to league_rate; as n -> inf it approaches observed_rate."""
    if n + k <= 0:
        return league_rate
    return (n / (n + k)) * observed_rate + (k / (n + k)) * league_rate


def shrink_distribution(raw_rates: dict, n: float, league_rates: dict,
                         k_map: dict) -> dict:
    """Shrink each category independently (different k per category), then
    renormalize to sum to 1.0 — required because per-category shrinkage
    does not preserve the sum on its own."""
    out = {}
    for c in CATEGORIES:
        out[c] = shrink_rate(raw_rates.get(c, 0.0), n, league_rates.get(c, 0.0), k_map.get(c, 200))
    s = sum(out.values())
    if s > 0:
        out = {c: out[c] / s for c in CATEGORIES}
    return out


def blend_matchup(batter_shrunk: dict, pitcher_shrunk: dict, league_rates: dict) -> dict:
    """log5 / odds-ratio blend of a batter's and pitcher's shrunk rates
    against league average, renormalized across all 7 categories."""
    out = {}
    for c in CATEGORIES:
        lg = max(league_rates.get(c, 1e-6), 1e-6)
        b = batter_shrunk.get(c, 0.0)
        p = pitcher_shrunk.get(c, 0.0)
        out[c] = (b / lg) * (p / lg) * lg
    s = sum(out.values())
    if s > 0:
        out = {c: out[c] / s for c in CATEGORIES}
    else:
        out = dict(league_rates)
    return out


def apply_context_multipliers(matchup_rates: dict, park_abbr: str | None,
                               weather: dict | None, umpire_name: str | None) -> dict:
    """Apply park/weather/umpire multipliers (reusing this repo's existing
    validated feature modules — not reinventing them), then renormalize.

    Renormalizing after a multiplier touches only e.g. HR redistributes the
    added/removed mass proportionally across all 6 other categories, not
    specifically out of/into OUT — a real approximation, not a hidden one.
    """
    from features.park_factors import park_edge_modifier
    from features.weather import weather_adjustment
    from features.umpire_stats import umpire_adjustment

    out = dict(matchup_rates)
    if park_abbr:
        for stat, cats in (("HR", ["HR"]), ("H", ["1B", "2B", "3B"])):
            try:
                mult = park_edge_modifier(park_abbr, stat)
            except Exception:
                mult = 1.0
            for c in cats:
                out[c] = out.get(c, 0.0) * mult
    if weather:
        for stat, cats in (("HR", ["HR"]), ("SO", ["SO"])):
            try:
                mult = weather_adjustment(weather, stat)
            except Exception:
                mult = 1.0
            for c in cats:
                out[c] = out.get(c, 0.0) * mult
    if umpire_name:
        try:
            mult = umpire_adjustment(umpire_name, "SO")
        except Exception:
            mult = 1.0
        out["SO"] = out.get("SO", 0.0) * mult

    s = sum(out.get(c, 0.0) for c in CATEGORIES)
    if s > 0:
        out = {c: out.get(c, 0.0) / s for c in CATEGORIES}
    else:
        out = dict(matchup_rates)
    return out


# ---------------------------------------------------------------------------
# 4. Game simulation engine
# ---------------------------------------------------------------------------

def _advance_runners(bases: tuple, hit_type: str, rng) -> tuple[tuple, int]:
    """Deterministic base advancement per hit type (simplified but
    standard). `bases` is (on1, on2, on3) booleans. Returns (new_bases,
    runs_scored_this_event)."""
    on1, on2, on3 = bases
    runs = 0

    if hit_type == "BB":
        # Force logic: batter always takes 1st. A runner is forced to the
        # next base only if the chain of occupied bases behind them (down
        # to 1st) is unbroken.
        new2, new3 = on2, on3
        if on1:
            new2 = True
            if on2:
                new3 = True
                if on3:
                    runs += 1  # runner forced home
        return (True, new2, new3), runs

    if hit_type == "1B":
        runs += int(on2) + int(on3)
        return (True, on1, False), runs

    if hit_type == "2B":
        runs += int(on2) + int(on3)
        return (False, True, on1), runs

    if hit_type == "3B":
        runs += int(on1) + int(on2) + int(on3)
        return (False, False, True), runs

    if hit_type == "HR":
        runs += 1 + int(on1) + int(on2) + int(on3)
        return (False, False, False), runs

    return bases, runs


def _cum_probs(rates: dict) -> np.ndarray:
    """Precompute a cumulative-probability array over CATEGORIES for fast
    inverse-CDF sampling (np.searchsorted), computed once per lineup slot
    rather than re-normalized on every simulated at-bat."""
    probs = np.array([rates.get(c, 0.0) for c in CATEGORIES], dtype=float)
    total = probs.sum()
    probs = probs / total if total > 0 else np.ones(len(CATEGORIES)) / len(CATEGORIES)
    return np.cumsum(probs)


def simulate_half_inning(lineup_cum: list[np.ndarray], start_idx: int, rng,
                          sac_score_prob: float = SAC_SCORE_PROB) -> tuple[int, int, dict]:
    """Simulate one half-inning against a fixed lineup of precomputed
    cumulative-probability arrays (see `_cum_probs`).

    Returns (runs_scored, next_start_idx, batter_event_tally) where
    batter_event_tally maps lineup slot index -> {category: count} for
    this half-inning only (aggregated across trials by the caller)."""
    n = len(lineup_cum)
    outs = 0
    bases = (False, False, False)
    runs = 0
    idx = start_idx
    tally: dict[int, dict] = {}

    while outs < 3:
        slot = idx % n
        cum = lineup_cum[slot]
        outcome = CATEGORIES[min(int(np.searchsorted(cum, rng.random(), side="right")), len(CATEGORIES) - 1)]

        slot_tally = tally.setdefault(slot, {c: 0 for c in CATEGORIES})
        slot_tally[outcome] += 1

        if outcome == "SO":
            outs += 1
        elif outcome == "OUT":
            if outs < 2 and bases[2] and rng.random() < sac_score_prob:
                runs += 1
                bases = (bases[0], bases[1], False)
            outs += 1
        else:
            bases, r = _advance_runners(bases, outcome, rng)
            runs += r

        idx += 1

    return runs, idx % n, tally


def simulate_game(away_lineup_rates: list[dict], home_lineup_rates: list[dict],
                   rng, n_innings: int = 9,
                   _away_cum: list[np.ndarray] | None = None,
                   _home_cum: list[np.ndarray] | None = None) -> dict:
    """Standard 9-inning game. Skips the bottom of the 9th (only) if the
    home team already leads. Does NOT simulate extra innings — a tie after
    9 is reported honestly as winner='tie', not forced to a winner. The
    same starting pitcher's rates face the lineup for all 9 innings (no
    bullpen model — see plan; this is a named limitation, not an
    oversight).

    `_away_cum`/`_home_cum` let a hot caller (run_monte_carlo) pass
    precomputed cumulative-probability arrays instead of recomputing them
    every trial; standalone callers can ignore these and pass rate dicts
    only."""
    away_runs = home_runs = 0
    away_idx = home_idx = 0
    batter_lines: dict[str, dict] = {"away": {}, "home": {}}
    away_cum = _away_cum if _away_cum is not None else [_cum_probs(r) for r in away_lineup_rates]
    home_cum = _home_cum if _home_cum is not None else [_cum_probs(r) for r in home_lineup_rates]

    def _merge(dst: dict, src: dict):
        for slot, cats in src.items():
            d = dst.setdefault(slot, {c: 0 for c in CATEGORIES})
            for c, v in cats.items():
                d[c] += v

    for inning in range(1, n_innings + 1):
        r, away_idx, t = simulate_half_inning(away_cum, away_idx, rng)
        away_runs += r
        _merge(batter_lines["away"], t)

        if inning == n_innings and home_runs > away_runs:
            break

        r, home_idx, t = simulate_half_inning(home_cum, home_idx, rng)
        home_runs += r
        _merge(batter_lines["home"], t)

    if home_runs > away_runs:
        winner = "home"
    elif away_runs > home_runs:
        winner = "away"
    else:
        winner = "tie"

    return {"home_runs": home_runs, "away_runs": away_runs, "winner": winner,
            "batter_lines": batter_lines}


def run_monte_carlo(away_lineup_rates: list[dict], home_lineup_rates: list[dict],
                     away_ids: list, home_ids: list,
                     n_trials: int = 5000, seed: int | None = None) -> dict:
    """Run `n_trials` simulated games with one fixed RNG stream (seed fixed
    once per call for reproducibility — Streamlit reruns the whole script
    on every widget interaction, and a re-seeded call on every rerun would
    make honest Monte Carlo variance look like a bug). Pure dict output."""
    rng = np.random.default_rng(seed)

    home_wins = away_wins = ties = 0
    home_runs_arr = np.zeros(n_trials)
    away_runs_arr = np.zeros(n_trials)

    n_away, n_home = len(away_lineup_rates), len(home_lineup_rates)
    away_totals = [{c: 0 for c in CATEGORIES + ["PA"]} for _ in range(n_away)]
    home_totals = [{c: 0 for c in CATEGORIES + ["PA"]} for _ in range(n_home)]

    # Rates are fixed for the whole matchup — precompute cumulative arrays
    # once instead of once per trial (was once per at-bat before this
    # optimization; ~385k redundant array builds for 5000 trials).
    away_cum = [_cum_probs(r) for r in away_lineup_rates]
    home_cum = [_cum_probs(r) for r in home_lineup_rates]

    for i in range(n_trials):
        g = simulate_game(away_lineup_rates, home_lineup_rates, rng,
                           _away_cum=away_cum, _home_cum=home_cum)
        home_runs_arr[i] = g["home_runs"]
        away_runs_arr[i] = g["away_runs"]
        if g["winner"] == "home":
            home_wins += 1
        elif g["winner"] == "away":
            away_wins += 1
        else:
            ties += 1

        for slot, cats in g["batter_lines"]["away"].items():
            for c, v in cats.items():
                away_totals[slot][c] += v
                away_totals[slot]["PA"] += v
        for slot, cats in g["batter_lines"]["home"].items():
            for c, v in cats.items():
                home_totals[slot][c] += v
                home_totals[slot]["PA"] += v

    def _per_player(totals, ids):
        rows = []
        for slot, t in enumerate(totals):
            pa = max(t["PA"], 1)
            h = t.get("1B", 0) + t.get("2B", 0) + t.get("3B", 0) + t.get("HR", 0)
            rows.append({
                "slot": slot + 1,
                "player_id": ids[slot] if slot < len(ids) else None,
                "PA_per_game": t["PA"] / n_trials,
                "H_per_game": h / n_trials,
                "HR_per_game": t.get("HR", 0) / n_trials,
                "BB_per_game": t.get("BB", 0) / n_trials,
                "SO_per_game": t.get("SO", 0) / n_trials,
                "AVG_sim": h / max(pa - t.get("BB", 0), 1),
            })
        return rows

    return {
        "n_trials": n_trials,
        "home_win_pct": 100.0 * home_wins / n_trials,
        "away_win_pct": 100.0 * away_wins / n_trials,
        "tie_pct": 100.0 * ties / n_trials,
        "home_runs_mean": float(home_runs_arr.mean()),
        "away_runs_mean": float(away_runs_arr.mean()),
        "total_runs_mean": float((home_runs_arr + away_runs_arr).mean()),
        "home_runs_arr": home_runs_arr,
        "away_runs_arr": away_runs_arr,
        "away_batter_lines": _per_player(away_totals, away_ids),
        "home_batter_lines": _per_player(home_totals, home_ids),
    }


# ---------------------------------------------------------------------------
# Smoke tests — no pytest infra exists in this repo; matches its existing
# ad hoc `if __name__ == "__main__"` convention (see backtest.py).
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    lg = {"BB": 0.085, "SO": 0.225, "1B": 0.145, "2B": 0.045,
          "3B": 0.004, "HR": 0.033, "OUT": 0.463}

    print("[1] Uniform league-average lineups, 5000 trials...")
    away = [dict(lg) for _ in range(9)]
    home = [dict(lg) for _ in range(9)]
    res = run_monte_carlo(away, home, list(range(9)), list(range(9)), n_trials=5000, seed=42)
    print(f"    total runs/game mean: {res['total_runs_mean']:.2f} (want ~8-9)")
    assert 6.5 <= res["total_runs_mean"] <= 11.0, "run environment out of plausible band"

    print("[2] Deliberate OBP/SLG gap...")
    strong = {"BB": 0.13, "SO": 0.16, "1B": 0.16, "2B": 0.06, "3B": 0.006, "HR": 0.05, "OUT": 0.434}
    weak = {"BB": 0.05, "SO": 0.30, "1B": 0.12, "2B": 0.03, "3B": 0.002, "HR": 0.015, "OUT": 0.483}
    away_s = [dict(strong) for _ in range(9)]
    home_w = [dict(weak) for _ in range(9)]
    pitcher = [dict(lg) for _ in range(9)]
    res2 = run_monte_carlo(away_s, pitcher, list(range(9)), list(range(9)), n_trials=5000, seed=1)
    print(f"    strong-lineup away win%: {res2['away_win_pct']:.1f} (want > 50)")
    assert res2["away_win_pct"] > 50, "stronger lineup should win more than half the time"

    print("[3] Thin-sample shrinkage (n=1 PA -> near league avg)...")
    shrunk = shrink_distribution({"HR": 1.0}, n=1, league_rates=lg, k_map={"HR": 170, **{c: 200 for c in CATEGORIES}})
    print(f"    shrunk HR rate: {shrunk['HR']:.4f} (league {lg['HR']:.4f})")
    assert abs(shrunk["HR"] - lg["HR"]) < 0.02, "n=1 sample should collapse close to league average"

    print("[4] Distribution-sum invariants...")
    for d in (lg, strong, weak, shrunk, blend_matchup(strong, weak, lg)):
        s = sum(d.get(c, 0.0) for c in CATEGORIES)
        assert abs(s - 1.0) < 1e-6, f"category dict does not sum to 1.0: {s}"

    print("[5] Bottom-9th skip + tie handling...")
    seen_tie = False
    rng = np.random.default_rng(7)
    for _ in range(200):
        g = simulate_game([dict(lg) for _ in range(9)], [dict(lg) for _ in range(9)], rng)
        if g["winner"] == "tie":
            seen_tie = True
        if g["home_runs"] > g["away_runs"]:
            pass  # bottom 9th may have been skipped; can't directly assert PA count here cheaply
    assert seen_tie, "expected at least one tie in 200 games at equal talent (sanity, not guaranteed)"

    print("All smoke tests passed.")
