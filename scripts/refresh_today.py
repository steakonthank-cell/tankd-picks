"""
Force-refresh today's MLB moneylines/odds/context data and clear every
cache that sits between those sources and the Sim Explorer tab.

Data flow this script touches (see MONEYLINE_TODO.md / app.py Sim Explorer
docstring for the full map):
  - src.core.moneylines.fetch_moneylines()   -> moneylines_cache/moneylines_cache.json
                                                (30 min TTL, checked by mtime)
                                              -> output/moneylines/latest.csv
                                                 (read by api/server.py GET /api/moneylines,
                                                 the React Moneylines tab's data source)
  - src.core.odds_providers.mlb_context.get_game_context()
                                              -> pickfinder_cache/mlb_context.json
                                                (20 min TTL, checked by mtime;
                                                 lineups/park/weather/totals that
                                                 Sim Explorer's _load_sim_matchup uses)
  - Streamlit's own st.cache_data wrappers around both of the above
    (_sim_todays_games/_sim_training_data/_sim_game_context/_load_sim_matchup,
    all ttl=1800, in app.py) live in-process memory in the two running
    `streamlit run app.py` workers (ports 8501 and 8502) and can only be
    cleared by restarting those processes — there is no external API to
    bust them, so this script restarts both via pm2.

Usage: .venv/bin/python scripts/refresh_today.py
"""
import os
import sys
import csv
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/root/tankd-picks")
os.chdir("/root/tankd-picks")

_ET = ZoneInfo("America/New_York")

MONEYLINES_CACHE = "moneylines_cache/moneylines_cache.json"
MLB_CONTEXT_CACHE = "pickfinder_cache/mlb_context.json"
ML_OUT_PATH = "output/moneylines/latest.csv"

PM2_APPS = ["tankd-picks", "tankd-sim-explorer"]  # Streamlit workers (8501, 8502)


def _banner(msg):
    print(f"\n=== {msg} ===")


def _bust(path):
    if os.path.exists(path):
        os.remove(path)
        print(f"   cleared stale cache: {path}")
    else:
        print(f"   no existing cache at {path} (already clear)")


def refresh_moneylines():
    _banner("Refreshing moneylines")
    _bust(MONEYLINES_CACHE)

    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        print("   ODDS_API_KEY not set — skipping moneylines fetch")
        return None

    from src.core.moneylines import fetch_moneylines, ACTIVE_SPORTS
    from src.sports.mlb.scanner import _abbr

    ml_lines = fetch_moneylines(api_key)
    today_str = datetime.now(_ET).strftime("%Y-%m-%d")
    today_games = [r for r in ml_lines
                   if r.get("Date") == today_str and r.get("Sport") in ACTIVE_SPORTS]

    seen, best_ml = set(), []
    for r in sorted(today_games, key=lambda x: -x.get("Win %", 0)):
        gk = tuple(sorted([r["Team"], r["Opponent"]]))
        if gk in seen:
            continue
        seen.add(gk)
        best_ml.append(r)

    os.makedirs(os.path.dirname(ML_OUT_PATH), exist_ok=True)
    cols = ["Date", "Sport", "Time", "Team", "Opponent", "Home", "Win %",
            "Avg Odds", "Best Odds", "Best Book", "Game Total",
            "Team_Abbr", "Opponent_Abbr", "Books"]
    with open(ML_OUT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in best_ml:
            row["Team_Abbr"] = _abbr(row["Team"])
            row["Opponent_Abbr"] = _abbr(row["Opponent"])
            w.writerow(row)

    print(f"   fetched {len(ml_lines)} total lines, {len(best_ml)} games for {today_str}")
    print(f"   wrote -> {ML_OUT_PATH}")
    return today_str, len(best_ml)


def refresh_game_context():
    _banner("Refreshing MLB game context (lineups/park/weather/totals)")
    _bust(MLB_CONTEXT_CACHE)

    from src.core.odds_providers.mlb_context import get_game_context
    team_ctx, bat_orders, _ = get_game_context()
    print(f"   teams with context: {len(team_ctx)} | lineup slots posted: {len(bat_orders)}")
    return len(team_ctx), len(bat_orders)


def restart_sim_explorer_workers():
    _banner("Restarting Streamlit workers to clear st.cache_data (Sim Explorer)")
    for app in PM2_APPS:
        result = subprocess.run(["pm2", "restart", app], capture_output=True, text=True)
        status = "ok" if result.returncode == 0 else f"FAILED: {result.stderr.strip()}"
        print(f"   pm2 restart {app} -> {status}")


def main():
    started_at = datetime.now(_ET)
    print(f"Starting refresh at {started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    ml_result = refresh_moneylines()
    ctx_result = refresh_game_context()
    restart_sim_explorer_workers()

    finished_at = datetime.now(_ET)
    _banner("DONE")
    print(f"Date loaded:        {ml_result[0] if ml_result else '(moneylines skipped)'}")
    print(f"Games refreshed:    {ml_result[1] if ml_result else 0}")
    print(f"Context teams:      {ctx_result[0]} | lineup slots: {ctx_result[1]}")
    print(f"Pull started:       {started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Pull finished:      {finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Elapsed:            {(finished_at - started_at).total_seconds():.1f}s")
    print("Sim Explorer (8501 + 8502) and /api/moneylines will now serve this data.")


if __name__ == "__main__":
    main()
