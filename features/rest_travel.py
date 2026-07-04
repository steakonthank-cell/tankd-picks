"""
Tank'd Picks v2 — Rest & Travel Module
=======================================
Calculates fatigue signals from schedule context:
- Days since last game
- Travel distance between cities
- Timezone shifts
- Day game after night game
- Series game number (game 1 vs game 3-4)

Usage:
    from features.rest_travel import get_fatigue_score, get_travel_distance
    
    fatigue = get_fatigue_score(
        team="NYY",
        prev_city="SEA",      # Where they played last
        current_city="NYY",   # Where they play today
        days_rest=0,          # 0 = back-to-back
        is_day_after_night=True,
        series_game=1         # First game of new series
    )
"""

import math

# ─── Stadium coordinates (lat, lon) for travel distance ───
STADIUM_COORDS = {
    "AZ":  (33.4453, -112.0667),  # Chase Field, Phoenix
    "ATL": (33.7350, -84.3900),   # Truist Park, Atlanta
    "BAL": (39.2839, -76.6217),   # Camden Yards, Baltimore
    "BOS": (42.3467, -71.0972),   # Fenway Park, Boston
    "CHC": (41.9484, -87.6553),   # Wrigley Field, Chicago
    "CWS": (41.8299, -87.6338),   # Guaranteed Rate, Chicago
    "CIN": (39.0974, -84.5082),   # GABP, Cincinnati
    "CLE": (41.4962, -81.6852),   # Progressive Field, Cleveland
    "COL": (39.7561, -104.9942),  # Coors Field, Denver
    "DET": (42.3390, -83.0485),   # Comerica Park, Detroit
    "HOU": (29.7572, -95.3555),   # Minute Maid, Houston
    "KC":  (39.0517, -94.4803),   # Kauffman Stadium, KC
    "LAA": (33.8003, -117.8827),  # Angel Stadium, Anaheim
    "LAD": (34.0739, -118.2400),  # Dodger Stadium, LA
    "MIA": (25.7781, -80.2196),   # loanDepot park, Miami
    "MIL": (43.0280, -87.9712),   # American Family Field, Milwaukee
    "MIN": (44.9817, -93.2783),   # Target Field, Minneapolis
    "NYM": (40.7571, -73.8458),   # Citi Field, Queens
    "NYY": (40.8296, -73.9262),   # Yankee Stadium, Bronx
    "ATH": (37.7516, -122.2005),  # Coliseum, Oakland (Sacramento 2025+)
    "PHI": (39.9061, -75.1665),   # Citizens Bank Park, Philly
    "PIT": (40.4469, -80.0058),   # PNC Park, Pittsburgh
    "SD":  (32.7076, -117.1570),  # Petco Park, San Diego
    "SF":  (37.7786, -122.3893),  # Oracle Park, San Francisco
    "SEA": (47.5914, -122.3325),  # T-Mobile Park, Seattle
    "STL": (38.6226, -90.1928),   # Busch Stadium, St. Louis
    "TB":  (27.7682, -82.6534),   # Tropicana Field, St. Pete
    "TEX": (32.7512, -97.0832),   # Globe Life Field, Arlington
    "TOR": (43.6414, -79.3894),   # Rogers Centre, Toronto
    "WSH": (38.8730, -77.0074),   # Nationals Park, DC
}

# Timezone offsets (ET-relative) for timezone shift calc
TEAM_TIMEZONE = {
    "AZ": -2, "ATL": 0, "BAL": 0, "BOS": 0, "CHC": -1, "CWS": -1,
    "CIN": 0, "CLE": 0, "COL": -2, "DET": 0, "HOU": -1, "KC": -1,
    "LAA": -3, "LAD": -3, "MIA": 0, "MIL": -1, "MIN": -1,
    "NYM": 0, "NYY": 0, "ATH": -3, "PHI": 0, "PIT": 0,
    "SD": -3, "SF": -3, "SEA": -3, "STL": -1, "TB": 0,
    "TEX": -1, "TOR": 0, "WSH": 0,
}


def haversine_miles(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in miles."""
    R = 3959  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def get_travel_distance(from_team: str, to_team: str) -> float:
    """
    Get travel distance in miles between two team cities.
    
    Returns 0 if same city (e.g. NYM -> NYY, CHC -> CWS, LAA -> LAD).
    """
    from_team = from_team.upper()
    to_team = to_team.upper()
    
    if from_team == to_team:
        return 0.0
    
    # Same-city teams
    same_city = [
        {"NYM", "NYY"}, {"CHC", "CWS"}, {"LAA", "LAD"},
        {"SF", "ATH"}, {"BAL", "WSH"},
    ]
    for pair in same_city:
        if {from_team, to_team} == pair:
            return 15.0  # Nominal same-city distance
    
    c1 = STADIUM_COORDS.get(from_team)
    c2 = STADIUM_COORDS.get(to_team)
    if not c1 or not c2:
        return 0.0
    
    return haversine_miles(c1[0], c1[1], c2[0], c2[1])


def get_timezone_shift(from_team: str, to_team: str) -> int:
    """Get timezone shift in hours (absolute value)."""
    tz1 = TEAM_TIMEZONE.get(from_team.upper(), 0)
    tz2 = TEAM_TIMEZONE.get(to_team.upper(), 0)
    return abs(tz2 - tz1)


def get_fatigue_score(
    team: str,
    prev_city: str = None,
    current_city: str = None,
    days_rest: int = 1,
    is_day_after_night: bool = False,
    series_game: int = 1,
) -> dict:
    """
    Calculate a composite fatigue profile for a team/player.
    
    Returns dict with:
        - fatigue_score: 0-100 (0 = fully rested, 100 = max fatigue)
        - travel_miles: distance traveled
        - tz_shift: timezone hours shifted
        - flags: list of fatigue flags
        - adjustment: multiplier for edge score (0.85 - 1.05)
    """
    score = 0.0
    flags = []
    
    travel_miles = 0
    tz_shift = 0
    
    # Travel component
    if prev_city and current_city:
        travel_miles = get_travel_distance(prev_city, current_city)
        tz_shift = get_timezone_shift(prev_city, current_city)
        
        if travel_miles > 2000:
            score += 25
            flags.append("LONG_TRAVEL")
        elif travel_miles > 1000:
            score += 15
            flags.append("MED_TRAVEL")
        elif travel_miles > 500:
            score += 8
        
        if tz_shift >= 3:
            score += 20
            flags.append("COAST_TO_COAST")
        elif tz_shift >= 2:
            score += 10
            flags.append("TZ_SHIFT")
    
    # Rest days
    if days_rest == 0:
        score += 15
        flags.append("BACK_TO_BACK")
    elif days_rest >= 2:
        score -= 10  # Well rested bonus
        flags.append("RESTED")
    
    # Day game after night game
    if is_day_after_night:
        score += 20
        flags.append("DAY_AFTER_NIGHT")
    
    # Series fatigue (game 3-4 of a series, especially after travel)
    if series_game >= 4:
        score += 5
    
    # Clamp
    score = max(0, min(100, score))
    
    # Convert to edge adjustment multiplier
    # 0 fatigue -> 1.05 (slight boost for rested)
    # 50 fatigue -> 1.00 (neutral)  
    # 100 fatigue -> 0.85 (significant penalty)
    adjustment = 1.05 - (score / 100.0) * 0.20
    
    return {
        "fatigue_score": round(score),
        "travel_miles": round(travel_miles),
        "tz_shift": tz_shift,
        "flags": flags,
        "adjustment": round(adjustment, 3),
    }


def get_schedule_context(team: str, schedule: list) -> dict:
    """
    Given a team's recent schedule, compute fatigue context.
    
    Args:
        team: Team abbreviation
        schedule: List of recent games, each a dict with:
            - date: str (YYYY-MM-DD)
            - opponent: str (team abbr)
            - home: bool
            - start_time: str (HH:MM, 24hr)
    
    Returns:
        Fatigue context dict for the next game
    """
    if not schedule or len(schedule) < 2:
        return get_fatigue_score(team)
    
    last_game = schedule[-1]
    prev_game = schedule[-2] if len(schedule) >= 2 else None
    
    # Determine cities
    current_city = team if last_game.get("home") else last_game.get("opponent", team)
    prev_city = team if prev_game and prev_game.get("home") else (prev_game.get("opponent", team) if prev_game else team)
    
    # Day after night detection
    is_day_after_night = False
    if prev_game and last_game:
        prev_time = prev_game.get("start_time", "19:00")
        curr_time = last_game.get("start_time", "19:00")
        prev_hour = int(prev_time.split(":")[0])
        curr_hour = int(curr_time.split(":")[0])
        if prev_hour >= 18 and curr_hour < 16:
            is_day_after_night = True
    
    # Days rest (simplified — in production use actual dates)
    days_rest = 1  # Default to back-to-back during regular season
    
    return get_fatigue_score(
        team=team,
        prev_city=prev_city,
        current_city=current_city,
        days_rest=days_rest,
        is_day_after_night=is_day_after_night,
    )


if __name__ == "__main__":
    print("=== Travel Distance Examples ===")
    print(f"SEA -> NYY: {get_travel_distance('SEA', 'NYY'):.0f} miles")
    print(f"NYM -> NYY: {get_travel_distance('NYM', 'NYY'):.0f} miles (same city)")
    print(f"BOS -> BAL: {get_travel_distance('BOS', 'BAL'):.0f} miles")
    print(f"LAD -> MIA: {get_travel_distance('LAD', 'MIA'):.0f} miles")
    print()
    
    print("=== Fatigue Score Examples ===")
    
    # Team flying coast-to-coast, day game after night game
    result = get_fatigue_score("NYY", prev_city="SEA", current_city="NYY",
                               days_rest=0, is_day_after_night=True)
    print(f"NYY (flew from SEA, day after night): {result}")
    
    # Well-rested team at home
    result = get_fatigue_score("LAD", prev_city="LAD", current_city="LAD",
                               days_rest=2, is_day_after_night=False)
    print(f"LAD (2 days rest, home): {result}")
    
    # Normal back-to-back, short travel
    result = get_fatigue_score("PHI", prev_city="NYM", current_city="PHI",
                               days_rest=0, is_day_after_night=False)
    print(f"PHI (from NYM, b2b): {result}")
