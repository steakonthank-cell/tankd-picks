#!/usr/bin/env python3
"""
Step 1 of the MLB moneyline predictor (see MONEYLINE_TODO.md).

Build a clean game-outcome table:
  one row per GAME: date, game_pk, home_team_id, away_team_id,
  home_score, away_score, home_win (1/0).

SOURCE STRATEGY (each source used only for what it's reliable at):
  * SCORES  -> boxscore JSONs (data/mlb/boxscores/*.json). game_pk-keyed,
    complete (only 6/3524 games incomplete), real per-player runs.
    batting_logs.csv was REJECTED for scores: ~2000 games have <5 batter
    rows (fragments), producing phantom ties / wrong totals.
  * HOME/AWAY + matchup -> batting_logs.csv is_home flag. The logs are
    incomplete on RUNS but the is_home / team_id / opponent_id metadata is
    reliable per row.
  * abbr -> team_id : empirically derived from date-overlap (every team
    matched 226-233/233 dates, unambiguous).

Doubleheaders: handled natively — game_pk is unique per game.
All-Star game (abbr AL/NL): dropped.

GATE: prints summary + 5 sample games BEFORE writing. CSV only written with --write.

Usage:
    python3 build_game_outcomes.py            # gate only
    python3 build_game_outcomes.py --write    # write after verifying
"""
import sys, json, glob, os
import pandas as pd

BOX_DIR = "data/mlb/boxscores"
LOGS    = "data/mlb/raw/batting_logs.csv"
OUT     = "data/mlb/processed/game_outcomes.csv"

ABBR_TO_ID = {
    "ATH": 133, "ATL": 144, "AZ": 109, "BAL": 110, "BOS": 111, "CHC": 112,
    "CIN": 113, "CLE": 114, "COL": 115, "CWS": 145, "DET": 116, "HOU": 117,
    "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142,
    "NYM": 121, "NYY": 147, "PHI": 143, "PIT": 134, "SD": 135, "SEA": 136,
    "SF": 137, "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}
SKIP_ABBRS = {"AL", "NL"}  # All-Star rosters


def scores_from_json():
    """Return list of dicts: date, game_pk, team_a_id, a_score, team_b_id, b_score."""
    rows = []
    skipped_allstar = 0
    skipped_incomplete = 0
    skipped_badteams = 0
    for f in sorted(glob.glob(os.path.join(BOX_DIR, "*.json"))):
        date = os.path.basename(f)[:10]
        d = json.load(open(f))
        for gpk, game in d.items():
            teams = {}
            for pdata in game.values():
                if not isinstance(pdata, dict):
                    continue
                ab = (pdata.get("team"))
                if ab is None:
                    continue
                bat = pdata.get("batting") or {}
                runs = bat.get("runs") or 0
                atbats = bat.get("atBats")
                rec = teams.setdefault(ab, {"runs": 0, "batters": 0})
                rec["runs"] += runs
                if atbats is not None:
                    rec["batters"] += 1
            # must be exactly two real teams
            if any(a in SKIP_ABBRS for a in teams):
                skipped_allstar += 1
                continue
            if len(teams) != 2:
                skipped_badteams += 1
                continue
            if any(t not in ABBR_TO_ID for t in teams):
                skipped_badteams += 1
                continue
            # completeness guard: both teams need a real lineup
            if any(v["batters"] < 8 for v in teams.values()):
                skipped_incomplete += 1
                continue
            (a_ab, a), (b_ab, b) = list(teams.items())
            rows.append({
                "date": date, "game_pk": gpk,
                "a_id": ABBR_TO_ID[a_ab], "a_score": a["runs"],
                "b_id": ABBR_TO_ID[b_ab], "b_score": b["runs"],
            })
    print(f"  JSON games kept: {len(rows)}  "
          f"(skipped: all-star {skipped_allstar}, incomplete {skipped_incomplete}, "
          f"bad-teams {skipped_badteams})")
    return rows


def home_lookup_from_logs():
    """Return dict: (date, team_id, opponent_id) -> is_home (0/1)."""
    df = pd.read_csv(LOGS, low_memory=False)
    sub = df[["date", "team_id", "opponent_id", "is_home"]].drop_duplicates(
        subset=["date", "team_id", "opponent_id"])
    return {(r["date"], int(r["team_id"]), int(r["opponent_id"])): int(r["is_home"])
            for _, r in sub.iterrows()}


def build():
    games = scores_from_json()
    home = home_lookup_from_logs()

    out_rows = []
    no_home_info = 0
    for g in games:
        a, b = g["a_id"], g["b_id"]
        # which side is home? look up (date, a, b) then (date, b, a)
        ha = home.get((g["date"], a, b))
        hb = home.get((g["date"], b, a))
        if ha == 1:
            home_id, home_sc, away_id, away_sc = a, g["a_score"], b, g["b_score"]
        elif hb == 1:
            home_id, home_sc, away_id, away_sc = b, g["b_score"], a, g["a_score"]
        elif ha == 0:  # a explicitly away -> b home
            home_id, home_sc, away_id, away_sc = b, g["b_score"], a, g["a_score"]
        elif hb == 0:
            home_id, home_sc, away_id, away_sc = a, g["a_score"], b, g["b_score"]
        else:
            no_home_info += 1
            continue
        out_rows.append({
            "date": g["date"], "game_pk": g["game_pk"],
            "home_team_id": home_id, "away_team_id": away_id,
            "home_score": home_sc, "away_score": away_sc,
            "home_win": int(home_sc > away_sc),
        })
    if no_home_info:
        print(f"  Dropped {no_home_info} games with no home/away info in logs.")

    out = pd.DataFrame(out_rows)
    # MLB has no ties; any equal-score row is a data error -> drop & report
    ties = int((out["home_score"] == out["away_score"]).sum())
    if ties:
        print(f"  Dropping {ties} tied games (data errors).")
        out = out[out["home_score"] != out["away_score"]]
    out = out.sort_values("date").reset_index(drop=True)
    return out


def main():
    out = build()
    print(f"\n  Built {len(out):,} games, {out['date'].min()} -> {out['date'].max()}")
    print(f"  Home win rate: {out['home_win'].mean():.3f}  "
          f"(MLB historical ~0.53-0.54 — this is the key sanity check)")

    id2ab = {v: k for k, v in ABBR_TO_ID.items()}
    print("\n  === GATE: verify these 5 games vs real final scores ===")
    sample = out.sample(min(5, len(out)), random_state=7).sort_values("date")
    for _, r in sample.iterrows():
        h, a = id2ab.get(r["home_team_id"], r["home_team_id"]), id2ab.get(r["away_team_id"], r["away_team_id"])
        winner = "HOME" if r["home_win"] else "AWAY"
        print(f"    {r['date']}  {a} @ {h}   {int(r['away_score'])}-{int(r['home_score'])}"
              f"   -> {winner} ({h if winner=='HOME' else a}) won")

    if "--write" in sys.argv:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        out.to_csv(OUT, index=False)
        print(f"\n  WROTE -> {OUT}  ({len(out):,} games)")
    else:
        print("\n  (gate only — no file written. Re-run with --write once verified.)")


if __name__ == "__main__":
    main()
