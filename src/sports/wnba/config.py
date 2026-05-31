"""
WNBA Configuration — Stat mappings, model quality tiers, targets.

Usage:
    from src.sports.wnba.config import STAT_MAP, MODEL_QUALITY, ACTIVE_TARGETS
"""

# PrizePicks display name → internal model target code
STAT_MAP = {
    'Points':             'PTS',
    'Rebounds':           'REB',
    'Assists':            'AST',
    '3-PT Made':          'FG3M',
    'Free Throws Made':   'FTM',
    'Steals':             'STL',
    'Turnovers':          'TOV',
    'FG Made':            'FGM',
    'Defensive Rebounds': 'DREB',
    'Offensive Rebounds': 'OREB',
    'Pts+Rebs+Asts':      'PRA',
    'Pts+Rebs':           'PR',
    'Pts+Asts':           'PA',
    'Rebs+Asts':          'RA',
    'Blks+Stls':          'SB',
    'Fantasy Score':      'FPTS',
}

# Reverse: internal code → PP display name
STAT_MAP_REVERSE = {v: k for k, v in STAT_MAP.items()}

# All targets the models will be trained on
ACTIVE_TARGETS = [
    'PTS', 'REB', 'AST',
    'PRA', 'PR', 'PA', 'RA', 'SB',
    'FG3M', 'FTM', 'STL', 'TOV', 'FGM',
    'DREB', 'OREB', 'FPTS',
]

# Model quality tiers  (estimates — update after training with actual DIR%)
MODEL_TIERS = {
    'ELITE': {
        'models':    ['PTS', 'REB', 'AST'],
        'emoji':     '💎 LOCK',
        'threshold': 1.5,
    },
    'STRONG': {
        'models':    ['PRA', 'PR', 'PA', 'RA', 'FG3M', 'FTM', 'FPTS'],
        'emoji':     '🔥 FIRE',
        'threshold': 2.0,
    },
    'DECENT': {
        'models':    ['STL', 'TOV', 'FGM', 'SB'],
        'emoji':     '✅ SOLID',
        'threshold': 2.5,
    },
    'RISKY': {
        'models':    ['DREB', 'OREB'],
        'emoji':     '⚡ RISKY',
        'threshold': 3.5,
    },
}

# Quick lookup: target → {tier, emoji, threshold}
MODEL_QUALITY = {}
for _tier, _data in MODEL_TIERS.items():
    for _m in _data['models']:
        MODEL_QUALITY[_m] = {
            'tier':      _tier,
            'emoji':     _data['emoji'],
            'threshold': _data['threshold'],
        }

# Stats that follow zero-inflated distributions → log-transform at training
LOG_TRANSFORM_TARGETS = {'STL', 'TOV', 'FG3M', 'OREB', 'SB'}

# WNBA seasons to pull (year format, used by nba_api with league_id='10')
SEASONS = ['2020', '2021', '2022', '2023', '2024', '2025']

# PickFinder stat name → internal target (for scanner's PF lookup)
# PF uses the same display names as PP for WNBA
PF_STAT_MAP = STAT_MAP.copy()
