"""
MLB Historical Data Collection

Downloads batter and pitcher game logs from the MLB Stats API (free, no key).
Fetches game-by-game stats for all active players across multiple seasons.

Data Source:
    statsapi.mlb.com/api/v1  (official MLB Stats API, no auth required)

Output Files:
    data/mlb/raw/batting_logs.csv   - batter game-by-game stats
    data/mlb/raw/pitching_logs.csv  - pitcher game-by-game stats

Checkpointing:
    Each fetch function saves its progress every CHECKPOINT_EVERY
    player-seasons to a hidden .{name}.checkpoint.csv (accumulated rows so
    far) and .{name}.done.json (which player_id:season pairs are already
    fetched) next to the real output file. If the process is killed or
    crashes partway through, re-running the same function resumes from the
    checkpoint instead of re-fetching everything from scratch and instead
    of losing all progress made since the last full run (this used to be
    all-or-nothing: a kill after 45 minutes of real API calls discarded
    every response, since the final df.to_csv() only ran once at the very
    end). Checkpoint files are deleted once the real output file is
    written successfully. Only CONFIRMED player-seasons (see below) are
    marked done, so a resumed run retries anything that failed rather than
    treating it as finished.

Failure vs. confirmed-zero (2026-07-28 incident):
    statSplits and gameLog both went through a sustained MLB-side
    degradation starting ~2026-07-04 -- under production request pacing,
    ~95% of gameLog calls 406 (confirmed by direct measurement, not
    inference). The original _get()/get_game_logs() collapsed "API call
    failed after retries" and "confirmed 0 games this season" into the same
    `[]`/None return, so a failed call silently looked identical to a
    player who genuinely didn't play -- and since fetch_*_logs() did a full
    overwrite every run, one bad night (or, as it turned out, every night
    for three weeks) permanently erased that player-season's history from
    the processed training CSVs, even though nothing about the player
    actually changed. pitcher_training.csv/batter_training.csv collapsed
    from 619/523 unique players to 183/246 as a result.

    Fixed by: (1) get_game_logs() now returns the FAILED sentinel (distinct
    from [] / real empty-list) when the call never got a real answer, matching
    the None-vs-{} contract src/core/odds_providers/mlb_splits.py already
    uses for exactly this reason; (2) fetch_batting_logs/fetch_pitching_logs
    only mark a player-season "confirmed" (done, and eligible to overwrite
    existing rows) when it got a real answer -- FAILED player-seasons keep
    whatever was already on file instead of being zeroed out; (3) the final
    write merges onto the existing CSV by (player_id, season) instead of
    replacing it outright, so a degraded run can only add data, never erase
    it silently.

Incremental fetch (added 2026-08-02):
    Every fetch_*_logs() call used to re-pull all of SEASONS (2022-2026, 5
    seasons) for every player, every night -- 6,590 API calls regardless of
    what had actually changed since yesterday. That was the real driver of
    the 8-24h nightly runtime, not just the degraded-endpoint backoff cost:
    closed seasons (everything before SEASONS[-1]) never change once the
    season ends, so re-fetching them nightly for a player already on file
    was pure waste. fetch_batting_logs()/fetch_pitching_logs() now default
    to incremental=True: for any player with existing rows in a closed
    season (see _closed_season_keys), only the current season is re-fetched;
    a player with no history at all (a call-up) still gets a full 5-season
    backfill, same as before. Steady-state call volume drops from ~6,590 to
    roughly ~1,330 (current season only) plus backfill for new players.

    Rare retroactive corrections to closed-season data (a postponed game
    reclassified, an official scorer correction) won't be caught by the
    incremental path. Call with incremental=False (or `--full` from the
    CLI) for a full re-pull -- intended to run as a separate, infrequent
    (monthly) cron entry, not nightly.

Usage:
    $ python3 -m src.sports.mlb.builder            # incremental (default)
    $ python3 -m src.sports.mlb.builder --full      # full re-pull, all seasons

Performance:
    Incremental, healthy endpoint: low single-digit minutes (~1,330 calls).
    Incremental, degraded endpoint: worst case well under an hour with the
    current _get() backoff (see its docstring for why long backoff was
    removed). Full re-pull (--full or incremental=False): back to the old
    ~10-15 minute healthy-case / many-hours degraded-case profile, since
    it's making the full 6,590-call sweep again -- expected for the monthly
    reconciliation pass, not a regression.
    Checkpointing means a second run after a kill only has to redo whatever
    wasn't marked done yet, not everything. During a sustained degradation
    most player-seasons will fail no matter how long this runs -- that's
    expected and handled by the merge logic, not a sign to retry harder.
"""

import requests
import pandas as pd
import json
import time
import os
from datetime import datetime

BASE_URL = "https://statsapi.mlb.com/api/v1"
SEASONS  = [2022, 2023, 2024, 2025, 2026]
CHECKPOINT_EVERY = 50  # player-season units between checkpoint saves

# Alert threshold for this run's gameLog failure rate. The 2026-07-28
# incident's fix (merge-not-overwrite) stops a degraded endpoint from
# erasing data, but a run can still fail the large majority of its calls
# and go nearly empty for the newest day's games without tripping the
# separate row/player-count sanity floor in refresh_training_data.py
# (that floor only fires on a >50% *aggregate* drop, which a mostly-stale
# merge won't produce). 30% is well above single-player-hiccup noise but
# catches the kind of endpoint-wide degradation seen on 2026-08-03 (97%
# pitcher failure rate) long before it silently erodes coverage.
FAILURE_ALERT_THRESHOLD = 0.30

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_DIR      = os.path.join(BASE_DIR, 'data', 'mlb', 'raw')
BATTING_FILE  = os.path.join(RAW_DIR, 'batting_logs.csv')
PITCHING_FILE = os.path.join(RAW_DIR, 'pitching_logs.csv')

# Sentinel distinguishing "API call never got a real answer" from a genuine
# empty result. Never treat FAILED as "confirmed 0" -- see module docstring.
FAILED = object()


def _alert_discord(message):
    """Same webhook/format as refresh_training_data.py's alert -- kept as a
    local copy rather than a cross-import since that script imports *from*
    this module, not the other way around."""
    webhook = os.getenv("MLB_PITCHER_WEBHOOK")
    if not webhook:
        print("   (MLB_PITCHER_WEBHOOK not set in .env -- skipping Discord alert)", flush=True)
        return
    try:
        requests.post(webhook, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"   (Discord alert failed to send: {e})", flush=True)


def _check_failure_rate(label, failed_count, total):
    if not total:
        return
    rate = failed_count / total
    if rate > FAILURE_ALERT_THRESHOLD:
        print(f"   🚨 {label} gameLog failure rate {rate:.0%} ({failed_count}/{total}) "
              f"exceeds the {FAILURE_ALERT_THRESHOLD:.0%} alert threshold this run.", flush=True)
        _alert_discord(
            f"🚨 MLB {label} gameLog fetch: {failed_count}/{total} ({rate:.0%}) failed this run "
            f"— endpoint looks degraded. Existing data is preserved (not erased), but the newest "
            f"day's coverage for most players may be thin/stale until this clears."
        )


def _get(url, params=None, retries=2):
    """Returns parsed JSON on 200, None on a confirmed 404 (real 'not
    found', safe to treat as no data), or FAILED if every attempt failed
    without a definitive answer (network error, timeout, or any other
    non-200/404 status like the 406s seen during the statSplits/gameLog
    degradation) -- callers must NOT treat FAILED as "no data".

    retries/backoff fixed 2026-08-02: was 4 attempts with backoff up to
    2/4/8s (~14.6s total per failed call) on the assumption that a failing
    call needed time to recover. Directly tested that assumption against
    both this endpoint and statSplits: retrying the same failing resource
    after a 0.1-2s pause recovered 0/38 and 0/6 sampled cases respectively
    -- the failures seen during the 2026-08 degradation are stable
    per-(player,season) outcomes, not transient blips that clear on a
    short wait. Backoff that long was pure cost with no recovery benefit
    and was the dominant driver of the 8-24h nightly runtimes (6,590 calls
    x ~66% failure x ~14.6s backoff ~= the observed 17.7h). Cut to 2 total
    attempts, 0.5s apart -- enough to catch a genuine one-off network
    hiccup without paying exponential backoff for calls that were never
    going to succeed on retry."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(0.5)
    return FAILED


def get_active_players(season):
    data = _get(f"{BASE_URL}/sports/1/players", {'season': season})
    if data is FAILED or not data:
        return []
    return data.get('people', [])


def probe_gamelog_health(player_id, season, group):
    """One gameLog call with the full retry budget, run before the main
    fetch loop purely for visibility -- so a degraded endpoint is reported
    up front in the log instead of only being inferable later from a
    smaller-than-expected player count."""
    result = get_game_logs(player_id, season, group)
    healthy = result is not FAILED
    if not healthy:
        print(f"   ⚠️  Probe failed (player {player_id}, {group}, {season}) -- "
              f"gameLog endpoint looks degraded right now. Proceeding anyway; "
              f"expect a reduced success rate this run. Failed player-seasons "
              f"will keep their existing data (not zeroed) and can be picked "
              f"up by a later run.", flush=True)
    return healthy


def get_game_logs(player_id, season, group):
    """Returns a list of game splits (possibly empty -- a real, confirmed
    result), or FAILED if the call never got a definitive answer. Callers
    must check `is FAILED` before treating an empty result as "0 games"."""
    data = _get(f"{BASE_URL}/people/{player_id}/stats", {
        'stats':    'gameLog',
        'group':    group,
        'season':   season,
        'gameType': 'R',
    })
    if data is FAILED:
        return FAILED
    if not data:
        return []
    stats = data.get('stats', [])
    if not stats:
        return []
    return stats[0].get('splits', [])


def _ip_to_outs(ip_str):
    try:
        parts = str(ip_str).split('.')
        whole = int(parts[0])
        frac  = int(parts[1]) if len(parts) > 1 else 0
        return whole * 3 + frac
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Checkpointing — shared by fetch_batting_logs() and fetch_pitching_logs()
# ---------------------------------------------------------------------------

def _checkpoint_paths(final_path):
    d, name = os.path.split(final_path)
    return (os.path.join(d, f".{name}.checkpoint.csv"),
            os.path.join(d, f".{name}.done.json"))


def _load_checkpoint(final_path):
    ckpt_csv, ckpt_done = _checkpoint_paths(final_path)
    rows, done = [], set()
    if os.path.exists(ckpt_csv) and os.path.exists(ckpt_done):
        try:
            # Let pandas infer real numeric dtypes (not dtype=str) so
            # checkpoint-loaded rows match the plain int/float types fresh
            # API rows use — mixing str and int in the same column would
            # make the final sort_values(['player_id', 'date']) raise
            # TypeError ('<' not supported between str and int).
            rows = pd.read_csv(ckpt_csv).to_dict('records')
            with open(ckpt_done) as f:
                done = set(json.load(f))
            print(f"   Resuming from checkpoint: {len(rows):,} rows, "
                  f"{len(done):,} player-seasons already fetched")
        except Exception as e:
            print(f"   Checkpoint unreadable ({e}) — starting fresh")
            rows, done = [], set()
    return rows, done


def _save_checkpoint(final_path, rows, done):
    ckpt_csv, ckpt_done = _checkpoint_paths(final_path)
    pd.DataFrame(rows).to_csv(ckpt_csv, index=False)
    with open(ckpt_done, 'w') as f:
        json.dump(sorted(done), f)


def _clear_checkpoint(final_path):
    for p in _checkpoint_paths(final_path):
        if os.path.exists(p):
            os.remove(p)


def _closed_season_keys(final_path):
    """(player_id, season) keys already on file for seasons strictly before
    the current one (SEASONS[-1]). Closed seasons never change once the
    season ends, so a nightly refresh doesn't need to re-fetch them for a
    player it already has -- only the current season, plus full backfill
    for a player with no history at all yet (a call-up), need a real API
    call. This is the incremental-fetch design added 2026-08-02: the old
    behavior re-pulled all of SEASONS for every player every night (6,590
    calls), which was the actual driver of the 8-24h nightly runtime, not
    just the degraded-endpoint backoff cost.

    Keyed off the existing MERGED file (not the in-run checkpoint), since
    this is a cross-night skip decision, not a same-run resume. Row-count
    completeness isn't re-validated here -- if a key exists at all for a
    closed season, it's trusted, matching how _merge_and_save's own
    confirmed/preserved split already works.
    """
    if not os.path.exists(final_path):
        return set()
    try:
        existing = pd.read_csv(final_path, usecols=['player_id', 'season'], low_memory=False)
    except Exception:
        return set()
    closed = existing[existing['season'] < SEASONS[-1]]
    return set(closed['player_id'].astype(str) + ':' + closed['season'].astype(str))


def _merge_and_save(final_path, new_rows, confirmed_keys, label):
    """Merge this run's rows onto the existing file by (player_id, season)
    instead of overwriting it outright. Only player-seasons in
    `confirmed_keys` (a real answer this run, success or genuine zero-games)
    replace what's already on file; everything else -- including any
    player-season that FAILED this run -- is left untouched, so a degraded
    API day can only add data, never erase it. Returns the merged df.
    """
    new_df = pd.DataFrame(new_rows)
    if not new_df.empty:
        new_df['date'] = pd.to_datetime(new_df['date'], errors='coerce')

    if os.path.exists(final_path):
        existing = pd.read_csv(final_path, low_memory=False)
        existing['date'] = pd.to_datetime(existing['date'], errors='coerce')
        existing_keys = existing['player_id'].astype(str) + ':' + existing['season'].astype(str)
        existing = existing[~existing_keys.isin(confirmed_keys)]
        before_players = existing['player_id'].nunique() if 'player_id' in existing.columns else 0
    else:
        existing = pd.DataFrame()
        before_players = 0

    merged = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
    if merged.empty:
        print(f"WARNING: No {label} data collected and no existing file to merge onto.")
        return merged

    merged = merged.sort_values(['player_id', 'date']).reset_index(drop=True)
    merged.to_csv(final_path, index=False)

    after_players = merged['player_id'].nunique()
    print(f"\n✅  {label.capitalize()} logs saved: {len(merged):,} rows → {final_path}", flush=True)
    print(f"    Players: {after_players:,} (was {before_players:,} before this run's merge)")
    print(f"    Date range: {merged['date'].min().date()} → {merged['date'].max().date()}")
    return merged


def fetch_batting_logs(resume=True, incremental=True):
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"\n--- DOWNLOADING BATTING LOGS ({min(SEASONS)}-{max(SEASONS)}) ---", flush=True)

    players = get_active_players(SEASONS[-1])
    # Filter out pitchers for batting logs
    batters = [p for p in players
               if p.get('primaryPosition', {}).get('code', '') not in ('1',)]
    print(f"   {len(batters)} position players found in {SEASONS[-1]} roster", flush=True)

    if batters:
        probe_gamelog_health(batters[0]['id'], SEASONS[-1], 'hitting')

    already_have = _closed_season_keys(BATTING_FILE) if incremental else set()

    all_rows, done = (_load_checkpoint(BATTING_FILE) if resume else ([], set()))
    # Real calls this run = every (player, current season) pair, plus any
    # (player, closed season) pair not already covered by already_have --
    # i.e. new call-ups needing a full historical backfill. See
    # _closed_season_keys for why closed seasons are otherwise skipped.
    to_fetch = [(season, player) for season in SEASONS for player in batters
                if not (incremental and season != SEASONS[-1]
                        and f"{player['id']}:{season}" in already_have)]
    skipped_incremental = len(batters) * len(SEASONS) - len(to_fetch)
    total = len(to_fetch)
    if incremental and skipped_incremental:
        print(f"   Incremental: skipping {skipped_incremental:,} closed-season "
              f"player-seasons already on file, fetching {total:,} this run "
              f"(current season for everyone + full backfill for new players)", flush=True)
    processed = len(done)
    since_checkpoint = 0
    failed_count = 0

    for season in SEASONS:
        season_rows = 0
        for player in batters:
            key = f"{player['id']}:{season}"
            if key in done:
                continue
            if incremental and season != SEASONS[-1] and key in already_have:
                continue

            processed += 1
            since_checkpoint += 1
            if processed % 100 == 0:
                print(f"   Progress: {processed}/{total} ({100*processed//total}%)  "
                      f"rows so far: {len(all_rows):,}  failed: {failed_count}", flush=True)

            splits = get_game_logs(player['id'], season, 'hitting')
            if splits is FAILED:
                failed_count += 1
                time.sleep(0.08)
                continue  # not added to `done` -- existing data for this player-season is preserved, and a resumed run will retry it
            for s in splits:
                stat = s.get('stat', {})
                ab   = stat.get('atBats', 0)
                if ab == 0:
                    continue
                hits    = stat.get('hits', 0)
                doubles = stat.get('doubles', 0)
                triples = stat.get('triples', 0)
                hr      = stat.get('homeRuns', 0)
                tb      = stat.get('totalBases', hits + doubles + 2*triples + 3*hr)

                all_rows.append({
                    'player_id':   player['id'],
                    'player_name': player.get('fullName', ''),
                    'date':        s.get('date', ''),
                    'season':      season,
                    'is_home':     1 if s.get('isHome', False) else 0,
                    'opponent_id': s.get('opponent', {}).get('id', 0),
                    'team_id':     s.get('team', {}).get('id', 0),
                    'H':           hits,
                    'TB':          tb,
                    'HR':          hr,
                    'RBI':         stat.get('rbi', 0),
                    'R':           stat.get('runs', 0),
                    'SO':          stat.get('strikeOuts', 0),
                    'BB':          stat.get('baseOnBalls', 0),
                    'AB':          ab,
                    'PA':          stat.get('plateAppearances', ab),
                    'SB':          stat.get('stolenBases', 0),
                    '2B':          doubles,
                    '3B':          triples,
                })
                season_rows += 1

            done.add(key)
            if since_checkpoint >= CHECKPOINT_EVERY:
                _save_checkpoint(BATTING_FILE, all_rows, done)
                since_checkpoint = 0

            time.sleep(0.08)

        print(f"   Season {season}: {season_rows:,} game rows", flush=True)

    print(f"   {failed_count} player-seasons failed this run (existing data preserved for those)", flush=True)
    _check_failure_rate('batting', failed_count, total)
    merged = _merge_and_save(BATTING_FILE, all_rows, done, 'batting')
    _clear_checkpoint(BATTING_FILE)
    return merged


def fetch_pitching_logs(resume=True, incremental=True):
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"\n--- DOWNLOADING PITCHING LOGS ({min(SEASONS)}-{max(SEASONS)}) ---", flush=True)

    players = get_active_players(SEASONS[-1])
    # Pitchers + two-way players
    pitchers = [p for p in players
                if p.get('primaryPosition', {}).get('code', '') in ('1', 'TWP')]
    print(f"   {len(pitchers)} pitchers found in {SEASONS[-1]} roster", flush=True)

    if pitchers:
        probe_gamelog_health(pitchers[0]['id'], SEASONS[-1], 'pitching')

    already_have = _closed_season_keys(PITCHING_FILE) if incremental else set()

    all_rows, done = (_load_checkpoint(PITCHING_FILE) if resume else ([], set()))
    to_fetch = [(season, player) for season in SEASONS for player in pitchers
                if not (incremental and season != SEASONS[-1]
                        and f"{player['id']}:{season}" in already_have)]
    skipped_incremental = len(pitchers) * len(SEASONS) - len(to_fetch)
    total = len(to_fetch)
    if incremental and skipped_incremental:
        print(f"   Incremental: skipping {skipped_incremental:,} closed-season "
              f"player-seasons already on file, fetching {total:,} this run "
              f"(current season for everyone + full backfill for new players)", flush=True)
    processed = len(done)
    since_checkpoint = 0
    failed_count = 0

    for season in SEASONS:
        season_rows = 0
        for player in pitchers:
            key = f"{player['id']}:{season}"
            if key in done:
                continue
            if incremental and season != SEASONS[-1] and key in already_have:
                continue

            processed += 1
            since_checkpoint += 1
            if processed % 50 == 0:
                print(f"   Progress: {processed}/{total} ({100*processed//total}%)  "
                      f"rows so far: {len(all_rows):,}  failed: {failed_count}", flush=True)

            splits = get_game_logs(player['id'], season, 'pitching')
            if splits is FAILED:
                failed_count += 1
                time.sleep(0.08)
                continue  # not added to `done` -- existing data for this player-season is preserved, and a resumed run will retry it
            for s in splits:
                stat = s.get('stat', {})
                ip   = stat.get('inningsPitched', '0.0')
                outs = _ip_to_outs(ip)
                if outs == 0:
                    continue

                all_rows.append({
                    'player_id':   player['id'],
                    'player_name': player.get('fullName', ''),
                    'date':        s.get('date', ''),
                    'season':      season,
                    'is_home':     1 if s.get('isHome', False) else 0,
                    'opponent_id': s.get('opponent', {}).get('id', 0),
                    'team_id':     s.get('team', {}).get('id', 0),
                    'is_starter':  1 if stat.get('gamesStarted', 0) > 0 else 0,
                    'K':           stat.get('strikeOuts', 0),
                    'ER':          stat.get('earnedRuns', 0),
                    'OUTS':        outs,
                    'HA':          stat.get('hits', 0),
                    'BBA':         stat.get('baseOnBalls', 0),
                    'HR_A':        stat.get('homeRuns', 0),
                    'pitches':     stat.get('numberOfPitches', 0),
                    'batters_faced': stat.get('battersFaced', 0),
                })
                season_rows += 1

            done.add(key)
            if since_checkpoint >= CHECKPOINT_EVERY:
                _save_checkpoint(PITCHING_FILE, all_rows, done)
                since_checkpoint = 0

            time.sleep(0.08)

        print(f"   Season {season}: {season_rows:,} game rows", flush=True)

    print(f"   {failed_count} player-seasons failed this run (existing data preserved for those)", flush=True)
    _check_failure_rate('pitching', failed_count, total)
    merged = _merge_and_save(PITCHING_FILE, all_rows, done, 'pitching')
    _clear_checkpoint(PITCHING_FILE)
    return merged


if __name__ == "__main__":
    import sys
    full = "--full" in sys.argv
    print("=" * 55)
    print("   ⚾ MLB DATA BUILDER" + ("  (FULL RE-PULL)" if full else "  (incremental)"))
    print("=" * 55)
    fetch_batting_logs(incremental=not full)
    fetch_pitching_logs(incremental=not full)
    print("\n" + "=" * 55)
    print("✅  BUILD COMPLETE")
    print("   Next: Run features.py → train.py")
    print("=" * 55)
