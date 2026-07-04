"""
Canonical constants and helpers for the MLB pipeline.

This module is the SINGLE SOURCE OF TRUTH for:
  - rolling-stat lists and windows (batter + pitcher)
  - the derived feature lists (BATTER_FEATURES / PITCHER_FEATURES)
  - the name normalizer used for all cross-source joins

Everything that builds features (features.py), trains models (train.py),
scans (scanner.py), or joins external data (mlb_splits.py) imports from here
so the definitions can never drift out of sync again.
"""
import re
import unicodedata


# ── Name normalization ──────────────────────────────────────────────────────
def normalize_name(name):
    """Canonical name key for ALL cross-source joins.

    NFD -> strip accents -> keep only [a-zA-Z space .] -> lower -> collapse ws.
    Strips hyphens/apostrophes/digits so e.g. 'Kai-Wei Teng' and "O'Hearn"
    key identically on both the build side and the lookup side.
    """
    if not name:
        return ""
    n = unicodedata.normalize('NFD', str(name))
    n = ''.join(c for c in n if unicodedata.category(c) != 'Mn')
    n = re.sub(r"[^a-zA-Z\s\.]", '', n)
    return ' '.join(n.lower().split())


# ── Rolling-stat feature sets ────────────────────────────────────────────────
BATTER_ROLL_STATS  = ['H', 'TB', 'HR', 'RBI', 'R', 'SO', 'BB', 'AB', 'SB']
PITCHER_ROLL_STATS = ['K', 'ER', 'OUTS', 'HA', 'BBA', 'HR_A', 'pitches', 'batters_faced']

BATTER_WINDOWS  = [5, 10, 20]
PITCHER_WINDOWS = [3, 5, 10]


def _build_feature_list(roll_stats, windows, extra=None):
    feats = []
    for stat in roll_stats:
        for w in windows:
            feats.append(f'{stat}_L{w}')
        feats.append(f'{stat}_season_avg')
    feats.append('is_home')
    if extra:
        feats.extend(extra)
    return feats


BATTER_FEATURES  = _build_feature_list(
    BATTER_ROLL_STATS, BATTER_WINDOWS,
    ['games_played']
)
PITCHER_FEATURES = _build_feature_list(
    PITCHER_ROLL_STATS, PITCHER_WINDOWS,
    ['is_starter', 'apps_season']
)
