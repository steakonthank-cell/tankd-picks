"""
ESPN Free Odds Fetcher  —  enriched with team context
Pulls moneylines + team records, home/away splits, recent form,
MLB starting pitcher stats. Computes a composite AI confidence score.

Supports: NBA, MLB, WNBA
"""

import requests
import json
import os
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

ESPN_SPORTS = {
    "NBA":  ("basketball", "nba"),
    "MLB":  ("baseball",   "mlb"),
    "WNBA": ("basketball", "wnba"),
}

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "espn_odds_cache.json"
)


def _scoreboard_url(sport_key, league_key, date_str=None):
    base = f"https://site.api.espn.com/apis/site/v2/sports/{sport_key}/{league_key}/scoreboard"
    if date_str:
        return f"{base}?dates={date_str}"
    return base


def _odds_url(sport_key, league_key, event_id):
    return (
        f"https://sports.core.api.espn.com/v2/sports/{sport_key}/leagues/"
        f"{league_key}/events/{event_id}/competitions/{event_id}/odds?limit=10"
    )


def _safe_get(url, timeout=6):
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _valid_ml(v):
    try:
        return v is not None and abs(int(v)) >= 100
    except Exception:
        return False


def _win_pct_from_ml(ml):
    if ml is None or not _valid_ml(ml):
        return 50.0
    if ml < 0:
        return round(abs(ml) / (abs(ml) + 100) * 100, 1)
    return round(100 / (ml + 100) * 100, 1)


def _parse_record(records, rec_type="total"):
    """Parse W-L from ESPN records list. Returns (wins, losses, win_pct) or None."""
    for r in (records or []):
        if r.get("type") == rec_type or r.get("name", "").lower() == rec_type:
            try:
                w, l = r["summary"].split("-")
                w, l = int(w), int(l)
                total = w + l
                return w, l, round(w / total * 100, 1) if total else 50.0
            except Exception:
                pass
    return None


def _parse_home_away_record(records, is_home):
    """Return win% for home or road record."""
    target = "home" if is_home else "road"
    for r in (records or []):
        if r.get("type", "").lower() == target or r.get("name", "").lower() == target:
            try:
                w, l = r["summary"].split("-")
                w, l = int(w), int(l)
                total = w + l
                return round(w / total * 100, 1) if total else None
            except Exception:
                pass
    return None


def _get_pitcher_info(probables):
    """
    Fetch starting pitcher name, handedness (L/R), W-L record, and quality score.
    Returns (name, hand, wins, losses, score).
    """
    if not probables:
        return None, None, 0, 0, 50.0
    try:
        p      = probables[0]
        ath    = p.get("athlete", {})
        name   = ath.get("fullName", "TBD")
        ath_id = ath.get("id", "")
        stats  = {s["name"]: s["displayValue"] for s in p.get("statistics", [])}
        wins   = int(stats.get("wins",   0) or 0)
        losses = int(stats.get("losses", 0) or 0)
        total  = wins + losses
        score  = round(wins / total * 100, 1) if total else 50.0

        # Fetch handedness from athlete detail endpoint
        hand = None
        if ath_id:
            detail = _safe_get(
                f"https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/athletes/{ath_id}",
                timeout=4
            )
            throws = detail.get("throws", {})
            hand = throws.get("abbreviation")  # "R" or "L"

        return name, hand, wins, losses, score
    except Exception:
        return None, None, 0, 0, 50.0


def _composite_confidence(
    ml_pct,           # implied win% from moneyline (0–100)
    overall_wpct,     # season win% (0–100) or None
    home_away_wpct,   # home/road win% (0–100) or None
    pitcher_score,    # pitcher quality score (0–100) or None  [MLB only]
    sport_label,
):
    """
    Weighted composite confidence score for a team winning.
    Returns a float 0–100.

    Weights vary by sport:
      MLB:  odds 40% + overall record 20% + home/away 20% + pitcher 20%
      NBA:  odds 45% + overall record 30% + home/away 25%
      WNBA: odds 50% + overall record 30% + home/away 20%
    """
    if sport_label == "MLB":
        components = [
            (ml_pct,           0.40),
            (overall_wpct,     0.20),
            (home_away_wpct,   0.20),
            (pitcher_score,    0.20),
        ]
    elif sport_label == "NBA":
        components = [
            (ml_pct,           0.45),
            (overall_wpct,     0.30),
            (home_away_wpct,   0.25),
        ]
    else:  # WNBA
        components = [
            (ml_pct,           0.50),
            (overall_wpct,     0.30),
            (home_away_wpct,   0.20),
        ]

    total_w = 0.0
    score   = 0.0
    for val, w in components:
        if val is not None:
            score   += val * w
            total_w += w

    if total_w == 0:
        raw = ml_pct
    else:
        # Re-normalise to account for any missing components
        raw = score / total_w

    # Stretch from the tight 40-70% band to a more expressive 12-88% range.
    # A 2.5× amplification of the deviation from 50 makes strong signals
    # read as genuinely high/low confidence instead of clustering near 50.
    stretched = 50.0 + (raw - 50.0) * 2.5
    return round(min(88.0, max(12.0, stretched)), 1)


def _fetch_sport_events(sport_label, sport_key, league_key, now_et, today, today_compact):
    """Fetch events + lookahead for one sport. Returns (sport_label, events, min_date)."""
    _SKIP_STATUSES = {"STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_IN_PROGRESS",
                      "STATUS_HALFTIME", "STATUS_END_PERIOD", "STATUS_POSTPONED",
                      "STATUS_CANCELLED", "STATUS_DELAYED"}
    sb     = _safe_get(_scoreboard_url(sport_key, league_key, date_str=today_compact))
    events = sb.get("events", [])
    min_date = today
    if not events:
        for _ahead in range(1, 4):
            _next_compact = (now_et + timedelta(days=_ahead)).strftime("%Y%m%d")
            _next_et      = (now_et + timedelta(days=_ahead)).strftime("%Y-%m-%d")
            sb2    = _safe_get(_scoreboard_url(sport_key, league_key, date_str=_next_compact))
            events2 = sb2.get("events", [])
            if any(
                e.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("name")
                not in _SKIP_STATUSES
                for e in events2
            ):
                events   = events2
                min_date = _next_et
                break
    return sport_label, events, min_date


def _process_event(event, sport_label, sport_key, league_key, today, min_date):
    """Process one event: fetch odds + pitcher info, return list of team rows."""
    _SKIP_STATUSES = {"STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_IN_PROGRESS",
                      "STATUS_HALFTIME", "STATUS_END_PERIOD", "STATUS_POSTPONED",
                      "STATUS_CANCELLED", "STATUS_DELAYED"}
    try:
        comp        = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            return []
        status_name = comp.get("status", {}).get("type", {}).get("name", "")
        if status_name in _SKIP_STATUSES:
            return []

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        home_name = home["team"]["displayName"]
        away_name = away["team"]["displayName"]

        game_dt = event.get("date", "")
        try:
            dt        = datetime.fromisoformat(game_dt.replace("Z", "+00:00"))
            dt_et     = dt.astimezone(ZoneInfo("America/New_York"))
            game_date = dt_et.strftime("%Y-%m-%d")
            game_time = dt_et.strftime("%-I:%M %p ET")
        except Exception:
            game_date = today
            game_time = ""

        if game_date < min_date:
            return []

        home_rec  = _parse_record(home.get("records"), "total")
        away_rec  = _parse_record(away.get("records"), "total")
        home_ovwpct     = home_rec[2] if home_rec else None
        away_ovwpct     = away_rec[2] if away_rec else None
        home_hawpct     = _parse_home_away_record(home.get("records"), is_home=True)
        away_hawpct     = _parse_home_away_record(away.get("records"), is_home=False)
        home_record_str = f"{home_rec[0]}-{home_rec[1]}" if home_rec else ""
        away_record_str = f"{away_rec[0]}-{away_rec[1]}" if away_rec else ""

        # Fetch odds + pitcher info in parallel
        event_id = event.get("id", "")
        with ThreadPoolExecutor(max_workers=3) as _ex:
            fut_odds  = _ex.submit(_safe_get, _odds_url(sport_key, league_key, event_id))
            fut_hp    = _ex.submit(_get_pitcher_info, home.get("probables")) if sport_label == "MLB" else None
            fut_ap    = _ex.submit(_get_pitcher_info, away.get("probables")) if sport_label == "MLB" else None
            odds_data = fut_odds.result()
            if fut_hp:
                home_pitcher, home_hand, home_pw, home_pl, home_p_score = fut_hp.result()
                away_pitcher, away_hand, away_pw, away_pl, away_p_score = fut_ap.result()
            else:
                home_pitcher = away_pitcher = None
                home_hand = away_hand = None
                home_pw = home_pl = away_pw = away_pl = 0
                home_p_score = away_p_score = 50.0

        odds_items = odds_data.get("items", [])
        book_odds  = {}
        home_ml = away_ml = None
        over_odds = under_odds = total = None

        for item in odds_items:
            book = item.get("provider", {}).get("name", "DraftKings")
            h_ml = item.get("homeTeamOdds", {}).get("moneyLine")
            a_ml = item.get("awayTeamOdds", {}).get("moneyLine")
            ou   = item.get("overUnder")
            ov   = item.get("overOdds")
            un   = item.get("underOdds")
            if _valid_ml(h_ml) and home_ml is None:
                home_ml    = h_ml
                away_ml    = a_ml if _valid_ml(a_ml) else None
                total      = ou
                over_odds  = ov
                under_odds = un
            if _valid_ml(h_ml):
                entry = {"home": h_ml}
                if _valid_ml(a_ml):
                    entry["away"] = a_ml
                book_odds[book] = entry

        if home_ml is None:
            return []

        home_ml_pct = _win_pct_from_ml(home_ml)
        away_ml_pct = _win_pct_from_ml(away_ml) if away_ml else (100 - home_ml_pct)
        home_conf   = _composite_confidence(home_ml_pct, home_ovwpct, home_hawpct,
                                            home_p_score if sport_label == "MLB" else None, sport_label)
        away_conf   = _composite_confidence(away_ml_pct, away_ovwpct, away_hawpct,
                                            away_p_score if sport_label == "MLB" else None, sport_label)

        def _best_odds(ml_dict, side):
            vals = [v.get(side) for v in ml_dict.values() if v.get(side) is not None]
            if not vals: return None
            return max(vals, key=lambda x: x if x >= 0 else 1 / abs(x))

        def _avg(ml_dict, side):
            vals = [v.get(side) for v in ml_dict.values() if v.get(side) is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        best_home       = _best_odds(book_odds, "home") or home_ml
        best_away       = _best_odds(book_odds, "away") or away_ml
        books_flat_home = {bk: v["home"] for bk, v in book_odds.items() if v.get("home")}
        books_flat_away = {bk: v["away"] for bk, v in book_odds.items() if v.get("away")}

        rows = []
        for (team_name, opp_name, ml, ml_pct, conf,
             is_home, best, books_flat,
             record_str, ha_wpct,
             pitcher_name, pitcher_hand, pitcher_w, pitcher_l, p_score) in [
            (home_name, away_name, home_ml, home_ml_pct, home_conf,
             True,  best_home, books_flat_home,
             home_record_str, home_hawpct,
             home_pitcher, home_hand, home_pw, home_pl, home_p_score),
            (away_name, home_name, away_ml, away_ml_pct, away_conf,
             False, best_away, books_flat_away,
             away_record_str, away_hawpct,
             away_pitcher, away_hand, away_pw, away_pl, away_p_score),
        ]:
            rows.append({
                "Sport":        sport_label,
                "Team":         team_name,
                "Opponent":     opp_name,
                "Home":         is_home,
                "Date":         game_date,
                "Time":         game_time,
                "Avg Odds":     _avg(book_odds, "home" if is_home else "away") or ml,
                "Best Odds":    best,
                "Best Book":    next(
                    (bk for bk, v in book_odds.items()
                     if v.get("home" if is_home else "away") == best),
                    "ESPN"
                ),
                "Win %":        ml_pct,
                "AI Conf":      conf,
                "Record":       record_str,
                "HA Win%":      ha_wpct,
                "Pitcher":       pitcher_name,
                "Pitcher Hand":  pitcher_hand,
                "Pitcher W":     pitcher_w,
                "Pitcher L":     pitcher_l,
                "Pitcher Score": p_score,
                "Game Total":   total,
                "Over Odds":    over_odds,
                "Under Odds":   under_odds,
                "Source":       "ESPN (free)",
                **books_flat,
            })
        return rows
    except Exception:
        return []


def fetch_espn_odds():
    """
    Fetch today's game odds + team context across NBA, MLB, WNBA.
    All three sports fetched in parallel; per-game odds + pitcher fetched in parallel.
    Returns list of enriched dicts.
    """
    now_et        = datetime.now(ZoneInfo("America/New_York"))
    today         = now_et.strftime("%Y-%m-%d")
    today_compact = now_et.strftime("%Y%m%d")

    # Fetch all three sport scoreboards in parallel
    sport_events = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {
            ex.submit(_fetch_sport_events, sl, sk, lk, now_et, today, today_compact): sl
            for sl, (sk, lk) in ESPN_SPORTS.items()
        }
        for fut in as_completed(futs):
            sl, events, min_date = fut.result()
            sport_events[sl] = (events, min_date)

    # Process all events across all sports in parallel
    results = []
    tasks = []
    for sport_label, (sport_key, league_key) in ESPN_SPORTS.items():
        events, min_date = sport_events.get(sport_label, ([], today))
        for event in events:
            tasks.append((event, sport_label, sport_key, league_key, today, min_date))

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_process_event, *t) for t in tasks]
        for fut in as_completed(futs):
            results.extend(fut.result())

    # Cache to disk
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({"date": today, "data": results}, f)
    except Exception:
        pass

    return results


def load_cached_espn_odds():
    try:
        with open(CACHE_FILE) as f:
            cached = json.load(f)
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if cached.get("date") == today:
            return cached["data"]
    except Exception:
        pass
    return []


def get_espn_odds(force_refresh=False):
    if not force_refresh:
        cached = load_cached_espn_odds()
        if cached:
            return cached
    return fetch_espn_odds()
