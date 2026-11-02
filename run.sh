#!/bin/sh
set -eu
if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    exec python -m car_space_checker.addon
fi
exec python -m car_space_checker serve
