"""
MLB Bullpen Signals
====================
Team-level bullpen quality/workload derived from the existing pitching-log
data (data/mlb/raw/pitching_logs.csv), which already tags each appearance as
starter or relief via the is_starter flag pulled from the MLB Stats API
(src/sports/mlb/builder.py). No new data source required.

Both functions are leakage-safe: they only look at rows strictly before
`as_of`, and return None when there isn't enough data in the window so
callers can fall back to a league-average value instead of a misleading 0.
"""

import pandas as pd


def _relief_window(team_id, as_of, logs, window_days):
    as_of = pd.Timestamp(as_of)
    cutoff = as_of - pd.Timedelta(days=window_days)
    return logs[
        (logs['team_id'] == team_id) &
        (logs['is_starter'] == 0) &
        (logs['date'] >= cutoff) &
        (logs['date'] < as_of)
    ]


def team_bullpen_era(team_id, as_of, logs, window_days=21):
    """Relief-only ERA for a team over the trailing window, as of a date.

    ERA = earned runs * 27 / outs (equivalent to ER / (outs/3) * 9).
    Returns None if the team has no relief innings in the window.
    """
    g = _relief_window(team_id, as_of, logs, window_days)
    outs = g['OUTS'].sum()
    if outs == 0:
        return None
    return round(g['ER'].sum() * 27 / outs, 2)


def team_bullpen_workload(team_id, as_of, logs, window_days=3):
    """Relief innings pitched for a team over the trailing window — a
    fatigue/rest proxy (heavier recent usage == more tired bullpen).

    Returns None if the team has no relief appearances in the window
    (distinct from 0.0, which would mean "confirmed idle bullpen").
    """
    g = _relief_window(team_id, as_of, logs, window_days)
    if len(g) == 0:
        return None
    return round(g['OUTS'].sum() / 3.0, 2)


def league_avg_bullpen_era(as_of, logs, window_days=21):
    """League-wide relief ERA over the trailing window — fallback value
    for teams with no relief data of their own in that window."""
    as_of = pd.Timestamp(as_of)
    cutoff = as_of - pd.Timedelta(days=window_days)
    g = logs[
        (logs['is_starter'] == 0) &
        (logs['date'] >= cutoff) &
        (logs['date'] < as_of)
    ]
    outs = g['OUTS'].sum()
    if outs == 0:
        return 4.30  # rough modern-era MLB bullpen ERA as a last-resort default
    return round(g['ER'].sum() * 27 / outs, 2)


def league_avg_bullpen_workload(as_of, logs, window_days=3):
    """Average per-team relief innings over the trailing window — used to
    normalize team_bullpen_workload() into a relative (fresh/tired) signal."""
    as_of = pd.Timestamp(as_of)
    cutoff = as_of - pd.Timedelta(days=window_days)
    g = logs[
        (logs['is_starter'] == 0) &
        (logs['date'] >= cutoff) &
        (logs['date'] < as_of)
    ]
    if len(g) == 0:
        return 3.0  # rough default: ~3 relief IP per team per 3 days
    per_team = g.groupby('team_id')['OUTS'].sum() / 3.0
    return round(per_team.mean(), 2) if len(per_team) else 3.0
