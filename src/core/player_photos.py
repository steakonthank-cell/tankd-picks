"""
Player Photo Resolver
Builds a name → headshot URL mapping from ESPN's free scoreboard/summary APIs.
Caches to disk so it only refreshes once per day.
"""

import os, json, requests
from datetime import datetime
from zoneinfo import ZoneInfo

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_FILE = os.path.join(BASE_DIR, "data", "player_photos_cache.json")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

SPORT_CONFIGS = [
    ("basketball", "nba",      "nba"),
    ("baseball",   "mlb",      "mlb"),
    ("basketball", "wnba",     "wnba"),
    ("tennis",     "atp",      "tennis"),
]

def _safe_get(url, timeout=6):
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _extract_athletes_from_scoreboard(sport_key, league_key):
    """Pull athlete name→headshot from scoreboard leaders."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_key}/{league_key}/scoreboard"
    data = _safe_get(url)
    mapping = {}

    for event in data.get("events", []):
        for comp in event.get("competitions", [{}]):
            for team in comp.get("competitors", []):
                for leader_cat in team.get("leaders", []):
                    for leader in leader_cat.get("leaders", []):
                        ath = leader.get("athlete", {})
                        name = ath.get("displayName", "")
                        hs   = ath.get("headshot", "")
                        if isinstance(hs, dict):
                            hs = hs.get("href", "")
                        if name and hs:
                            mapping[name.lower()] = hs
    return mapping


def _fetch_sport_roster(sport_key, league_key, sport_label):
    """Fetch a broader set of players via ESPN athletes endpoint."""
    mapping = {}
    # Try multiple pages
    for page in range(1, 6):
        url = (f"https://sports.core.api.espn.com/v2/sports/{sport_key}/leagues/"
               f"{league_key}/athletes?limit=100&page={page}&active=true")
        data = _safe_get(url)
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            ref = item.get("$ref", "")
            if not ref:
                continue
            athlete = _safe_get(ref)
            name = athlete.get("displayName", "")
            hs = athlete.get("headshot", {})
            if isinstance(hs, dict):
                hs = hs.get("href", "")
            elif not isinstance(hs, str):
                hs = ""
            if name and hs:
                mapping[name.lower()] = hs
    return mapping


def build_photo_cache(force: bool = False) -> dict:
    """Build or load the name→URL photo cache."""
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

    # Load from disk if fresh
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                cached = json.load(f)
            if cached.get("date") == today:
                return cached.get("photos", {})
        except Exception:
            pass

    print("Building player photo cache from ESPN…")
    photos = {}

    for sport_key, league_key, _ in SPORT_CONFIGS:
        try:
            # Scoreboard leaders (fast)
            sb = _extract_athletes_from_scoreboard(sport_key, league_key)
            photos.update(sb)
            # Roster pages (slower but broader)
            roster = _fetch_sport_roster(sport_key, league_key, league_key)
            photos.update(roster)
        except Exception:
            pass

    print(f"  Cached {len(photos)} player photos")

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"date": today, "photos": photos}, f)

    return photos


_CACHE = None  # type: dict

def get_photo(player_name: str) -> str:
    """Return headshot URL for a player name, or empty string."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_photo_cache()
    nl = player_name.lower().strip()
    if nl in _CACHE:
        return _CACHE[nl]
    # Fuzzy: last name match
    parts = nl.split()
    if len(parts) >= 2:
        last = parts[-1]
        matches = [v for k, v in _CACHE.items() if k.endswith(last)]
        if len(matches) == 1:
            return matches[0]
    return ""


def enrich_df_with_photos(df, player_col="Player", photo_col="Image_URL"):
    """Add Image_URL column to a dataframe using ESPN headshots."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_photo_cache()
    if player_col not in df.columns:
        return df
    df = df.copy()
    df[photo_col] = df[player_col].apply(get_photo)
    return df
