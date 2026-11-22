# Nifty 50 EOD Dashboard (React)

Price chart with indicators, NSE option chain (OI, PCR, max pain), India VIX,
a rule-based CE/PE/no-trade signal, and a track record that grades every
signal against the next day's actual market move.

The website is a React app (Vite). The analysis is still the Python script
`analyze.py`, which writes `data.json`; the React app reads that file.

## Project layout
```
analyze.py, kite_morning.py, *.bat, *.sh   Python analysis + local schedulers (unchanged)
index.html, login.html, kite.html          the three pages (each mounts a React app)
src/
  main.jsx, login.jsx, kite.jsx            page entry points
  dashboard/                               dashboard sections and tabs
    App.jsx                                loads data.json, holds shared state
    Hero, Alerts, Premarket, GlobalMarkets, News
    DashboardPanel + PriceChart, PlaybookPanel, OptionsPanel, TrackPanel
  login/LoginPage.jsx                      demo login (credentials at the top)
  kite/KitePage.jsx                        Kite redirect page (API key at the top)
  components/Plot.jsx                      small Plotly wrapper
  lib/                                     formatting, auth, chart theme
  styles/                                  page styles
public/                                    icons and manifest, copied as-is
.github/workflows/update.yml               data updates + build + deploy
```

## Run it on your computer
Needs Node.js 18+ and Yarn, plus Python for the data.
```
yarn install
python analyze.py --demo     # or: python analyze.py   (live data)
yarn dev                     # http://localhost:5173  (login: admin / admin123)
```
`yarn build` makes the production site in `dist/` (including `data.json`);
`yarn preview` serves that build.

## Setup on GitHub (one time)
1. Create a GitHub repo and upload all these files (including the `.github` folder and `yarn.lock`).
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
   (Not "Deploy from branch": the React app has to be built before it can be served.)
3. Actions tab → "Update Nifty data" → Run workflow (creates data.json the first time and deploys the site).
4. Open https://<your-username>.github.io/<repo>/

After that it refreshes itself every weekday:
- 4:00 PM IST: full analysis after the market closes
- 8:15 AM IST: pre-market run with news, FII/DII, global markets and the opening-gap forecast
  (GitHub often starts scheduled runs 5-20 minutes late, so it's usually ready by about 8:30)

Every data run rebuilds and redeploys the site. Pushing to `main` (code changes, or
data from `update_local` / `premarket_local`) also rebuilds and redeploys.

To run either one by hand: Actions -> Update Nifty data -> Run workflow -> choose "full" or "premarket".

## Opening-gap forecast and GIFT Nifty
Every morning the forecast predicts a gap up, gap down or flat open, with points and
an expected opening level. It's graded against the actual open in the evening run
(saved in `gap_track.json`).

It always uses a **global cues model**: how far S&P 500 futures have moved since
Nifty's last close, scaled by how Nifty has historically gapped on such moves
(refitted on 2 years of data each evening).

**GIFT Nifty is fetched automatically** from NSE IX's own public website (nseix.com),
the exchange where it trades. No login or keys needed. The evening run records each
contract's price around Nifty's close, and the morning run compares the same contract's
price now with that, which gives the implied gap. If NSE IX blocks GitHub's servers
(exchanges sometimes block cloud servers), the forecast falls back to the global
cues model; running `premarket_local.bat` / `.sh` from your PC usually fixes that.

**Optional backup: Zerodha Kite** (paid Kite Connect plan, ₹500/month; needs a manual
login every morning after 7:35 AM, as the exchange requires).
1. developers.kite.trade -> your app -> Redirect URL = `https://<your-username>.github.io/<repo>/kite.html`
2. GitHub -> Settings -> Secrets and variables -> Actions: add `KITE_API_KEY` and `KITE_API_SECRET`
   (the secret lives only there, never in a file).
3. Paste your API key (not the secret) into the `KITE_API_KEY` line of `src/kite/KitePage.jsx`.
Then on any morning: cockpit -> "Use Kite instead" -> log in -> copy the code -> GitHub ->
Run workflow -> premarket -> paste it. From a PC: `python kite_morning.py`.

## AI analysis tab
Every 4 PM run also does a technical analysis of the daily chart and shows it in the
**AI analysis** tab:
- A pattern scanner in `analyze.py` finds candlestick patterns (engulfing, hammer, doji,
  stars...), chart patterns (double top/bottom, head and shoulders, triangles, wedges,
  channels), trendlines, support/resistance zones, Fibonacci retracements, RSI divergence,
  ADX trend strength and swing structure, and merges them into a list of major levels.
- Claude (`claude-opus-5-5`) reads those findings with the last 40 sessions, the indicators,
  pivots and option-chain levels, then writes the outlook, conditional suggestions, the
  levels to watch and what would prove the view wrong.
- Each day's outlook is saved in `analysis_track.json` and graded against the next
  session's close, so the tab shows how often it has been right.

To turn Claude on, add an `ANTHROPIC_API_KEY` secret (GitHub -> Settings -> Secrets and
variables -> Actions). It costs roughly 5-15 US cents a day (one request per weekday). Without the
key, or if the call fails, the tab shows a rule-based note built from the same scanner
results. `--demo` and `--no-ai` runs always use the rule-based note.

## Login
The site opens on `login.html`. Demo credentials: **admin / admin123**.
To change them, edit `USERNAME` and `PASS_HASH` at the top of `src/login/LoginPage.jsx`
(the comment there shows how to make a new hash).
This is a browser-only login: it keeps casual visitors out but is not real
security. Anyone determined can read the page source or open `data.json`
directly. For real protection, use a private host (for example Cloudflare
Pages with Cloudflare Access, or Netlify with password protection).

## Files the script keeps
- `data.json`  – everything the page shows (rewritten each run)
- `track.json` – the permanent signal log. Don't delete it, or the track record restarts.
- `oc_cache.json` – last good option-chain snapshot, shown (flagged as old) if NSE fails.
- `analysis_track.json` – every day's AI/technical outlook and whether the next session agreed.
- `fii_dii_track.json` – FII/DII cash-market buy, sell and net figures, one row per trading day.
  NSE only publishes the latest day, so this is the only place the history exists; don't delete it.
  It feeds the **FII / DII trend** chart under the news (daily or cumulative net, 5- and 20-day totals,
  buying/selling streaks) and the AI analysis.

## If the option chain shows "couldn't be fetched"
NSE often blocks requests from cloud servers, including GitHub's. Prices, VIX
and signals still update; only the option-chain panel goes missing or stale.
Fix: run the update from your own computer instead.
- Windows: install Python + Git, `pip install -r requirements.txt`, then schedule
  `update_local.bat` in Task Scheduler for weekdays 4:00 PM.
- Mac/Linux: schedule `update_local.sh` with cron (`0 16 * * 1-5`).
For the morning forecast, schedule `premarket_local.bat` / `premarket_local.sh` at 8:15 AM.
Pushing the new data triggers a rebuild and deploy of the site.
You can then disable the scheduled runs by removing the `schedule:` lines from the workflow
(keep the workflow itself enabled, since it does the deploying).

Educational only — not investment advice.
