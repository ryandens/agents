#!/bin/sh
if [ "${SCAN_FIXTURE_CRASH:-}" = "1" ]; then
    echo 'fixture: scanner crashed' >&2
    exit 2
fi
if [ "${SCAN_FIXTURE_SUPPRESSED:-}" = "1" ]; then
    printf '%s' '{"version":"2.1.0","runs":[{"results":[{"suppressions":[{"kind":"inSource"}]}]}]}' > /reports/results.sarif
    exit "${SCAN_FIXTURE_EXIT:-1}"
fi
printf '%s' '{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"fixture"}},"results":[]}]}' > /reports/results.sarif
exit "${SCAN_FIXTURE_EXIT:-0}"
