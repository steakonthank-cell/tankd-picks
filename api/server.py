"""
Tank'd Picks v2 — API Server
==============================
Lightweight FastAPI backend that serves enriched scanner data
as JSON endpoints for the React dashboard.

Replaces the Streamlit UI with a proper API + static React app.

Run:
    uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET /api/picks/{sport}              — Latest picks for a sport
    GET /api/picks/{sport}/{stat_type}  — Picks filtered by stat
    GET /api/moneylines                 — Today's moneyline picks
    GET /api/meta                       — Last scan times, counts
    GET /                               — Serves React dashboard
"""

import os
import sys
import glob
import json
import time
import requests
from datetime import datetime
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    import pandas as pd
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install fastapi uvicorn pandas --break-system-packages")
    sys.exit(1)

# Add parent for feature imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from features.pipeline import enrich_scan_data
from src.sports.mlb.bullpen import (
    team_bullpen_era, team_bullpen_workload,
    league_avg_bullpen_era, league_avg_bullpen_workload,
)

_TEAM_ABBR = {
    "Arizona Diamondbacks": "ARI", "Athletics": "ATH", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE", "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM", "New York Yankees": "NYY",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

# goblin model scorer (validated MLB goblin filter)
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import goblin_scorer as _goblin
    _GOBLIN_OK = True
except Exception as _e:
    print(f"[server] goblin scorer unavailable: {_e}")
    _GOBLIN_OK = False


# ─── Config ───
BASE_DIR = Path(os.environ.get("TANKD_DIR", "/root/tankd-picks"))
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend" / "dist"


import math as _math
def _scrub_nan(obj):
    """Recursively replace NaN/Inf floats with None so JSON serialization succeeds."""
    if isinstance(obj, float):
        return None if (_math.isnan(obj) or _math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _scrub_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_nan(v) for v in obj]
    return obj

app = FastAPI(title="Tank'd Picks v2 API", version="2.0.0")

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Picks payload grew ~6x once the per-stat cap was raised (see below) —
# gzip keeps the mobile transfer cost down (JSON compresses ~5-8x).
app.add_middleware(GZipMiddleware, minimum_size=500)


_PITCHER_HAND_CACHE = {"data": None, "ts": 0.0}
_PITCHER_HAND_TTL = 6 * 3600  # hours; a pitcher's throwing hand never changes intra-season


def _get_pitcher_hands() -> dict:
    """MLB_ID -> throwing hand ('L'/'R') for the active roster.

    Deliberately a separate, direct call to the roster endpoint
    (/sports/1/players) rather than reusing anything from the nightly
    gameLog/statSplits pipeline: that pipeline is the one under sustained
    degradation (see CLAUDE.md's 2026-07-28/08-03 incidents), and this
    field is decorative (a label on the Sharp tab), not scoring input --
    a failure here should never be able to touch scan data or picks, only
    silently omit the hand label.
    """
    now = time.time()
    if _PITCHER_HAND_CACHE["data"] is not None and now - _PITCHER_HAND_CACHE["ts"] < _PITCHER_HAND_TTL:
        return _PITCHER_HAND_CACHE["data"]
    hands = {}
    try:
        r = requests.get("https://statsapi.mlb.com/api/v1/sports/1/players",
                          params={"season": 2026}, timeout=15)
        if r.status_code == 200:
            for p in r.json().get("people", []):
                pid = p.get("id")
                hand = (p.get("pitchHand") or {}).get("code")
                if pid and hand:
                    hands[pid] = hand
    except Exception as e:
        print(f"[server] pitcher-hand lookup failed: {e}")
    if hands:
        _PITCHER_HAND_CACHE["data"], _PITCHER_HAND_CACHE["ts"] = hands, now
        return hands
    return _PITCHER_HAND_CACHE["data"] or {}


def get_latest_csv(sport: str) -> Path | None:
    """Find the most recent scan CSV for a sport."""
    scan_dir = OUTPUT_DIR / sport.lower() / "scans"
    files = sorted(glob.glob(str(scan_dir / "scan_*.csv")))
    return Path(files[-1]) if files else None


def load_and_enrich(sport: str) -> pd.DataFrame:
    """Load the latest scan CSV and enrich with v2 features."""
    csv_path = get_latest_csv(sport)
    if not csv_path or not csv_path.exists():
        return pd.DataFrame()
    
    df = pd.read_csv(csv_path)
    enriched = enrich_scan_data(df, sport=sport)
    return enriched


def df_to_picks(df: pd.DataFrame) -> list:
    """Convert enriched DataFrame to API response format."""
    if df.empty:
        return []
    
    # score goblins with the validated model (returns {row_index: (prob, grade)})
    goblin_scores = {}
    if _GOBLIN_OK:
        try:
            goblin_scores = _goblin.score_goblins(df)
        except Exception as _e:
            print(f"[server] goblin scoring failed: {_e}")

    pitcher_hands = _get_pitcher_hands()

    picks = []
    for idx, row in df.iterrows():
        is_goblin = bool(row.get("Is_Goblin", False))
        gp, gg = goblin_scores.get(idx, (None, None))
        model_prob = (min(round(float(gp), 3), 0.99) if gp is not None else None)
        pick = {
            "player": row.get("Player", "Unknown"),
            "team": row.get("team", row.get("Team", "")),
            "mlb_id": (str(int(float(row.get("MLB_ID")))) if pd.notna(row.get("MLB_ID")) and str(row.get("MLB_ID")).strip() not in ("", "nan") else None),
            "headshot": (f"https://midfield.mlbstatic.com/v1/people/{int(float(row.get('MLB_ID')))}/spots/120" if pd.notna(row.get("MLB_ID")) and str(row.get("MLB_ID")).strip() not in ("", "nan") else None),
            "stat_type": row.get("stat_type", row.get("Stat_Label", row.get("Stat", ""))),
            "side": row.get("Side", ""),
            "line": float(row.get("PP_Line", row.get("Line", 0))) if pd.notna(row.get("PP_Line", row.get("Line"))) else 0,
            "segment": "pitcher" if bool(row.get("Is_Pitcher", False)) else "hitter",
            "win_pct": float(row.get("Con_Over", 0)) if pd.notna(row.get("Con_Over")) else 0,
            "ai_proj": float(row.get("AI_Proj", row.get("ai_proj", 0))) if pd.notna(row.get("AI_Proj", row.get("ai_proj"))) else 0,
            "score": float(row.get("v2_score", row.get("Score", row.get("score", 0)))),
            # Edge_Pct/v2_edge are true percentages (|proj-line|/line*100, composite-
            # adjusted) — this is the value the 45%-of-composite-score weighting in
            # pipeline.py actually refers to. Previously this recomputed a raw
            # AI_Proj-PP_Line diff in the stat's native units (e.g. "+2.3" Ks), which
            # is not a percentage and doesn't match what the UI displays it as.
            "edge": float(row.get("v2_edge", row.get("Edge_Pct", 0)) or 0),
            "tier": row.get("v2_tier", row.get("tier", row.get("Tier", ""))),
            "l5": str(row.get("l5", row.get("L5", ""))),
            "l10": str(row.get("l10", row.get("L10", row.get("Avg_L10", "")))),
            # matchup hitting stats (baseball only; null when absent)
            "ops_vs": (float(row.get("OPS_vs")) if pd.notna(row.get("OPS_vs")) else None),
            "avg_vs": (float(row.get("AVG_vs")) if pd.notna(row.get("AVG_vs")) else None),
            "k_pct_vs": (float(row.get("K_Pct_vs")) if pd.notna(row.get("K_Pct_vs")) else None),
            "ab_vs": (int(float(row.get("AB_vs"))) if pd.notna(row.get("AB_vs")) else None),
            # True = a real vs-hand statSplits result; False = MLB's statSplits
            # endpoint was unavailable and ops_vs/avg_vs/k_pct_vs above are a
            # season-aggregate fallback instead (see mlb_splits.get_todays_splits) —
            # None when there's no matchup data at all. Previously computed
            # (Split_Is_Live, scanner.py) but dropped before reaching the API,
            # so the dashboard had no way to flag which matchup numbers were
            # real platoon splits vs. season averages.
            "split_is_live": (bool(row.get("Split_Is_Live")) if pd.notna(row.get("Split_Is_Live")) else None),
            # Hand of today's opposing starter (batters) — 'L'/'R'. Only
            # meaningful alongside split_is_live=True: when the split is a
            # season-aggregate fallback, ops_vs/avg_vs aren't actually
            # specific to this hand, so the frontend must not badge them
            # "vs L"/"vs R" in that case even though the hand itself is known.
            "pitch_hand": (str(row.get("Pitch_Hand")) if pd.notna(row.get("Pitch_Hand")) and str(row.get("Pitch_Hand")).strip() else None),
            # The pitcher's OWN throwing hand (pitcher rows only) — distinct
            # from pitch_hand above, which is the opposing SP's hand as seen
            # by a batter. Sourced from a live roster lookup (_get_pitcher_hands),
            # not the gameLog/statSplits pipeline, so it can't be affected by
            # that pipeline's ongoing degradation.
            "pitcher_hand": (
                pitcher_hands.get(int(float(row.get("MLB_ID"))))
                if bool(row.get("Is_Pitcher", False)) and pd.notna(row.get("MLB_ID")) and str(row.get("MLB_ID")).strip() not in ("", "nan")
                else None
            ),
            # v2 features
            #
            # park_factor: the live per-team/per-stat multiplier that was
            # actually baked into AI_Proj (scanner.py's PF_Mult, from
            # mlb_context.py's table, applied pre-line alongside wind/PA
            # adjustments). Previously this field came from a *different*,
            # static "2024-2025 seasons" table in features/park_factors.py
            # that only ever fed the internal v2_score ranking multiplier —
            # never AI_Proj — so the badge shown to users didn't match the
            # number that actually shaped their projection. Falls back to
            # the pipeline's neutral 100 for non-MLB sports / rows without
            # a live PF_Mult (indoor sports, or if scanner.py's game-context
            # fetch failed for that slate).
            "park_factor": (
                round(float(row.get("PF_Mult")) * 100)
                if pd.notna(row.get("PF_Mult")) else int(row.get("park_factor", 100))
            ),
            "weather_adj": float(row.get("weather_adj", 1.0)),
            # fatigue_score and umpire_adj are deliberately not sent: both
            # are computed in features/pipeline.py against a game_context
            # dict that nothing in this codebase ever populates (grepped —
            # zero callers pass it), so they are structurally always the
            # neutral default (fatigue_score=0, umpire_adj=1.0) on every
            # pick, never a real signal. Re-add once game_context is wired
            # up to real per-game data.
            # goblin model
            "is_goblin": is_goblin,
            "is_demon": bool(row.get("Is_Demon", False)),
            "model_prob": model_prob,
            "grade": gg,
            # SHARP: in live practice this bucket is ~99% goblin-Over picks
            # (standard-Under K/OUTS at this edge threshold almost never
            # clears the board — n=4 across 2 months of production, not a
            # usable sample). Live-validated number: goblin-Over K/OUTS,
            # edge>=2, hit 81.4% (n=533, graded 2026-05-31 to 2026-07-31,
            # post-regrade). The "~88% out-of-sample" figure previously
            # cited here for a blended standard+goblin bucket was an
            # unsourced backtest claim with no linked script or data in
            # this repo and no live sample behind its standard-Under half —
            # removed 2026-08-01, see memory: tankd-sharp-bucket-validation.
            "sharp": (
                str(row.get("Stat","")).upper() in ("K","OUTS")
                and pd.notna(row.get("AI_Proj")) and pd.notna(row.get("PP_Line"))
                and abs(float(row.get("AI_Proj")) - float(row.get("PP_Line"))) >= 2.0
                and not bool(row.get("Is_Demon", False))          # demons: fake edge, never sharp
                and (not is_goblin or str(row.get("Side","")).title() == "Over")  # goblins: Over only
                and gg != "SKIP"   # bust-gate: don't badge a pick the calibrated model itself rejects
            ),
        }
        picks.append(pick)
    
    # Drop push lines — only keep .5 lines (whole numbers can tie)
    picks = [p for p in picks if abs((p.get("line", 0) % 1) - 0.5) < 1e-9]

    # Sort by score descending
    # rank: graded goblins by model_prob first, then everything else by score
    def _rank(x):
        mp = x.get("model_prob")
        return (1, mp) if mp is not None else (0, x["score"] / 1000.0)
    picks.sort(key=_rank, reverse=True)
    # Dedupe alternate lines: keep only the best-ranked line per
    # player+stat+side (picks are already rank-sorted, so first seen wins).
    seen = set()
    deduped = []
    for p in picks:
        key = (p.get("player"), p.get("stat_type"))  # one row per player+stat, best side wins
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    picks = deduped
    # SHARP picks (backtested edge bucket) always surface, uncapped — they're
    # the whole point. Then fill the rest under the per-bucket cap.
    #
    # Cap raised 25 -> 1000: 25 was hiding the large majority of real eligible
    # picks in high-volume stats (e.g. HR non-goblin had 252 real candidates
    # on 2026-07-03, only 25 shown). 1000 is a safety ceiling, not a real
    # limit — a full MLB slate tops out at ~270 batters total (15 games x 18),
    # so no stat/goblin bucket can realistically get near this; it only
    # guards against a data/dedup bug trying to serve an absurd row count.
    # The frontend renders this incrementally (load-more-on-scroll), so the
    # full set doesn't have to hit the DOM at once.
    sharp = [p for p in picks if p.get("sharp")]
    rest  = [p for p in picks if not p.get("sharp")]
    gob = _cap_per_stat([p for p in rest if p.get("is_goblin")], 1000)
    non = _cap_per_stat([p for p in rest if not p.get("is_goblin")], 1000)
    return sharp + gob + non


def _cap_per_stat(rank_sorted_picks: list, cap_per_stat: int) -> list:
    """Cap a rank-sorted pick list per stat_type instead of as one flat
    global cap. A flat cap (e.g. top 75 across all stats combined) lets a
    high-volume stat with generally higher scores (e.g. Hits+Runs+RBIs)
    consume the whole budget and starve out a lower-scoring stat entirely
    (e.g. Home Runs had 229 real candidate rows in the raw scan on 2026-07-03
    but zero survived a flat top-75 cut). Preserves the existing rank order.
    """
    counts = {}
    out = []
    for p in rank_sorted_picks:
        st = p.get("stat_type")
        if counts.get(st, 0) < cap_per_stat:
            counts[st] = counts.get(st, 0) + 1
            out.append(p)
    return out


# ─── API Endpoints ───

_BULLPEN_CACHE = {"data": None, "ts": 0.0}
_BULLPEN_CACHE_TTL = 900  # 15 min — cheap to recompute, but no reason to hit the schedule endpoint every request


# NOTE: this must be registered before /api/picks/{sport} below -- FastAPI
# matches routes in registration order, and a {sport} path param would
# otherwise swallow "bullpen" as sport="bullpen" before this handler is
# ever reached (confirmed by testing; moved after finding this the hard way).
@app.get("/api/picks/bullpen")
async def get_bullpen():
    """Bullpen ERA/workload context for tonight's MLB slate, by team.

    Built entirely from data/mlb/raw/pitching_logs.csv (already refreshed
    nightly, is_starter-tagged) via src/sports/mlb/bullpen.py's leakage-safe
    rolling windows -- no new data source, and no added load on the
    gameLog/statSplits endpoints already under sustained degradation (see
    CLAUDE.md's 2026-07-28/08-03 incidents).

    Deliberately NOT included, flagged here instead of faked:
      - bullpen K% vs handedness: no Statcast/Savant integration exists in
        this pipeline. One was attempted before and reverted for silently
        serving wrong data (its pitch-hand filter was a no-op) -- adding a
        new external data source for this is a real project, not a
        same-day addition.
      - bullpen appearance probability: would need a starter
        expected-innings/leverage model that doesn't exist anywhere in
        this codebase. No shortcut available without inventing a number.
    """
    now = time.time()
    if _BULLPEN_CACHE["data"] is not None and now - _BULLPEN_CACHE["ts"] < _BULLPEN_CACHE_TTL:
        return _BULLPEN_CACHE["data"]

    logs_path = BASE_DIR / "data" / "mlb" / "raw" / "pitching_logs.csv"
    if not logs_path.exists():
        raise HTTPException(503, "pitching_logs.csv not found")
    logs = pd.read_csv(logs_path)
    logs["date"] = pd.to_datetime(logs["date"])

    as_of = pd.Timestamp.now().normalize()

    teams = {}
    try:
        r = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                          params={"sportId": 1, "date": as_of.strftime("%Y-%m-%d")}, timeout=12)
        if r.status_code == 200:
            games = r.json().get("dates", [{}])[0].get("games", [])
            for g in games:
                for side in ("away", "home"):
                    t = g["teams"][side]["team"]
                    teams[t["id"]] = t["name"]
    except Exception as e:
        print(f"[server] bullpen: schedule fetch failed: {e}")

    league_era = league_avg_bullpen_era(as_of, logs)
    league_workload = league_avg_bullpen_workload(as_of, logs)

    rows = []
    for team_id, name in teams.items():
        era = team_bullpen_era(team_id, as_of, logs)
        workload = team_bullpen_workload(team_id, as_of, logs)
        eff_workload = workload if workload is not None else league_workload
        if eff_workload >= league_workload * 1.25:
            fatigue = "tired"
        elif eff_workload <= league_workload * 0.6:
            fatigue = "fresh"
        else:
            fatigue = "normal"
        rows.append({
            "team": name,
            "team_abbr": _TEAM_ABBR.get(name, name[:3].upper() if name else ""),
            "bullpen_era": era if era is not None else league_era,
            "bullpen_era_is_team_specific": era is not None,
            "workload_ip_last_3d": eff_workload,
            "workload_is_team_specific": workload is not None,
            "fatigue": fatigue,
        })
    rows.sort(key=lambda x: x["bullpen_era"])

    result = {
        "date": as_of.strftime("%Y-%m-%d"),
        "league_avg_era_21d": league_era,
        "league_avg_workload_ip_3d": league_workload,
        "teams": rows,
        "not_available": {
            "k_pct_vs_handedness": "no Statcast/handedness bullpen data source wired in — flagged as future work, not faked",
            "appearance_probability": "no starter-depth/leverage model exists in this codebase — flagged as future work, not faked",
        },
    }
    _BULLPEN_CACHE["data"], _BULLPEN_CACHE["ts"] = result, now
    return result


@app.get("/api/picks/{sport}")
async def get_picks(sport: str, tier: str = None, min_score: float = 0):
    """Get all picks for a sport, optionally filtered."""
    sport = sport.upper()
    if sport not in ("MLB", "WNBA", "NBA"):
        raise HTTPException(404, f"Unknown sport: {sport}")
    
    df = load_and_enrich(sport.lower())
    picks = _scrub_nan(df_to_picks(df))
    
    # Apply filters
    if tier:
        picks = [p for p in picks if p["tier"] == tier.upper()]
    if min_score > 0:
        picks = [p for p in picks if p["score"] >= min_score]
    
    return {
        "sport": sport,
        "count": len(picks),
        "last_scan": _get_scan_time(sport.lower()),
        "model_trained_at": _get_model_trained_at(sport.lower()),
        "api_version": app.version,
        "picks": picks,
    }


@app.get("/api/picks/{sport}/{stat_type}")
async def get_picks_by_stat(sport: str, stat_type: str):
    """Get picks filtered by stat type (e.g., Hits, Strikeouts, Points)."""
    sport = sport.upper()
    df = load_and_enrich(sport.lower())
    picks = _scrub_nan(df_to_picks(df))
    
    # Filter by stat type (case-insensitive partial match)
    stat_lower = stat_type.lower().replace("_", " ")
    filtered = [p for p in picks if stat_lower in p["stat_type"].lower()]
    
    return {
        "sport": sport,
        "stat_type": stat_type,
        "count": len(filtered),
        "picks": filtered,
    }


@app.get("/api/stats/{sport}")
async def get_available_stats(sport: str):
    """Get available stat types for a sport."""
    sport = sport.upper()
    df = load_and_enrich(sport.lower())
    
    if df.empty:
        return {"sport": sport, "stats": []}
    
    stat_col = "stat_type" if "stat_type" in df.columns else "Stat_Label"
    stats = df[stat_col].unique().tolist() if stat_col in df.columns else []
    
    return {"sport": sport, "stats": sorted(stats)}


@app.get("/api/moneylines")
async def get_moneylines():
    """Get today's moneyline picks from the Odds API.

    Filtered to ACTIVE_SPORTS (src/core/moneylines.py) — fetch_moneylines()
    itself pulls NBA/MLB/WNBA together, but only MLB is a shipped tab right
    now, so non-active sports (e.g. WNBA) never reach the dashboard even if
    they're still in latest.csv. Add a sport there (e.g. NFL) to surface it
    here without touching this endpoint.
    """
    from src.core.moneylines import ACTIVE_SPORTS

    ml_path = OUTPUT_DIR / "moneylines" / "latest.csv"
    if not ml_path.exists():
        # Try running moneylines module
        try:
            sys.path.insert(0, str(BASE_DIR / "src" / "core"))
            from moneylines import get_moneylines
            data = get_moneylines()
            data = [g for g in data if g.get("Sport") in ACTIVE_SPORTS]
            return {"count": len(data), "games": data}
        except Exception:
            return {"count": 0, "games": []}

    df = pd.read_csv(ml_path)
    df = df[df["Sport"].isin(ACTIVE_SPORTS)]
    games = df.to_dict(orient="records")
    return {"count": len(games), "games": games}


@app.get("/api/meta")
async def get_meta():
    """Get scan metadata — last scan times, pick counts per sport."""
    meta = {}
    for sport in ["mlb", "wnba", "nba"]:
        csv_path = get_latest_csv(sport)
        if csv_path and csv_path.exists():
            df = pd.read_csv(csv_path)
            meta[sport.upper()] = {
                "last_scan": _get_scan_time(sport),
                "total_picks": len(df),
                "file": str(csv_path.name),
            }
        else:
            meta[sport.upper()] = {
                "last_scan": None,
                "total_picks": 0,
                "file": None,
            }
    
    return meta


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "timestamp": datetime.now().isoformat()}


def _get_scan_time(sport: str) -> str | None:
    csv_path = get_latest_csv(sport)
    if csv_path and csv_path.exists():
        mtime = csv_path.stat().st_mtime
        return datetime.fromtimestamp(mtime).isoformat()
    return None


def _get_model_trained_at(sport: str) -> str | None:
    """Latest trained_at across a sport's per-stat models (model_metrics.csv),
    so the dashboard can show how stale the model weights are — separate from
    last_scan, which only reflects when the (nightly-refreshed) input data
    was last scored, not when the model itself was last retrained."""
    metrics_path = BASE_DIR / "models" / sport.lower() / "model_metrics.csv"
    if not metrics_path.exists():
        return None
    try:
        df = pd.read_csv(metrics_path)
        if "trained_at" not in df.columns or df.empty:
            return None
        return str(df["trained_at"].max())
    except Exception:
        return None


# ─── Serve React frontend ───

@app.get("/app.jsx")
async def serve_appjsx():
    f = FRONTEND_DIR / "app.jsx"
    if f.exists():
        return FileResponse(str(f), media_type="text/babel")
    raise HTTPException(status_code=404, detail="app.jsx not found")


@app.get("/")
async def serve_index():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({
        "message": "Tank'd Picks v2 API",
        "docs": "/docs",
        "endpoints": ["/api/picks/mlb", "/api/picks/wnba", "/api/picks/nba", "/api/moneylines"],
    })


# Mount static files if frontend is built
if FRONTEND_DIR.exists():
    _assets_dir = FRONTEND_DIR / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
