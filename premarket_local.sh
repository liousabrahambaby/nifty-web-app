#!/usr/bin/env bash
# Morning forecast from your own PC. cron:  15 8 * * 1-5  /path/to/premarket_local.sh
cd "$(dirname "$0")" && git pull -q && python3 analyze.py --premarket && \
git add data.json && { [ -f gap_track.json ] && git add gap_track.json; true; } && \
git commit -qm "Pre-market update $(date +%F)" && git push -q
