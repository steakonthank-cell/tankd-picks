"""
MLB Name and Stat Mappings
"""

import unicodedata
import re


def normalize_name(name):
    if not name:
        return ""
    n = unicodedata.normalize('NFD', str(name))
    n = ''.join(c for c in n if unicodedata.category(c) != 'Mn')
    n = re.sub(r"[^a-zA-Z\s\.]", '', n)
    return ' '.join(n.lower().split())


# PrizePicks stat label → internal stat code
STAT_MAPPING = {
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
    # Alternate labels PrizePicks might use
    'Strikeouts':          'K',
    'Earned Runs':         'ER',
    'Outs Recorded':       'OUTS',
    'Runs':                'R',
    # Combo stats — predicted by summing individual model projections
    'Hits+Runs+RBIs':    'HRR',   # = H_proj + R_proj + RBI_proj
}

# Stats that belong to pitchers
PITCHER_STATS = {'K', 'ER', 'OUTS', 'HA', 'BBA'}
BATTER_STATS  = {'H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB', 'SB'}

# Volatility weights for combined scoring (more volatile = lower weight)
VOLATILITY_MAP = {
    'H':    1.00,
    'TB':   1.00,
    'K':    1.00,
    'RBI':  0.90,
    'R':    0.85,
    'OUTS': 0.85,
    'ER':   0.75,
    'HR':   0.65,
    'SO':   0.60,
    'BB':   0.55,
}
