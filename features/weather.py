"""
Tank'd Picks v2 — Weather Module
=================================
Fetches game-time weather for outdoor stadiums.
Indoor/retractable-roof parks are marked and return neutral conditions.

Requires: WEATHER_API_KEY in .env (free tier from openweathermap.org)

Usage:
    from features.weather import get_game_weather, weather_adjustment
    
    weather = get_game_weather("CHC", game_time="19:10")
    adj = weather_adjustment(weather, stat_type="HR")
"""

import os
import json
import time
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ─── Stadium info: coords + indoor/outdoor ───
STADIUMS = {
    "AZ":  {"lat": 33.4453, "lon": -112.0667, "indoor": True,  "name": "Chase Field"},
    "ATL": {"lat": 33.7350, "lon": -84.3900,  "indoor": False, "name": "Truist Park"},
    "BAL": {"lat": 39.2839, "lon": -76.6217,  "indoor": False, "name": "Camden Yards"},
    "BOS": {"lat": 42.3467, "lon": -71.0972,  "indoor": False, "name": "Fenway Park"},
    "CHC": {"lat": 41.9484, "lon": -87.6553,  "indoor": False, "name": "Wrigley Field"},
    "CWS": {"lat": 41.8299, "lon": -87.6338,  "indoor": False, "name": "Guaranteed Rate"},
    "CIN": {"lat": 39.0974, "lon": -84.5082,  "indoor": False, "name": "GABP"},
    "CLE": {"lat": 41.4962, "lon": -81.6852,  "indoor": False, "name": "Progressive Field"},
    "COL": {"lat": 39.7561, "lon": -104.9942, "indoor": False, "name": "Coors Field"},
    "DET": {"lat": 42.3390, "lon": -83.0485,  "indoor": False, "name": "Comerica Park"},
    "HOU": {"lat": 29.7572, "lon": -95.3555,  "indoor": True,  "name": "Minute Maid Park"},
    "KC":  {"lat": 39.0517, "lon": -94.4803,  "indoor": False, "name": "Kauffman Stadium"},
    "LAA": {"lat": 33.8003, "lon": -117.8827, "indoor": False, "name": "Angel Stadium"},
    "LAD": {"lat": 34.0739, "lon": -118.2400, "indoor": False, "name": "Dodger Stadium"},
    "MIA": {"lat": 25.7781, "lon": -80.2196,  "indoor": True,  "name": "loanDepot park"},
    "MIL": {"lat": 43.0280, "lon": -87.9712,  "indoor": True,  "name": "American Family Field"},
    "MIN": {"lat": 44.9817, "lon": -93.2783,  "indoor": False, "name": "Target Field"},
    "NYM": {"lat": 40.7571, "lon": -73.8458,  "indoor": False, "name": "Citi Field"},
    "NYY": {"lat": 40.8296, "lon": -73.9262,  "indoor": False, "name": "Yankee Stadium"},
    "ATH": {"lat": 37.7516, "lon": -122.2005, "indoor": False, "name": "Coliseum"},
    "PHI": {"lat": 39.9061, "lon": -75.1665,  "indoor": False, "name": "Citizens Bank Park"},
    "PIT": {"lat": 40.4469, "lon": -80.0058,  "indoor": False, "name": "PNC Park"},
    "SD":  {"lat": 32.7076, "lon": -117.1570, "indoor": False, "name": "Petco Park"},
    "SF":  {"lat": 37.7786, "lon": -122.3893, "indoor": False, "name": "Oracle Park"},
    "SEA": {"lat": 47.5914, "lon": -122.3325, "indoor": True,  "name": "T-Mobile Park"},
    "STL": {"lat": 38.6226, "lon": -90.1928,  "indoor": False, "name": "Busch Stadium"},
    "TB":  {"lat": 27.7682, "lon": -82.6534,  "indoor": True,  "name": "Tropicana Field"},
    "TEX": {"lat": 32.7512, "lon": -97.0832,  "indoor": True,  "name": "Globe Life Field"},
    "TOR": {"lat": 43.6414, "lon": -79.3894,  "indoor": True,  "name": "Rogers Centre"},
    "WSH": {"lat": 38.8730, "lon": -77.0074,  "indoor": False, "name": "Nationals Park"},
}

# Cache directory
CACHE_DIR = Path("/root/tankd-picks/cache/weather")


def _get_api_key():
    return os.environ.get("WEATHER_API_KEY", "")


def get_game_weather(home_team: str, game_time: str = "19:10") -> dict:
    """
    Get weather conditions at game time for a home team's stadium.
    
    Returns:
        {
            "temp_f": 72,
            "wind_mph": 12,
            "wind_dir": "SW",    # Compass direction
            "wind_blowing": "out",  # "out", "in", "cross", "calm" (park-specific)
            "humidity": 55,
            "condition": "clear",
            "indoor": False,
            "flags": ["WIND_OUT", "HOT"],
        }
    """
    team = home_team.upper()
    stadium = STADIUMS.get(team)
    
    if not stadium:
        return _neutral_weather()
    
    # Indoor stadiums — weather doesn't matter
    if stadium["indoor"]:
        return {
            "temp_f": 72, "wind_mph": 0, "wind_dir": "N/A",
            "wind_blowing": "calm", "humidity": 50,
            "condition": "indoor", "indoor": True, "flags": ["INDOOR"],
        }
    
    # Try API fetch
    api_key = _get_api_key()
    if api_key and HAS_REQUESTS:
        return _fetch_weather(stadium, api_key)
    
    # Fallback: return neutral
    return _neutral_weather()


def _fetch_weather(stadium: dict, api_key: str) -> dict:
    """Fetch weather from OpenWeatherMap API with caching."""
    cache_key = f"{stadium['lat']}_{stadium['lon']}"
    cached = _read_cache(cache_key)
    if cached:
        return cached
    
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={stadium['lat']}&lon={stadium['lon']}"
            f"&appid={api_key}&units=imperial"
        )
        resp = requests.get(url, timeout=5)
        data = resp.json()
        
        wind_mph = data.get("wind", {}).get("speed", 0)
        wind_deg = data.get("wind", {}).get("deg", 0)
        temp_f = data.get("main", {}).get("temp", 72)
        humidity = data.get("main", {}).get("humidity", 50)
        condition = data.get("weather", [{}])[0].get("main", "Clear").lower()
        
        wind_dir = _deg_to_compass(wind_deg)
        
        flags = []
        if wind_mph >= 15:
            flags.append("WINDY")
        if temp_f >= 90:
            flags.append("HOT")
        elif temp_f <= 50:
            flags.append("COLD")
        if humidity >= 80:
            flags.append("HUMID")
        if "rain" in condition:
            flags.append("RAIN_RISK")
        
        result = {
            "temp_f": round(temp_f),
            "wind_mph": round(wind_mph),
            "wind_dir": wind_dir,
            "wind_blowing": "out" if wind_mph >= 10 else "calm",  # Simplified
            "humidity": round(humidity),
            "condition": condition,
            "indoor": False,
            "flags": flags,
        }
        
        _write_cache(cache_key, result)
        return result
        
    except Exception:
        return _neutral_weather()


def _neutral_weather():
    return {
        "temp_f": 72, "wind_mph": 5, "wind_dir": "N",
        "wind_blowing": "calm", "humidity": 50,
        "condition": "clear", "indoor": False, "flags": [],
    }


def _deg_to_compass(deg):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(deg / 22.5) % 16]


def _read_cache(key):
    """Read from 1-hour cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{key}.json"
        if path.exists() and (time.time() - path.stat().st_mtime) < 3600:
            return json.loads(path.read_text())
    except Exception:
        pass
    return None


def _write_cache(key, data):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{key}.json"
        path.write_text(json.dumps(data))
    except Exception:
        pass


def weather_adjustment(weather: dict, stat_type: str) -> float:
    """
    Returns edge multiplier based on weather conditions.
    
    Key interactions:
    - Wind blowing out + HR/TB props = boost
    - Cold weather = suppresses offense
    - Hot + humid = ball carries further
    - Rain risk = suppress everything slightly
    """
    if weather.get("indoor"):
        return 1.0
    
    adj = 1.0
    temp = weather.get("temp_f", 72)
    wind = weather.get("wind_mph", 0)
    flags = weather.get("flags", [])
    
    # Stat-type checks below match both the full display labels this
    # function was originally written against ("Hits", "Total Bases",
    # "Strikeouts") and the short scan codes actually passed at runtime
    # (H, TB, K, SO) — previously only full labels were listed, so those
    # short codes never matched and silently got no weather adjustment at
    # all. Each branch keeps its original stat membership; only the missing
    # short-code equivalent of each already-listed full label is added.

    # Temperature effects
    if temp >= 85:
        if stat_type in ("HR", "HRR", "Total Bases", "Hits", "TB", "H"):
            adj += 0.03  # Heat helps offense slightly
    elif temp <= 55:
        if stat_type in ("HR", "HRR", "Total Bases", "TB"):
            adj -= 0.05  # Cold suppresses power
        if stat_type in ("Strikeouts", "K", "SO"):
            adj += 0.03  # Cold helps pitchers

    # Wind effects (simplified — ideally track direction relative to park)
    if wind >= 15:
        if stat_type in ("HR", "HRR", "Total Bases", "TB"):
            adj += 0.05  # Strong wind, assume some blowing out
        if stat_type in ("Strikeouts", "K", "SO"):
            adj -= 0.02
    
    # Rain risk
    if "RAIN_RISK" in flags:
        adj -= 0.03  # Slight suppression across the board
    
    return round(adj, 3)


if __name__ == "__main__":
    print("=== Stadium Indoor/Outdoor ===")
    for team, info in sorted(STADIUMS.items()):
        if info["indoor"]:
            print(f"  {team}: {info['name']} (INDOOR)")
    
    print("\n=== Weather at Outdoor Parks (no API key, neutral) ===")
    for team in ["CHC", "COL", "BOS", "SF"]:
        w = get_game_weather(team)
        print(f"  {team}: {w}")
