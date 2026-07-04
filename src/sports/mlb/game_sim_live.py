"""
MLB Monte Carlo "Scenario Explorer" — live/today's-real-games data layer.

*** EXPLORATORY, NOT PREDICTIVE. Not validated or backtested.

The only file in this feature that talks to the network or touches live
schedule/lineup lookups. Decoupled from `mlb_context.py` / `mlb_splits.py`
(both are only ever called, never modified) and from every other pick/scan
module in this repo — nothing here is wired into any production path.

Scope: today's real scheduled MLB matchups only. Real probable pitchers
and real lineups are used when the MLB Stats API has posted them
(~2-3h pre-game); otherwise every affected field is tagged `presumed=True`
so the caller can label it honestly instead of silently guessing.
"""

from __future__ import annotations

import requests
from datetime import date as date_cls

from src.sports.mlb.game_sim import compute_league_averages  # noqa: F401  (re-export convenience)

_MLB_API = "https://statsapi.mlb.com/api/v1"
_http = requests.Session()
_http.headers.update({"User-Agent": "Mozilla/5.0"})

# (team_id, full_name, park/weather-module abbr). Stable, publicly documented
# MLB Stats API team IDs — reference data, not a projection input. The abbr
# column deliberately matches features/park_factors.py's and
# features/weather.py's own key sets (AZ not ARI, ATH not OAK, KC/SD/SF/TB/
# WSH not KCR/SDP/SFG/TBR/WSN) — scanner.py's `_abbr()` uses a different
# convention (ARI, OAK's old label) that does NOT match those two modules'
# dict keys, so it is intentionally not reused here.
TEAM_META = {
    108: ("Los Angeles Angels", "LAA"), 109: ("Arizona Diamondbacks", "AZ"),
    110: ("Baltimore Orioles", "BAL"),  111: ("Boston Red Sox", "BOS"),
    112: ("Chicago Cubs", "CHC"),       113: ("Cincinnati Reds", "CIN"),
    114: ("Cleveland Guardians", "CLE"),115: ("Colorado Rockies", "COL"),
    116: ("Detroit Tigers", "DET"),     117: ("Houston Astros", "HOU"),
    118: ("Kansas City Royals", "KC"),  119: ("Los Angeles Dodgers", "LAD"),
    120: ("Washington Nationals", "WSH"),121: ("New York Mets", "NYM"),
    133: ("Athletics", "ATH"),          134: ("Pittsburgh Pirates", "PIT"),
    135: ("San Diego Padres", "SD"),    136: ("Seattle Mariners", "SEA"),
    137: ("San Francisco Giants", "SF"),138: ("St. Louis Cardinals", "STL"),
    139: ("Tampa Bay Rays", "TB"),      140: ("Texas Rangers", "TEX"),
    141: ("Toronto Blue Jays", "TOR"),  142: ("Minnesota Twins", "MIN"),
    143: ("Philadelphia Phillies", "PHI"),144: ("Atlanta Braves", "ATL"),
    145: ("Chicago White Sox", "CWS"),  146: ("Miami Marlins", "MIA"),
    147: ("New York Yankees", "NYY"),   158: ("Milwaukee Brewers", "MIL"),
}
NAME_TO_ID = {name: tid for tid, (name, _abbr) in TEAM_META.items()}


def team_name(team_id: int) -> str:
    return TEAM_META.get(team_id, (f"Team {team_id}", ""))[0]


def team_park_abbr(team_id: int) -> str:
    return TEAM_META.get(team_id, ("", ""))[1]


def _norm(name: str) -> str:
    import unicodedata
    n = unicodedata.normalize('NFKD', name or "")
    return ''.join(c for c in n if not unicodedata.combining(c)).lower().strip()


# ---------------------------------------------------------------------------
# Today's real schedule
# ---------------------------------------------------------------------------

def get_todays_games(date_str: str | None = None) -> list[dict]:
    """Fresh call to the MLB Stats API for today's real scheduled games.

    Returns list of:
        {game_pk, away_team_id, away_team_name, home_team_id, home_team_name,
         away_probable: {'id','name'} | None, home_probable: {'id','name'} | None,
         game_time (ISO), status}
    Empty list on any fetch failure — callers must not fabricate games.
    """
    today = date_str or date_cls.today().strftime('%Y-%m-%d')
    try:
        r = _http.get(f"{_MLB_API}/schedule", params={
            "sportId": 1, "date": today,
            "hydrate": "team,linescore,probablePitcher",
        }, timeout=12)
        if r.status_code != 200:
            return []
        games_raw = r.json().get('dates', [{}])
        games_raw = games_raw[0].get('games', []) if games_raw else []
    except Exception as e:
        print(f"[game_sim_live] schedule fetch failed: {e}")
        return []

    out = []
    for g in games_raw:
        try:
            home = g['teams']['home']
            away = g['teams']['away']
            hp = home.get('probablePitcher')
            ap = away.get('probablePitcher')
            out.append({
                "game_pk": g.get("gamePk"),
                "away_team_id": away['team']['id'],
                "away_team_name": away['team']['name'],
                "home_team_id": home['team']['id'],
                "home_team_name": home['team']['name'],
                "away_probable": {"id": ap["id"], "name": ap["fullName"]} if ap else None,
                "home_probable": {"id": hp["id"], "name": hp["fullName"]} if hp else None,
                "game_time": g.get("gameDate", ""),
                "status": g.get("status", {}).get("detailedState", ""),
            })
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Presumed fallbacks (used only when real lineups/starters aren't posted yet)
# ---------------------------------------------------------------------------

def get_presumed_starter(pitcher_df, team_id: int, as_of_date, window: int = 10) -> dict | None:
    """Most frequent starter among this team's last `window` starts before
    `as_of_date`. A naive proxy for "who's likely next in the rotation" —
    NOT a real probable-pitcher lookup. Always tagged presumed=True."""
    d = pitcher_df[(pitcher_df["team_id"] == team_id) & (pitcher_df["is_starter"] == 1)
                   & (pitcher_df["date"] < as_of_date)]
    if d.empty:
        return None
    d = d.sort_values("date").tail(window)
    pid = d["player_id"].value_counts().idxmax()
    pname = d[d["player_id"] == pid]["player_name"].iloc[-1]
    return {"player_id": int(pid), "player_name": pname, "presumed": True}


def get_presumed_lineup(batter_df, team_id: int, as_of_date, n: int = 9,
                         window_games: int = 20) -> list[dict]:
    """Top-`n` batters by trailing appearance frequency for this team.

    IMPORTANT GAP: batter_training.csv has no bat_order column, so there is
    no way to recover a real historical batting-order slot from this file.
    The order returned here is a naive usage-frequency proxy — explicitly
    NOT a real lineup-slot projection. Always tagged presumed=True."""
    d = batter_df[(batter_df["team_id"] == team_id) & (batter_df["date"] < as_of_date)]
    if d.empty:
        return []
    recent_dates = sorted(d["date"].unique())[-window_games:]
    d = d[d["date"].isin(recent_dates)]
    counts = d.groupby("player_id").size().sort_values(ascending=False)
    out = []
    for pid in counts.index[:n]:
        pname = d[d["player_id"] == pid]["player_name"].iloc[-1]
        out.append({"player_id": int(pid), "player_name": pname, "presumed": True})
    return out


# ---------------------------------------------------------------------------
# Composition: real-when-available, presumed-fallback-when-not
# ---------------------------------------------------------------------------

def _name_to_id_map(df, as_of_date) -> dict:
    """norm(player_name) -> most-recent player_id, built from prior rows
    only. Used to match mlb_context's real posted-lineup names (which carry
    no player_id) back to this dataset's player_id."""
    d = df[df["date"] < as_of_date].sort_values("date")
    m = {}
    for pid, nm in zip(d["player_id"], d["player_name"]):
        m[_norm(nm)] = pid
    return m


def build_matchup_lineups(away_team_id: int, home_team_id: int, as_of_date,
                           batter_df, pitcher_df,
                           team_context: dict, bat_orders: dict) -> dict:
    """Compose the away/home lineup + starter for one matchup.

    Lineup order: prefers real posted batting order from
    `mlb_context.get_game_context()`'s `bat_orders` (real once MLB posts
    lineups, ~2-3h pre-game); falls back to `get_presumed_lineup()` only
    for slots that aren't posted. Starter: prefers `get_todays_games()`'s
    probablePitcher (passed in by the caller — this function takes no
    schedule dependency itself to stay easily unit-testable); falls back
    to `get_presumed_starter()`.

    Every entry carries presumed: bool so the UI can label it plainly.
    """
    name_to_id_b = _name_to_id_map(batter_df, as_of_date)

    def _team_lineup(team_id: int) -> list[dict]:
        tname = team_name(team_id)
        real = [(k, v) for k, v in bat_orders.items() if v.get("team") == tname]
        real.sort(key=lambda kv: kv[1]["bat_order"])

        lineup: list[dict] = []
        used_ids = set()
        for norm_name, info in real[:9]:
            pid = name_to_id_b.get(norm_name)
            if pid is None:
                continue
            pname = batter_df[batter_df["player_id"] == pid]["player_name"].iloc[-1]
            lineup.append({"player_id": int(pid), "player_name": pname,
                            "presumed": False, "bat_order": info["bat_order"]})
            used_ids.add(pid)

        if len(lineup) < 9:
            fallback = get_presumed_lineup(batter_df, team_id, as_of_date, n=9)
            for entry in fallback:
                if entry["player_id"] in used_ids:
                    continue
                lineup.append(entry)
                used_ids.add(entry["player_id"])
                if len(lineup) >= 9:
                    break
        return lineup[:9]

    return {
        "away": {"team_id": away_team_id, "team_name": team_name(away_team_id),
                  "lineup": _team_lineup(away_team_id)},
        "home": {"team_id": home_team_id, "team_name": team_name(home_team_id),
                  "lineup": _team_lineup(home_team_id)},
    }


def resolve_starter(pitcher_df, team_id: int, as_of_date, probable: dict | None) -> dict | None:
    """Real probable pitcher (from get_todays_games, passed in by caller)
    matched back to this dataset's player_id when possible; falls back to
    get_presumed_starter() when there's no probable listed or no match."""
    if probable:
        pid = _name_to_id_map(pitcher_df, as_of_date).get(_norm(probable["name"]))
        if pid is not None:
            pname = pitcher_df[pitcher_df["player_id"] == pid]["player_name"].iloc[-1]
            return {"player_id": int(pid), "player_name": pname, "presumed": False}
        # Real probable pitcher named by MLB but not found in our training
        # data (e.g. a rookie call-up) — still real, just can't be rated.
        return {"player_id": None, "player_name": probable["name"], "presumed": False,
                "no_rate_data": True}
    return get_presumed_starter(pitcher_df, team_id, as_of_date)


def resolve_umpire(away_abbr: str, home_abbr: str) -> str | None:
    """Look up today's home-plate umpire via features.umpire_stats'
    existing (currently unimplemented/scraping-stub) lookup. Returns None
    — never a guessed name — when no real assignment is available."""
    try:
        from features.umpire_stats import get_todays_umpires
        umps = get_todays_umpires()
    except Exception:
        return None
    for key in (f"{away_abbr}_vs_{home_abbr}", f"{home_abbr}_vs_{away_abbr}"):
        if key in umps:
            return umps[key]
    return None


def build_weather_dict(ctx: dict | None) -> dict:
    """Adapt mlb_context's team_context entry to the shape
    features.weather.weather_adjustment expects."""
    if not ctx:
        return {"indoor": True, "temp_f": 72, "wind_mph": 0, "flags": []}
    return {
        "indoor": bool(ctx.get("is_indoor")),
        "temp_f": ctx.get("temp_f") or 72,
        "wind_mph": ctx.get("wind_speed") or 0,
        "flags": [],
    }
