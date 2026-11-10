#!/bin/sh
# A deterministic blocked-install fixture, never a production firewall substitute.
if [ "${SOCKET_FIXTURE_BLOCK:-}" = "1" ]; then
    echo 'fixture: package blocked' >&2
    exit 29
fi
exec "$@"
