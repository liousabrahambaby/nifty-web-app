@echo off
REM Morning forecast from your own Windows PC. Schedule in Task Scheduler: weekdays 8:15 AM.
cd /d "%~dp0"
git pull -q
python analyze.py --premarket
git add data.json
if exist gap_track.json git add gap_track.json
git commit -qm "Pre-market update"
git push -q
