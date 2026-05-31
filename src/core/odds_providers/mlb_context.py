"""
MLB Game Context
- Park factors   (static 3-year rolling averages, applied to AI projections)
- Vegas totals   (Odds API — game O/U + implied team run totals)
- Weather/wind   (Open-Meteo, free, no key — wind speed/dir/temp per ballpark)
- Batting order  (MLB Stats API — PA adjustment once lineups are posted)

Usage:
    from src.core.odds_providers.mlb_context import get_game_context
    team_ctx, bat_orders = get_game_context()

    # Per-batter: ctx = team_ctx.get('Detroit Tigers', {})
    # bat_pos = bat_orders.get(norm_name, {}).get('bat_order', 0)
"""

import os, json, time, unicodedata, requests
from datetime import date as date_cls

CACHE_DIR  = 'pickfinder_cache'
CACHE_FILE = os.path.join(CACHE_DIR, 'mlb_context.json')
CACHE_MIN  = 20

_MLB_API = "https://statsapi.mlb.com/api/v1"
_http    = requests.Session()
_http.headers.update({"User-Agent": "Mozilla/5.0"})


# ---------------------------------------------------------------------------
# Park Factors  (1.00 = league average; >1 = hitter-friendly for that stat)
# Source: Statcast/Baseball Reference 3-year park factors, normalized.
# Keys match MLB Stats API team names exactly.
# ---------------------------------------------------------------------------
PARK_FACTORS = {
    # Big hitter parks
    'Colorado Rockies':      {'HR': 1.30, 'TB': 1.15, 'H': 1.12, 'R': 1.18, 'RBI': 1.15, 'K': 0.92, 'ER': 1.20, 'OUTS': 0.93},
    'Cincinnati Reds':       {'HR': 1.15, 'TB': 1.08, 'H': 1.03, 'R': 1.06, 'RBI': 1.06, 'K': 0.97, 'ER': 1.10, 'OUTS': 0.98},
    'New York Yankees':      {'HR': 1.12, 'TB': 1.06, 'H': 1.00, 'R': 1.04, 'RBI': 1.04, 'K': 1.00, 'ER': 1.06, 'OUTS': 1.00},
    'Philadelphia Phillies': {'HR': 1.10, 'TB': 1.05, 'H': 1.01, 'R': 1.04, 'RBI': 1.04, 'K': 0.98, 'ER': 1.06, 'OUTS': 0.99},
    'Chicago White Sox':     {'HR': 1.10, 'TB': 1.05, 'H': 1.01, 'R': 1.04, 'RBI': 1.04, 'K': 0.98, 'ER': 1.06, 'OUTS': 0.99},
    'Baltimore Orioles':     {'HR': 1.08, 'TB': 1.05, 'H': 1.02, 'R': 1.04, 'RBI': 1.04, 'K': 0.98, 'ER': 1.06, 'OUTS': 0.99},
    'Texas Rangers':         {'HR': 1.08, 'TB': 1.04, 'H': 1.01, 'R': 1.03, 'RBI': 1.03, 'K': 0.99, 'ER': 1.06, 'OUTS': 1.00},
    'Chicago Cubs':          {'HR': 1.05, 'TB': 1.03, 'H': 1.02, 'R': 1.03, 'RBI': 1.03, 'K': 0.98, 'ER': 1.04, 'OUTS': 0.99},
    'Boston Red Sox':        {'HR': 1.05, 'TB': 1.08, 'H': 1.05, 'R': 1.05, 'RBI': 1.04, 'K': 0.98, 'ER': 1.05, 'OUTS': 0.99},
    'Arizona Diamondbacks':  {'HR': 1.05, 'TB': 1.03, 'H': 1.01, 'R': 1.03, 'RBI': 1.03, 'K': 0.99, 'ER': 1.03, 'OUTS': 1.00},
    'Toronto Blue Jays':     {'HR': 1.05, 'TB': 1.02, 'H': 1.00, 'R': 1.02, 'RBI': 1.02, 'K': 0.99, 'ER': 1.02, 'OUTS': 1.00},
    'Milwaukee Brewers':     {'HR': 1.05, 'TB': 1.02, 'H': 1.01, 'R': 1.02, 'RBI': 1.02, 'K': 0.99, 'ER': 1.02, 'OUTS': 1.00},
    'Houston Astros':        {'HR': 1.02, 'TB': 1.01, 'H': 1.00, 'R': 1.01, 'RBI': 1.01, 'K': 1.00, 'ER': 1.01, 'OUTS': 1.00},
    # Near-neutral parks
    'Atlanta Braves':        {'HR': 0.97, 'TB': 1.00, 'H': 1.00, 'R': 1.00, 'RBI': 1.00, 'K': 1.00, 'ER': 1.00, 'OUTS': 1.00},
    'Minnesota Twins':       {'HR': 0.97, 'TB': 1.00, 'H': 1.00, 'R': 1.00, 'RBI': 1.00, 'K': 1.00, 'ER': 1.00, 'OUTS': 1.00},
    'Cleveland Guardians':   {'HR': 0.97, 'TB': 0.99, 'H': 1.00, 'R': 0.99, 'RBI': 0.99, 'K': 1.00, 'ER': 0.99, 'OUTS': 1.00},
    'Washington Nationals':  {'HR': 0.97, 'TB': 0.99, 'H': 1.00, 'R': 0.99, 'RBI': 0.99, 'K': 1.00, 'ER': 0.99, 'OUTS': 1.00},
    'Los Angeles Dodgers':   {'HR': 0.95, 'TB': 0.98, 'H': 0.99, 'R': 0.98, 'RBI': 0.98, 'K': 1.01, 'ER': 0.97, 'OUTS': 1.01},
    'St. Louis Cardinals':   {'HR': 0.95, 'TB': 0.98, 'H': 1.00, 'R': 0.98, 'RBI': 0.98, 'K': 1.01, 'ER': 0.97, 'OUTS': 1.01},
    'New York Mets':         {'HR': 0.95, 'TB': 0.98, 'H': 0.99, 'R': 0.98, 'RBI': 0.98, 'K': 1.01, 'ER': 0.97, 'OUTS': 1.01},
    # Pitcher-friendly
    'Kansas City Royals':    {'HR': 0.93, 'TB': 0.97, 'H': 1.00, 'R': 0.97, 'RBI': 0.97, 'K': 1.01, 'ER': 0.95, 'OUTS': 1.01},
    'Detroit Tigers':        {'HR': 0.93, 'TB': 0.97, 'H': 0.99, 'R': 0.97, 'RBI': 0.97, 'K': 1.01, 'ER': 0.95, 'OUTS': 1.01},
    'Tampa Bay Rays':        {'HR': 0.92, 'TB': 0.97, 'H': 0.98, 'R': 0.97, 'RBI': 0.97, 'K': 1.01, 'ER': 0.95, 'OUTS': 1.01},
    'Pittsburgh Pirates':    {'HR': 0.92, 'TB': 0.97, 'H': 0.99, 'R': 0.97, 'RBI': 0.97, 'K': 1.01, 'ER': 0.95, 'OUTS': 1.01},
    'Miami Marlins':         {'HR': 0.92, 'TB': 0.96, 'H': 0.98, 'R': 0.96, 'RBI': 0.96, 'K': 1.01, 'ER': 0.95, 'OUTS': 1.01},
    'Los Angeles Angels':    {'HR': 0.90, 'TB': 0.96, 'H': 0.99, 'R': 0.96, 'RBI': 0.96, 'K': 1.01, 'ER': 0.94, 'OUTS': 1.01},
    'San Diego Padres':      {'HR': 0.88, 'TB': 0.95, 'H': 0.97, 'R': 0.95, 'RBI': 0.95, 'K': 1.02, 'ER': 0.93, 'OUTS': 1.02},
    'Seattle Mariners':      {'HR': 0.88, 'TB': 0.95, 'H': 0.97, 'R': 0.95, 'RBI': 0.95, 'K': 1.02, 'ER': 0.93, 'OUTS': 1.02},
    'Oakland Athletics':     {'HR': 0.85, 'TB': 0.93, 'H': 0.95, 'R': 0.93, 'RBI': 0.93, 'K': 1.03, 'ER': 0.90, 'OUTS': 1.03},
    'San Francisco Giants':  {'HR': 0.82, 'TB': 0.93, 'H': 0.96, 'R': 0.93, 'RBI': 0.93, 'K': 1.03, 'ER': 0.90, 'OUTS': 1.03},
}

# Parks where weather has minimal effect (retractable or fixed dome)
INDOOR_PARKS = {
    'Tampa Bay Rays',        # Tropicana Field — fixed dome
    'Toronto Blue Jays',     # Rogers Centre — retractable
    'Milwaukee Brewers',     # American Family Field — retractable
    'Houston Astros',        # Minute Maid Park — retractable
    'Arizona Diamondbacks',  # Chase Field — retractable
    'Miami Marlins',         # loanDepot park — retractable
    'Seattle Mariners',      # T-Mobile Park — retractable
    'Texas Rangers',         # Globe Life Field — retractable
}

# (lat, lon) for outdoor ballparks — used for Open-Meteo weather API
STADIUM_COORDS = {
    'Colorado Rockies':      (39.7559, -104.9942),  # Coors Field
    'Cincinnati Reds':       (39.0974,  -84.5065),  # GABP
    'Boston Red Sox':        (42.3467,  -71.0972),  # Fenway Park
    'New York Yankees':      (40.8296,  -73.9262),  # Yankee Stadium
    'San Diego Padres':      (32.7076, -117.1570),  # Petco Park
    'San Francisco Giants':  (37.7786, -122.3893),  # Oracle Park
    'Atlanta Braves':        (33.8908,  -84.4678),  # Truist Park
    'Los Angeles Dodgers':   (34.0739, -118.2400),  # Dodger Stadium
    'Baltimore Orioles':     (39.2838,  -76.6218),  # Camden Yards
    'Chicago White Sox':     (41.8299,  -87.6338),  # Guaranteed Rate Field
    'Cleveland Guardians':   (41.4954,  -81.6854),  # Progressive Field
    'Detroit Tigers':        (42.3390,  -83.0485),  # Comerica Park
    'Kansas City Royals':    (39.0517,  -94.4803),  # Kauffman Stadium
    'Minnesota Twins':       (44.9817,  -93.2781),  # Target Field
    'Chicago Cubs':          (41.9484,  -87.6553),  # Wrigley Field
    'St. Louis Cardinals':   (38.6226,  -90.1928),  # Busch Stadium
    'Pittsburgh Pirates':    (40.4469,  -80.0057),  # PNC Park
    'New York Mets':         (40.7571,  -73.8458),  # Citi Field
    'Philadelphia Phillies': (39.9057,  -75.1665),  # Citizens Bank Park
    'Washington Nationals':  (38.8730,  -77.0074),  # Nationals Park
    'Los Angeles Angels':    (33.8003, -117.8827),  # Angel Stadium
    'Oakland Athletics':     (38.5802, -121.5085),  # Sutter Health Park (Sacramento)
}

# Expected PA per batting order slot (MLB average: ~3.90 PA per game)
_PA_BY_SLOT  = {1: 4.25, 2: 4.15, 3: 4.05, 4: 4.00, 5: 3.95,
                6: 3.85, 7: 3.75, 8: 3.60, 9: 3.50}
_PA_AVERAGE  = 3.90


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    n = unicodedata.normalize('NFKD', name)
    return ''.join(c for c in n if not unicodedata.combining(c)).lower().strip()


def _deg_to_compass(deg: float) -> str:
    return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][round(float(deg) / 45) % 8]


def _get_weather(lat: float, lon: float) -> dict:
    """Current conditions from Open-Meteo (free, no key)."""
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            'latitude': lat, 'longitude': lon,
            'current': 'wind_speed_10m,wind_direction_10m,temperature_2m',
            'wind_speed_unit': 'mph',
            'temperature_unit': 'fahrenheit',
            'timezone': 'auto',
        }, timeout=8)
        if r.status_code != 200:
            return {}
        cur = r.json().get('current', {})
        return {
            'wind_speed': round(float(cur.get('wind_speed_10m',  0)), 1),
            'wind_dir':   _deg_to_compass(cur.get('wind_direction_10m', 0)),
            'temp_f':     round(float(cur.get('temperature_2m', 0)), 0),
        }
    except Exception:
        return {}


def _get_game_totals(api_key: str) -> dict:
    """Fetch today's MLB game totals + run lines from The Odds API."""
    if not api_key:
        return {}
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
            params={'apiKey': api_key, 'regions': 'us',
                    'markets': 'totals,spreads', 'oddsFormat': 'american'},
            timeout=12)
        if r.status_code != 200:
            print(f"   Odds API HTTP {r.status_code}")
            return {}
        result = {}
        for game in r.json():
            home = game.get('home_team', '')
            away = game.get('away_team', '')
            game_total = spread = None
            for bk in game.get('bookmakers', []):
                for mkt in bk.get('markets', []):
                    if mkt['key'] == 'totals' and game_total is None:
                        for o in mkt['outcomes']:
                            if o['name'] == 'Over':
                                game_total = float(o['point'])
                    elif mkt['key'] == 'spreads' and spread is None:
                        for o in mkt['outcomes']:
                            if o['name'] == home:
                                spread = float(o['point'])  # negative = home favored
                if game_total is not None:
                    break
            if game_total:
                sp = spread or 0.0
                result[(_norm(home), _norm(away))] = {
                    'total':        game_total,
                    'home_implied': round((game_total - sp) / 2, 1),
                    'away_implied': round((game_total + sp) / 2, 1),
                }
        return result
    except Exception as e:
        print(f"   Odds API error: {e}")
        return {}


def _get_batting_orders(date_str: str) -> dict:
    """
    Fetch today's batting lineups from MLB Stats API.
    Returns {norm_player_name: {'bat_order': int (1-9), 'team': str}}
    Only populated once lineups are officially posted (~2-3h pre-game).
    """
    result = {}
    try:
        r = _http.get(f"{_MLB_API}/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "lineups,team"},
            timeout=12)
        if r.status_code != 200:
            return result
        games = r.json().get('dates', [{}])[0].get('games', [])
        for game in games:
            for side in ('home', 'away'):
                team_data = game['teams'][side]
                team_name = team_data['team']['name']
                lineups   = team_data.get('lineups') or {}
                batting   = lineups.get('batting', []) or []
                for pos, player in enumerate(batting, 1):
                    pname = (player.get('fullName') or
                             player.get('person', {}).get('fullName', ''))
                    if pname:
                        result[_norm(pname)] = {'bat_order': pos, 'team': team_name}
    except Exception as e:
        print(f"   Lineup fetch error: {e}")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_game_context(date_str: str = None) -> tuple:
    """
    Build full game context for every team playing today.

    Returns:
        team_context — {team_name: {
            'park_factors': dict,     # stat → multiplier
            'is_home': bool,
            'is_indoor': bool,
            'total': float|None,      # game O/U
            'implied': float|None,    # THIS team's implied run total
            'wind_speed': float|None,
            'wind_dir': str,
            'temp_f': float|None,
            'wind_boost': float,      # HR/TB multiplier from wind (outdoor only)
        }}
        bat_orders — {norm_player_name: {'bat_order': int (1-9), 'team': str}}
    """
    # Cache check
    try:
        if os.path.exists(CACHE_FILE):
            age = (time.time() - os.path.getmtime(CACHE_FILE)) / 60
            if age < CACHE_MIN:
                with open(CACHE_FILE) as f:
                    cached = json.load(f)
                n = len(cached.get('bat_orders', {}))
                print(f"   Using cached game context ({n} lineup slots)")
                return cached.get('team_context', {}), cached.get('bat_orders', {}), cached.get('player_to_team', {})
    except Exception:
        pass

    today = date_str or date_cls.today().strftime('%Y-%m-%d')
    print(f"   Fetching game context for {today}...")

    from src.sports.mlb.config import ODDS_API_KEY
    game_totals = _get_game_totals(ODDS_API_KEY)
    bat_orders  = _get_batting_orders(today)
    n_lo = len(bat_orders)
    print(f"   Totals: {len(game_totals)} games | Lineups: {n_lo} players posted")

    # Today's schedule for park/weather mapping
    try:
        r = _http.get(f"{_MLB_API}/schedule",
            params={"sportId": 1, "date": today, "hydrate": "team"},
            timeout=12)
        games_raw = (r.json().get('dates', [{}])[0].get('games', [])
                     if r.status_code == 200 else [])
    except Exception:
        games_raw = []

    team_context   = {}
    player_to_team = {}   # norm_player_name → team_name (from active rosters)

    for game in games_raw:
        home    = game['teams']['home']['team']['name']
        away    = game['teams']['away']['team']['name']
        home_id = game['teams']['home']['team']['id']
        away_id = game['teams']['away']['team']['id']

        # Build player→team from active rosters (both sides)
        for team_name, team_id in [(home, home_id), (away, away_id)]:
            try:
                rr = _http.get(f"{_MLB_API}/teams/{team_id}/roster",
                    params={"rosterType": "active", "season": 2026}, timeout=10)
                if rr.status_code == 200:
                    for p in rr.json().get('roster', []):
                        pname = p['person']['fullName']
                        player_to_team[_norm(pname)] = team_name
            except Exception:
                pass

        pf         = PARK_FACTORS.get(home, {})
        is_indoor  = home in INDOOR_PARKS

        # Match Odds API totals (names normalized)
        hn, an    = _norm(home), _norm(away)
        tot_entry = {}
        for (h2, a2), v in game_totals.items():
            if h2 == hn or a2 == an:
                tot_entry = v
                break

        # Weather (outdoor parks only)
        weather = {}
        if not is_indoor and home in STADIUM_COORDS:
            lat, lon = STADIUM_COORDS[home]
            weather  = _get_weather(lat, lon)

        # Wind boost: HR/TB/HRR get a bump at 15+ mph outdoors
        ws = weather.get('wind_speed', 0) or 0
        wind_boost = 1.0
        if not is_indoor:
            if ws >= 20:
                wind_boost = 1.06
            elif ws >= 15:
                wind_boost = 1.03

        base = {
            'park_factors': pf,
            'is_indoor':    is_indoor,
            'total':        tot_entry.get('total'),
            'wind_speed':   weather.get('wind_speed'),
            'wind_dir':     weather.get('wind_dir', ''),
            'temp_f':       weather.get('temp_f'),
            'wind_boost':   wind_boost,
        }
        # Home team plays in their park; away team also plays in that park
        team_context[home] = {**base, 'is_home': True,  'implied': tot_entry.get('home_implied')}
        team_context[away] = {**base, 'is_home': False, 'implied': tot_entry.get('away_implied')}

    print(f"   Player→team map: {len(player_to_team)} players")

    # Persist
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump({'team_context': team_context, 'bat_orders': bat_orders,
                       'player_to_team': player_to_team}, f)
    except Exception:
        pass

    return team_context, bat_orders, player_to_team


def pa_factor(bat_order: int) -> float:
    """Expected PA adjustment vs league average for a given batting slot."""
    if bat_order < 1 or bat_order > 9:
        return 1.0
    return round(_PA_BY_SLOT[bat_order] / _PA_AVERAGE, 3)
