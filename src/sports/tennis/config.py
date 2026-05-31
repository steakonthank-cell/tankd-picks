"""
Tennis Configuration Constants

All tennis-specific settings: stat name mappings, model quality tiers,
scanning modes, and PrizePicks market names.

Model accuracy last updated: 2026-02-18
    total_games:    81.2% DIR | MAE 3.163 | R² 0.642
    total_sets:     81.2% DIR | MAE 0.319 | R² 0.639
    games_won:      78.8% DIR | MAE 2.183 | R² 0.603
    aces:           78.0% DIR | MAE 2.302 | R² 0.527
    bp_won:         76.2% DIR | MAE 1.208 | R² 0.440
    total_tiebreaks:69.4% DIR | MAE 0.408 | R² 0.226
    double_faults:  69.2% DIR | MAE 1.732 | R² 0.279

Usage:
    from src.sports.tennis.config import STAT_MAP, MODEL_QUALITY, ACTIVE_TARGETS
"""

import os
from dotenv import load_dotenv

load_dotenv()



# PrizePicks stat name → internal target (for analyzer compatibility)
PP_NORMALIZATION_MAP = {
    'Total Games':       'total_games',
    'Total Games Won':   'games_won',
    'Total Sets':        'total_sets',
    'Aces':              'aces',
    'Break Points Won':  'bp_won',
    'Total Tie Breaks':  'total_tiebreaks',
    'Double Faults':     'double_faults',
}

# 1. PrizePicks display name -> internal column name
STAT_MAP = {
    'Total Games':       'total_games',
    'Total Games Won':   'games_won',
    'Total Sets':        'total_sets',
    'Aces':              'aces',
    'Fantasy Score':     'fantasy_score',    # deferred — formula not confirmed
    'Break Points Won':  'bp_won',
    'Total Tie Breaks':  'total_tiebreaks',
    'Double Faults':     'double_faults',
}

# 2. Reverse map: internal column -> PrizePicks display name
STAT_MAP_REVERSE = {v: k for k, v in STAT_MAP.items()}

# 3. Active targets (Fantasy Score excluded until formula confirmed)
ACTIVE_TARGETS = [
    'total_games',
    'games_won',
    'total_sets',
    'aces',
    'bp_won',
    'total_tiebreaks',
    'double_faults',
]

# 4. Model Quality Tiers  (based on actual directional accuracy from training)
MODEL_TIERS = {
    'ELITE': {
        'models':         ['total_games', 'total_sets'],
        'accuracy_range': '81%',
        'edge_threshold': 1.5,
        'description':    '💎 LOCK — highest confidence',
        'emoji':          '💎 LOCK',
    },
    'STRONG': {
        'models':         ['games_won', 'aces'],
        'accuracy_range': '78-79%',
        'edge_threshold': 2.0,
        'description':    '🔥 FIRE — strong model edge',
        'emoji':          '🔥 FIRE',
    },
    'DECENT': {
        'models':         ['bp_won'],
        'accuracy_range': '76%',
        'edge_threshold': 2.5,
        'description':    '✅ SOLID — good play at right edge',
        'emoji':          '✅ SOLID',
    },
    'RISKY': {
        'models':         ['total_tiebreaks', 'double_faults'],
        'accuracy_range': '69%',
        'edge_threshold': 3.5,
        'description':    '⚡ RISKY — needs big edge to be +EV',
        'emoji':          '⚡ RISKY',
    },
}

# Quick lookup: target -> tier info
MODEL_QUALITY = {}
for tier, data in MODEL_TIERS.items():
    for model in data['models']:
        MODEL_QUALITY[model] = {
            'tier':      tier,
            'threshold': data['edge_threshold'],
            'emoji':     data['emoji'],
        }

# 5. Scanning mode
# Controls which tiers are included in a scan.
# Options: 'ELITE_ONLY', 'SAFE', 'BALANCED', 'AGGRESSIVE', 'ALL'
SCANNING_MODE = 'ALL'

SCANNING_MODES = {
    'ELITE_ONLY': MODEL_TIERS['ELITE']['models'],
    'SAFE':       MODEL_TIERS['ELITE']['models'] + MODEL_TIERS['STRONG']['models'],
    'BALANCED':   MODEL_TIERS['ELITE']['models'] + MODEL_TIERS['STRONG']['models'] + MODEL_TIERS['DECENT']['models'],
    'AGGRESSIVE': MODEL_TIERS['ELITE']['models'] + MODEL_TIERS['STRONG']['models'] + MODEL_TIERS['DECENT']['models'] + MODEL_TIERS['RISKY']['models'],
    'ALL':        ACTIVE_TARGETS,
}

mode_descriptions = {
    'ELITE_ONLY': "⭐ ELITE ONLY — 2 models (81%+)",
    'SAFE':       "✔ SAFE — 4 models (78%+)",
    'BALANCED':   "📊 BALANCED — 5 models (76%+)",
    'AGGRESSIVE': "⚡ AGGRESSIVE — 7 models (69%+)",
    'ALL':        "🎲 ALL MODELS — 7 models",
}

# print(f"⚙️  Tennis: {mode_descriptions.get(SCANNING_MODE, 'UNKNOWN MODE')}")

# 6. Surface labels (for display)
SURFACE_DISPLAY = {
    'Hard':   '🔵 Hard',
    'Clay':   '🟤 Clay',
    'Grass':  '🟢 Grass',
    'Carpet': '⬜ Carpet',
}

# 7. Volatility weights for combined scoring
VOLATILITY_MAP = {
    'total_games':     1.0,
    'games_won':       1.0,
    'total_sets':      0.95,
    'aces':            0.85,
    'bp_won':          0.80,
    'total_tiebreaks': 0.60,
    'double_faults':   0.55,
}