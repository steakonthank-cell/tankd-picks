"""
Tank'd Picks v2 — Park Factors Module
======================================
Park factors quantify how much a ballpark inflates/deflates stats
relative to league average (100 = neutral).

Sources: FanGraphs park factors, updated for 2024-2025 seasons.
These are 3-year rolling averages. Values > 100 = hitter-friendly.

Usage:
    from features.park_factors import get_park_factors, get_park_factor
    
    factors = get_park_factors("COL")  # Coors Field
    hr_factor = get_park_factor("COL", "HR")  # 118 (HR-friendly)
"""

# Park factors: { team_abbr: { factor_type: value } }
# 100 = league average, >100 = inflates stat, <100 = suppresses
# Factors: R (runs), HR, H (hits), 2B (doubles), 3B (triples), 
#          BB (walks), SO (strikeouts), GB (ground balls)
PARK_FACTORS = {
    "AZ":  {"R": 106, "HR": 107, "H": 103, "2B": 104, "3B": 115, "SO": 98, "BB": 101},
    "ATL": {"R": 101, "HR": 104, "H": 100, "2B": 99,  "3B": 95,  "SO": 100, "BB": 99},
    "BAL": {"R": 102, "HR": 108, "H": 100, "2B": 96,  "3B": 90,  "SO": 99, "BB": 100},
    "BOS": {"R": 105, "HR": 99,  "H": 105, "2B": 120, "3B": 80,  "SO": 99, "BB": 100},
    "CHC": {"R": 103, "HR": 107, "H": 101, "2B": 100, "3B": 95,  "SO": 100, "BB": 100},
    "CWS": {"R": 99,  "HR": 103, "H": 98,  "2B": 97,  "3B": 90,  "SO": 101, "BB": 100},
    "CIN": {"R": 107, "HR": 114, "H": 102, "2B": 101, "3B": 95,  "SO": 97, "BB": 99},
    "CLE": {"R": 97,  "HR": 95,  "H": 98,  "2B": 99,  "3B": 100, "SO": 102, "BB": 101},
    "COL": {"R": 115, "HR": 118, "H": 110, "2B": 113, "3B": 130, "SO": 92, "BB": 102},
    "DET": {"R": 96,  "HR": 92,  "H": 98,  "2B": 101, "3B": 100, "SO": 101, "BB": 100},
    "HOU": {"R": 100, "HR": 104, "H": 99,  "2B": 97,  "3B": 90,  "SO": 100, "BB": 99},
    "KC":  {"R": 102, "HR": 98,  "H": 103, "2B": 107, "3B": 110, "SO": 98, "BB": 100},
    "LAA": {"R": 97,  "HR": 96,  "H": 98,  "2B": 99,  "3B": 95,  "SO": 101, "BB": 100},
    "LAD": {"R": 98,  "HR": 97,  "H": 99,  "2B": 101, "3B": 100, "SO": 101, "BB": 100},
    "MIA": {"R": 94,  "HR": 89,  "H": 97,  "2B": 100, "3B": 105, "SO": 103, "BB": 101},
    "MIL": {"R": 100, "HR": 103, "H": 99,  "2B": 98,  "3B": 95,  "SO": 100, "BB": 100},
    "MIN": {"R": 103, "HR": 109, "H": 101, "2B": 99,  "3B": 95,  "SO": 99, "BB": 99},
    "NYM": {"R": 97,  "HR": 94,  "H": 98,  "2B": 100, "3B": 100, "SO": 102, "BB": 101},
    "NYY": {"R": 104, "HR": 112, "H": 100, "2B": 95,  "3B": 85,  "SO": 99, "BB": 100},
    "ATH": {"R": 98,  "HR": 95,  "H": 99,  "2B": 101, "3B": 100, "SO": 101, "BB": 100},
    "PHI": {"R": 103, "HR": 108, "H": 101, "2B": 100, "3B": 95,  "SO": 99, "BB": 99},
    "PIT": {"R": 96,  "HR": 90,  "H": 99,  "2B": 103, "3B": 110, "SO": 102, "BB": 101},
    "SD":  {"R": 95,  "HR": 91,  "H": 97,  "2B": 98,  "3B": 100, "SO": 103, "BB": 101},
    "SF":  {"R": 95,  "HR": 88,  "H": 97,  "2B": 100, "3B": 105, "SO": 102, "BB": 101},
    "SEA": {"R": 95,  "HR": 93,  "H": 97,  "2B": 99,  "3B": 100, "SO": 103, "BB": 101},
    "STL": {"R": 98,  "HR": 96,  "H": 99,  "2B": 101, "3B": 105, "SO": 101, "BB": 100},
    "TB":  {"R": 96,  "HR": 93,  "H": 98,  "2B": 99,  "3B": 95,  "SO": 102, "BB": 101},
    "TEX": {"R": 105, "HR": 108, "H": 102, "2B": 102, "3B": 100, "SO": 98, "BB": 99},
    "TOR": {"R": 101, "HR": 105, "H": 100, "2B": 98,  "3B": 90,  "SO": 100, "BB": 100},
    "WSH": {"R": 100, "HR": 101, "H": 100, "2B": 100, "3B": 100, "SO": 100, "BB": 100},
}

# Map stat types to park factor keys. Includes both the full display labels
# (used by the docstring/self-test examples below) and the short scan codes
# (H, TB, HR, RBI, R, SO, BB, K, OUTS, ER, HRR — what enrich_scan_data()
# actually passes as stat_type at runtime, per the Stat column). Previously
# only full labels were mapped, so short codes fell through to
# get_park_factor()'s stat.upper() fallback, which only happened to match a
# real PARK_FACTORS key for H/SO/R/HR/BB by coincidence and silently
# returned neutral 100 for TB/K/OUTS/ER regardless of the actual park.
STAT_TO_FACTOR = {
    # Full display labels
    "Hits":          "H",
    "HRR":           "HR",
    "Total Bases":   "R",   # Runs as proxy for total bases
    "Runs":          "R",
    "Strikeouts":    "SO",
    "Hitter Ks":     "SO",
    "Pitching Outs": "SO",  # Inverse — high K park = more outs opportunity
    "Doubles":       "2B",
    "Triples":       "3B",
    "Walks":         "BB",
    "RBI":           "R",
    # Short scan codes
    "H":    "H",
    "TB":   "R",    # Runs as proxy for total bases
    "R":    "R",
    "SO":   "SO",   # hitter strikeouts
    "K":    "SO",   # pitcher strikeouts — same park K-suppression/inflation applies to both sides
    "OUTS": "SO",
    "BB":   "BB",
    "ER":   "R",    # Runs as proxy for earned-run environment
}


def get_park_factors(team: str) -> dict:
    """Get all park factors for a team's home park."""
    return PARK_FACTORS.get(str(team).upper() if team is not None and str(team) != "nan" else "", {k: 100 for k in ["R","HR","H","2B","3B","SO","BB"]})


def get_park_factor(team: str, stat: str = "R") -> int:
    """
    Get a specific park factor for a team.
    
    Args:
        team: Team abbreviation (e.g. "COL", "NYY")
        stat: Factor type — "R", "HR", "H", "2B", "3B", "SO", "BB"
              or a prop stat name like "Hits", "HRR", "Strikeouts"
    
    Returns:
        Park factor (100 = neutral, >100 = inflates, <100 = suppresses)
    """
    # Map prop stat names to factor keys
    factor_key = STAT_TO_FACTOR.get(stat, stat.upper())
    factors = get_park_factors(team)
    return factors.get(factor_key, 100)


def park_adjustment(team: str, stat_type: str, projection: float) -> float:
    """
    Adjust an AI projection by park factor.
    
    Example:
        # Player projected for 1.5 hits, playing at Coors
        adjusted = park_adjustment("COL", "Hits", 1.5)  
        # Returns ~1.65 (110% of 1.5)
    """
    factor = get_park_factor(team, stat_type)
    return projection * (factor / 100.0)


def park_edge_modifier(home_team: str, stat_type: str) -> float:
    """
    Returns a multiplier for the edge score based on park factors.
    
    Extreme parks (Coors, Fenway, GABP) should boost/suppress
    edge confidence. Returns a value 0.85 - 1.15 to scale the edge.
    """
    factor = get_park_factor(home_team, stat_type)
    # Normalize: 100 -> 1.0, 115 -> 1.10, 85 -> 0.90
    # Dampened to avoid overcorrection
    return 1.0 + (factor - 100) / 150.0


if __name__ == "__main__":
    # Quick test
    print("=== Park Factor Examples ===")
    print(f"Coors (COL) HR factor:  {get_park_factor('COL', 'HR')}  (hitter paradise)")
    print(f"Oracle (SF) HR factor:  {get_park_factor('SF', 'HR')}   (pitcher park)")
    print(f"Fenway (BOS) 2B factor: {get_park_factor('BOS', '2B')}  (Green Monster)")
    print(f"Yankee (NYY) HR factor: {get_park_factor('NYY', 'HR')}  (short porch)")
    print()
    print("=== Projection Adjustments ===")
    print(f"1.5 hits proj at Coors:  {park_adjustment('COL', 'Hits', 1.5):.2f}")
    print(f"1.5 hits proj at Oracle: {park_adjustment('SF', 'Hits', 1.5):.2f}")
    print(f"7.0 K proj at Tropicana: {park_adjustment('TB', 'Strikeouts', 7.0):.2f}")
    print(f"7.0 K proj at Coors:     {park_adjustment('COL', 'Strikeouts', 7.0):.2f}")
