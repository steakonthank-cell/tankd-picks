"""
Builds/refreshes data/mlb/pitcher_hand_cache.json — a persistent
{player_id: 'L'|'R'|'S'} map used to reconstruct vs-hand splits from raw
game logs (starter identification + this static bio attribute), since
MLB's statSplits endpoint has 406'd unconditionally since 2026-07-04.

Fetches sequentially against /people/{id} — a separate, still-healthy
endpoint (confirmed 200 while statSplits still 406s) — one at a time with
a fixed delay, deliberately not parallelized. Writes to a temp file and
atomically renames over the real cache so an interrupted run can't leave
a half-written file, and refuses to replace a good cache with a worse one
(same sanity-floor pattern as scripts/refresh_training_data.py).

Usage: .venv/bin/python scripts/build_pitcher_hand_cache.py
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pandas as pd

CACHE_PATH           = 'data/mlb/pitcher_hand_cache.json'
REQUEST_DELAY_SEC     = 1.0    # sequential pacing between calls — widened after
                                # two prior back-to-back ~600-call runs in the
                                # same session showed degrading resolve rates,
                                # consistent with cumulative rate-limiting
MAX_RETRIES           = 3
RETRY_BACKOFF_SEC     = 2.0

_MLB_API = "https://statsapi.mlb.com/api/v1"
_http = requests.Session()
_http.headers.update({"User-Agent": "Mozilla/5.0"})


def fetch_hand(player_id) -> str:
    """Return 'L', 'R', or 'S' for one pitcher; '' if unresolved."""
    for attempt in range(MAX_RETRIES):
        try:
            r = _http.get(f"{_MLB_API}/people/{player_id}", timeout=8)
            if r.status_code == 200:
                people = r.json().get('people', [{}])
                return people[0].get('pitchHand', {}).get('code', '') if people else ''
        except Exception:
            pass
        time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    return ''


def load_existing_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def coverage(d: dict) -> float:
    if not d:
        return 0.0
    resolved = sum(1 for v in d.values() if v in ('L', 'R', 'S'))
    return resolved / len(d)


def main():
    pitching = pd.read_csv('data/mlb/raw/pitching_logs.csv')
    pitcher_ids = sorted(pitching['player_id'].unique().tolist())
    print(f"{len(pitcher_ids)} unique pitcher_ids in raw pitching_logs.csv", flush=True)

    existing = load_existing_cache()
    print(f"{len(existing)} already cached (seed)", flush=True)

    result = dict(existing)
    to_fetch = [pid for pid in pitcher_ids
                if str(pid) not in result or result[str(pid)] not in ('L', 'R', 'S')]
    print(f"{len(to_fetch)} need fetching", flush=True)

    fetched_ok = 0
    for i, pid in enumerate(to_fetch, 1):
        hand = fetch_hand(pid)
        result[str(pid)] = hand
        if hand:
            fetched_ok += 1
        if i % 25 == 0 or i == len(to_fetch):
            print(f"  {i}/{len(to_fetch)} fetched ({fetched_ok} resolved)", flush=True)
        time.sleep(REQUEST_DELAY_SEC)

    new_cov = coverage(result)
    old_cov = coverage(existing)
    new_resolved = sum(1 for v in result.values() if v in ('L', 'R', 'S'))
    old_resolved = sum(1 for v in existing.values() if v in ('L', 'R', 'S'))
    print(f"New coverage: {new_cov:.1%} ({new_resolved}/{len(result)} ids) | "
          f"old coverage: {old_cov:.1%} ({old_resolved}/{len(existing)} ids)", flush=True)

    # `result` only ever fetches pids that were missing or unresolved in
    # `existing` (see `to_fetch` above) — an already-good entry is never
    # re-fetched, so it can never be overwritten with something worse. That
    # makes resolved *count* monotonic across runs by construction; a
    # coverage *percentage* floor isn't, since expanding to the full pitcher
    # universe legitimately dilutes the percentage even as real, permanent
    # progress is made. Guard against an actual regression (count going
    # down, which would mean a bug elsewhere) instead of a percentage floor.
    if new_resolved < old_resolved:
        print(f"ABORT: resolved count went DOWN ({old_resolved} -> {new_resolved}) — "
              f"that shouldn't be possible given how `to_fetch` is built, treating it "
              f"as a bug and leaving {CACHE_PATH} untouched.", flush=True)
        return 1

    tmp_path = f"{CACHE_PATH}.tmp-{os.getpid()}"
    with open(tmp_path, 'w') as f:
        json.dump(result, f, indent=0, sort_keys=True)
    os.replace(tmp_path, CACHE_PATH)  # atomic on same filesystem
    print(f"SAVED {CACHE_PATH} ({len(result)} pitchers, {new_cov:.1%} resolved)", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
