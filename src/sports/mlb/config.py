"""
MLB Configuration Constants
"""

import os
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv('ODDS_API_KEY')

SPORT_MAP   = {'MLB': 'baseball_mlb'}
REGIONS     = 'us'
ODDS_FORMAT = 'american'

# PrizePicks display name → internal stat code
STAT_MAP = {
    'Hits':                'H',
    'Total Bases':         'TB',
    'Home Runs':           'HR',
    'RBIs':                'RBI',
    'Runs Scored':         'R',
    'Hitter Strikeouts':   'SO',
    'Walks':               'BB',
    'Stolen Bases':        'SB',
    'Pitcher Strikeouts':  'K',
    'Pitching Outs':       'OUTS',
    'Earned Runs Allowed': 'ER',
    'Hits Allowed':        'HA',
    'Walks Allowed':       'BBA',
}

STAT_MAP_REVERSE = {v: k for k, v in STAT_MAP.items()}

BATTER_TARGETS  = ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB', 'HRR']
PITCHER_TARGETS = ['K', 'ER', 'OUTS']
ACTIVE_TARGETS  = BATTER_TARGETS + PITCHER_TARGETS

# Combo stats — predicted by summing component model projections
COMBO_STATS = {
    'HRR': ['H', 'R', 'RBI'],   # Hits + Runs + RBIs
}

PITCHER_STATS = {'K', 'ER', 'OUTS', 'HA', 'BBA'}

MODEL_TIERS = {
    'ELITE': {
        'models':         ['H', 'TB', 'K'],
        'accuracy_range': '~58-62%',
        'edge_threshold': 15.0,
        'description':    '⭐ Core plays — highest model confidence',
        'emoji':          '⭐',
    },
    'STRONG': {
        'models':         ['RBI', 'R', 'OUTS'],
        'accuracy_range': '~55-58%',
        'edge_threshold': 20.0,
        'description':    '✔ Strong plays — good confidence',
        'emoji':          '✔',
    },
    'DECENT': {
        'models':         ['ER', 'HR', 'HRR'],
        'accuracy_range': '~53-55%',
        'edge_threshold': 25.0,
        'description':    '~ Decent plays — use with care',
        'emoji':          '~',
    },
    'RISKY': {
        'models':         ['SO', 'BB'],
        'accuracy_range': '~51-53%',
        'edge_threshold': 30.0,
        'description':    '⚠️ High edge only',
        'emoji':          '⚠️',
    },
}

MODEL_QUALITY = {}
for _tier, _data in MODEL_TIERS.items():
    for _model in _data['models']:
        MODEL_QUALITY[_model] = {
            'tier':      _tier,
            'threshold': _data['edge_threshold'],
            'emoji':     _data['emoji'],
        }

SCANNING_MODE = 'ALL'

SCANNING_MODES = {
    'ELITE_ONLY': MODEL_TIERS['ELITE']['models'],
    'SAFE':       MODEL_TIERS['ELITE']['models'] + MODEL_TIERS['STRONG']['models'],
    'BALANCED':   MODEL_TIERS['ELITE']['models'] + MODEL_TIERS['STRONG']['models'] + MODEL_TIERS['DECENT']['models'],
    'AGGRESSIVE': MODEL_TIERS['ELITE']['models'] + MODEL_TIERS['STRONG']['models'] + MODEL_TIERS['DECENT']['models'] + MODEL_TIERS['RISKY']['models'],
    'ALL':        ACTIVE_TARGETS,
}

mode_descriptions = {
    'ELITE_ONLY': "⭐ ELITE — Hits, TB, K (pitcher)",
    'SAFE':       "✔ SAFE — 6 high-confidence stats",
    'BALANCED':   "📊 BALANCED — 8 stats",
    'AGGRESSIVE': "⚡ AGGRESSIVE — all 10 stats",
    'ALL':        "🎲 ALL — every stat",
}

def print_mode_info():
    desc = mode_descriptions.get(SCANNING_MODE, 'UNKNOWN')
    print(f"⚙️  MLB: {desc}")
    print(f"   Scanning: {', '.join(SCANNING_MODES.get(SCANNING_MODE, ACTIVE_TARGETS))}")
