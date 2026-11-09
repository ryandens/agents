#!/bin/sh
[ "$1" = "--no-global" ] || exit 29
exit "${VALIDATOR_FIXTURE_EXIT:-0}"
