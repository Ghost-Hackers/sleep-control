#!/bin/sh
# Starts Sleep Control from the copy installed in the Flatpak.
PYTHONPATH=/app/share/sleep-control${PYTHONPATH:+:$PYTHONPATH}
export PYTHONPATH
exec python3 -m sleep_control "$@"
