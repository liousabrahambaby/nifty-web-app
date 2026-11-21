@echo off
REM Run the update from your own Windows PC (use if NSE blocks GitHub's servers).
REM Schedule it with Task Scheduler: weekdays at 4:00 PM.
cd /d "%~dp0"
git pull -q
python analyze.py
git add data.json track.json
if exist oc_cache.json git add oc_cache.json
if exist gap_track.json git add gap_track.json
git commit -qm "Local data update"
git push -q
