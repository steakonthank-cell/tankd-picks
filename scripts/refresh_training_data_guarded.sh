#!/bin/bash
# Hard-timeout wrapper for scripts/refresh_training_data.py.
#
# Root cause of the 2026-08-01/02 incident: refresh_training_data.py's
# fetch_batting_logs()/fetch_pitching_logs() have per-call retry limits
# (4 attempts, 20s timeout each -- see builder.py::_get) but NO overall
# circuit breaker. probe_gamelog_health() detects a degraded MLB gameLog
# endpoint up front but deliberately "proceeds anyway" (by design, so a
# transient blip doesn't abort a run that would otherwise succeed) -- if
# the degradation is SUSTAINED instead of transient, nothing stops the
# script from grinding through every remaining player-season at ~15-90s
# per failed call. That's what happened: the 2026-08-01 04:00 cron run
# hit a ~98% failure rate and was still running, stuck, 20 hours later,
# competing for memory with everything else on this box until it was
# manually killed. It had not corrupted anything (builder.py's
# checkpoint/merge-not-overwrite design held), it just never finished.
#
# This wrapper adds the missing outer bound: a hard wall-clock timeout,
# plus a Discord alert (same MLB_PITCHER_WEBHOOK used by the script's own
# sanity-drop alert) on timeout OR any nonzero exit, so a repeat of this
# is loud instead of silently eating a day (or 20 hours) of runtime.
#
# TIMEOUT_MINUTES: historical "Done" runs in refresh_training_data.log range
# 29,002s-86,612s (8.1h-24.1h, median 8.8h) -- healthy runs routinely take
# most of a day, not "well under an hour" as an earlier draft of this
# comment assumed (that number was never checked against the actual log and
# would have killed every single run, healthy or not). Set to 18h: comfortably
# above the slowest run that still finished on its own, but with enough
# margin before the next 24h cron fire (0 4 * 3-10 *) that a timed-out run
# can't still be exiting when the next one starts.
#
# LOCK_FILE: flock -n so a run that's still going (whether mid-timeout-window
# or, if the timeout is ever disabled/changed, genuinely overrun) can't get a
# second instance stacked on top of it -- two copies of this on a 1-vCPU/1GB
# box is exactly the kind of memory pressure that led to the manual kill in
# the 2026-08-01/02 incident.
set -uo pipefail

cd /root/tankd-picks
TIMEOUT_MINUTES=1080
LOCK_FILE=/tmp/refresh_training_data.lock
LOG=/root/refresh_training_data.log

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "=== SKIPPED: previous refresh_training_data run still holds the lock ===" >> "$LOG"
    exit 0
fi
WEBHOOK="${MLB_PITCHER_WEBHOOK:-}"
if [ -z "$WEBHOOK" ] && [ -f .env ]; then
    WEBHOOK=$(grep -m1 '^MLB_PITCHER_WEBHOOK=' .env | cut -d= -f2-)
fi

alert() {
    local message="$1"
    if [ -z "$WEBHOOK" ]; then
        echo "   (MLB_PITCHER_WEBHOOK not set -- skipping Discord alert: $message)" >> "$LOG"
        return
    fi
    curl -s -X POST -H "Content-Type: application/json" \
        -d "$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1]}))' "$message")" \
        "$WEBHOOK" >/dev/null 2>&1
}

START_TS=$(date +%s)
timeout "${TIMEOUT_MINUTES}m" .venv/bin/python scripts/refresh_training_data.py >> "$LOG" 2>&1
EXIT_CODE=$?
ELAPSED_MIN=$(( ($(date +%s) - START_TS) / 60 ))

if [ "$EXIT_CODE" -eq 124 ]; then
    echo "=== TIMED OUT after ${TIMEOUT_MINUTES}m (killed by guard wrapper) ===" >> "$LOG"
    alert "🚨 refresh_training_data.py TIMED OUT after ${TIMEOUT_MINUTES} minutes and was killed. Training data did not refresh tonight -- likely a sustained MLB gameLog API degradation (same class as the 2026-08-01/02 incident). Check ${LOG}."
elif [ "$EXIT_CODE" -ne 0 ]; then
    echo "=== EXITED NONZERO ($EXIT_CODE) after ${ELAPSED_MIN}m ===" >> "$LOG"
    alert "🚨 refresh_training_data.py exited with code ${EXIT_CODE} after ${ELAPSED_MIN} minutes. Training data may not have refreshed. Check ${LOG}."
fi

exit "$EXIT_CODE"
