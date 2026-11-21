"""
Nifty 50 end-of-day analyzer.

Each run:
  1. Downloads daily Nifty 50 and India VIX prices (Yahoo Finance via yfinance)
  2. Downloads the Nifty option chain from NSE (open interest, PCR, max pain)
  3. Computes indicators, key levels and a rule-based CE / PE / no-trade signal
  4. Logs today's signal to track.json and grades earlier signals against
     what the market actually did the next day
  5. Writes everything the web page needs to data.json

Usage:
    python analyze.py                  # live data
    python analyze.py --demo           # synthetic data, for testing offline
    python analyze.py --demo --cut 3   # demo data minus the last 3 days
"""
import json
import os
import sys
import datetime as dt

import numpy as np
import pandas as pd

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
STRIKE_STEP = 50          # Nifty strikes are 50 points apart
CHAIN_STRIKES_EACH_SIDE = 15
BACKFILL_DAYS = 60        # first run: grade the rule over this many past days
TRACK_FILE = "track.json"
CHAIN_CACHE = "oc_cache.json"
NSE = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}


# =====================================================================
# Price data
# =====================================================================
def _yf(symbol, period="2y", interval="1d"):
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval,
                     auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_live():
    nifty = _yf("^NSEI")[["Open", "High", "Low", "Close", "Volume"]].dropna()
    try:
        vix = _yf("^INDIAVIX")["Close"].dropna()
    except Exception as e:
        print("VIX download failed:", e)
        vix = pd.Series(dtype=float)
    return nifty, vix


def load_demo(n=500):
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end=dt.date.today(), periods=n)
    close = 22000 * np.exp(np.cumsum(rng.normal(0.0004, 0.009, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - abs(rng.normal(0, 0.004, n)))
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                       "Volume": rng.integers(2e5, 6e5, n)}, index=idx)
    vix = pd.Series(np.clip(14 + np.cumsum(rng.normal(0, 0.4, n)), 9, 35), index=idx)
    return df, vix


# ---------- intraday (for the 1D / 5D chart views) ----------
INTRADAY_VIEWS = {  # view: (candle size, how much to download, sessions to show)
    "1d": ("5m", "5d", 1),
    "5d": ("15m", "1mo", 5),
}


def load_intraday_live(interval, period):
    df = _yf("^NSEI", period=period, interval=interval)
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    df.index = idx.tz_convert("Asia/Kolkata")
    return df[["Open", "High", "Low", "Close"]].dropna()


def load_intraday_demo(interval, last_close, sessions=22):
    step = int(interval.rstrip("m"))
    rng = np.random.default_rng(11)
    days = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=sessions)
    stamps = [pd.Timestamp(f"{d.date()} 09:15") + pd.Timedelta(minutes=step * i)
              for d in days for i in range(375 // step + 1)]
    close = np.exp(np.cumsum(rng.normal(0, 0.0012 * np.sqrt(step / 5), len(stamps))))
    close = close / close[-1] * last_close
    open_ = np.r_[close[0], close[:-1]]
    spread = abs(rng.normal(0, 0.0006, len(stamps))) * close
    return pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) + spread,
                         "Low": np.minimum(open_, close) - spread, "Close": close},
                        index=pd.DatetimeIndex(stamps))


def build_intraday(df, sessions):
    """Indicators are computed on all downloaded bars (so they're warmed up),
    then only the last `sessions` trading days are kept for the chart."""
    df = add_indicators(df.copy())
    days = sorted(set(df.index.date))
    keep = set(days[-sessions:])
    mask = np.array([d in keep for d in df.index.date])
    sub, before = df[mask], df[~mask]
    label = "%H:%M" if sessions == 1 else "%d %b %H:%M"

    def col(name):
        return [None if pd.isna(v) else round(float(v), 2) for v in sub[name]]

    return {
        "dates": [t.strftime(label) for t in sub.index],
        **{k.lower(): col(k) for k in ["Open", "High", "Low", "Close", "SMA20", "SMA50", "SMA200",
                                         "BB_UP", "BB_LO", "RSI", "MACD", "MACD_SIG", "MACD_HIST"]},
        "prev_close": round(float(before["Close"].iloc[-1]), 2) if len(before) else None,
        "from": min(keep).strftime("%d %b %Y"), "to": max(keep).strftime("%d %b %Y"),
    }


def get_intraday(demo, last_close):
    out = {}
    for view, (interval, period, sessions) in INTRADAY_VIEWS.items():
        try:
            raw = (load_intraday_demo(interval, last_close) if demo
                   else load_intraday_live(interval, period))
            out[view] = build_intraday(raw, sessions) | {"interval": interval}
        except Exception as e:  # never let intraday problems break the daily update
            print(f"Intraday {view} failed:", e)
    return out


# =====================================================================
# Option chain (NSE)
# =====================================================================
def fetch_option_chain(as_of):
    """Return the raw option-chain rows for the nearest expiry after as_of."""
    import requests
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get(NSE + "/option-chain", timeout=20)  # sets the cookies NSE requires

    def pick_expiry(dates):
        parsed = sorted(dt.datetime.strptime(d, "%d-%b-%Y").date() for d in dates)
        future = [d for d in parsed if d > as_of] or parsed
        return future[0].strftime("%d-%b-%Y")

    try:  # current API
        info = s.get(NSE + "/api/option-chain-contract-info",
                     params={"symbol": "NIFTY"}, timeout=20).json()
        expiry = pick_expiry(info["expiryDates"])
        raw = s.get(NSE + "/api/option-chain-v3",
                    params={"type": "Indices", "symbol": "NIFTY", "expiry": expiry},
                    timeout=20).json()
    except Exception:  # older API, kept as a fallback
        raw = s.get(NSE + "/api/option-chain-indices",
                    params={"symbol": "NIFTY"}, timeout=20).json()
        expiry = pick_expiry(raw["records"]["expiryDates"])

    rec = raw.get("records", raw)
    rows = [r for r in rec["data"] if r.get("expiryDate", expiry) == expiry]
    if not rows:
        raise ValueError("Option chain came back empty")
    spot = rec.get("underlyingValue") or next(
        (r[k]["underlyingValue"] for r in rows for k in ("CE", "PE") if k in r), None)
    return expiry, spot, rows


def demo_option_chain(spot):
    rng = np.random.default_rng(3)
    atm = round(spot / STRIKE_STEP) * STRIKE_STEP
    rows = []
    for k in range(atm - 40 * STRIKE_STEP, atm + 41 * STRIKE_STEP, STRIKE_STEP):
        d = (k - atm) / STRIKE_STEP
        ce = int(max(0, 9e4 * np.exp(-((d - 4) / 8) ** 2) * rng.uniform(.6, 1.4)))
        pe = int(max(0, 9e4 * np.exp(-((d + 4) / 8) ** 2) * rng.uniform(.6, 1.4)))
        rows.append({"strikePrice": k,
                     "CE": {"openInterest": ce, "changeinOpenInterest": int(ce * rng.normal(0, .2))},
                     "PE": {"openInterest": pe, "changeinOpenInterest": int(pe * rng.normal(0, .2))}})
    exp = (dt.date.today() + dt.timedelta(days=(1 - dt.date.today().weekday()) % 7 or 7))
    return exp.strftime("%d-%b-%Y"), spot, rows


def summarize_chain(expiry, spot, rows):
    df = pd.DataFrame([{
        "strike": r["strikePrice"],
        "ce_oi": (r.get("CE") or {}).get("openInterest", 0) or 0,
        "pe_oi": (r.get("PE") or {}).get("openInterest", 0) or 0,
        "ce_chg": (r.get("CE") or {}).get("changeinOpenInterest", 0) or 0,
        "pe_chg": (r.get("PE") or {}).get("changeinOpenInterest", 0) or 0,
    } for r in rows]).groupby("strike").sum().sort_index()

    k = df.index.values
    pain = [(df.ce_oi * np.maximum(0, x - k)).sum() + (df.pe_oi * np.maximum(0, k - x)).sum() for x in k]
    atm = round(spot / STRIKE_STEP) * STRIKE_STEP
    win = df[(df.index >= atm - CHAIN_STRIKES_EACH_SIDE * STRIKE_STEP) &
             (df.index <= atm + CHAIN_STRIKES_EACH_SIDE * STRIKE_STEP)]
    return {
        "expiry": expiry,
        "spot": round(float(spot), 2),
        "pcr": round(float(df.pe_oi.sum() / max(df.ce_oi.sum(), 1)), 2),
        "pcr_chg_oi": round(float(df.pe_chg.sum() / df.ce_chg.sum()), 2) if df.ce_chg.sum() > 0 else None,
        "max_pain": int(k[int(np.argmin(pain))]),
        "max_ce_oi_strike": int(df.ce_oi.idxmax()),   # heaviest call writing = resistance
        "max_pe_oi_strike": int(df.pe_oi.idxmax()),   # heaviest put writing = support
        "strikes": [int(x) for x in win.index],
        "ce_oi": [int(x) for x in win.ce_oi], "pe_oi": [int(x) for x in win.pe_oi],
        "ce_chg": [int(x) for x in win.ce_chg], "pe_chg": [int(x) for x in win.pe_chg],
        "fetched_at": dt.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "stale": False,
    }


def get_chain(demo, spot, as_of):
    if demo:
        return summarize_chain(*demo_option_chain(spot))
    try:
        oc = summarize_chain(*fetch_option_chain(as_of))
        with open(CHAIN_CACHE, "w") as f:
            json.dump(oc, f)
        return oc
    except Exception as e:
        print("Option chain fetch failed:", e)
        if os.path.exists(CHAIN_CACHE):  # show the last good snapshot, flagged as old
            with open(CHAIN_CACHE) as f:
                oc = json.load(f)
            oc["stale"] = True
            return oc
        return None


# =====================================================================
# News and FII / DII flows
# =====================================================================
# Only headlines, source names, times and links are kept (no article text).
GN = "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
NEWS_FEEDS = [
    GN + "Nifty+Sensex+stock+market+when:2d",
    GN + "FII+OR+FPI+OR+DII+India+stocks+when:2d",
    GN + "global+markets+Fed+OR+crude+OR+dollar+India+when:2d",
    GN + "geopolitical+tensions+OR+war+OR+tariffs+markets+when:2d",
    GN + "RBI+OR+rupee+OR+inflation+India+economy+when:2d",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.livemint.com/rss/markets",
]
NEWS_TOPICS = [  # first match wins
    ("FII / DII", ["fii", "fpi", "dii", "foreign investor", "foreign portfolio", "foreign fund", "institutional investor", "outflow", "inflow"]),
    ("Global", ["fed", "powell", "wall street", "us market", "dow", "nasdaq", "s&p 500", "china", "trump", "tariff", "war", "israel",
                "iran", "russia", "ukraine", "geopolit", "tension", "global", "treasury", "dollar index", "recession", "opec"]),
    ("Policy", ["rbi", "repo", "rate cut", "rate hike", "inflation", "cpi", "gdp", "budget", "sebi", "government", "fiscal", "tax"]),
    ("Commodities", ["crude", "oil", "brent", "gold", "silver", "commodit"]),
    ("Currency", ["rupee", "forex", "inr", "usd/inr"]),
    ("Earnings", ["q1", "q2", "q3", "q4", "results", "earnings", "profit", "revenue", "guidance"]),
]
# Words are matched as word starts, so "rall" also matches "rally" and "rallies".
UP_WORDS = ["rall", "surg", "jump", "soar", "gain", "rise", "rising", "higher", "climb", "record high", "rebound", "recover"]
DOWN_WORDS = ["fall", "fell", "slump", "crash", "plunge", "tumbl", "drop", "slide", "slid", "lower", "decline", "sink", "record low", "weaken"]
GOOD = ["inflow", "net buyer", "buying", "upgrade", "rate cut", "ease", "eases", "easing", "beat", "strong", "boost", "ceasefire",
        "deal", "optimis", "bull", "outperform"]
BAD = ["outflow", "net seller", "selling", "selloff", "sell-off", "downgrade", "rate hike", "tension", "war", "attack", "fear",
       "weak", "miss", "bear", "recession", "tariff", "sanction", "worr", "concern", "drag", "volatil", "uncertain"]
# For these, a rise is bad for Indian stocks (India imports most of its oil; a strong dollar pulls money out)
RISE_IS_BAD = ["crude", "oil", "brent", "dollar index", "us yield", "treasury yield", "bond yield", "vix", "inflation"]


def _tone(t):
    """Rough guess of whether a headline is good or bad for Indian stocks."""
    import re
    w = t.lower()
    has = lambda words: sum(bool(re.search(r"\b" + re.escape(k), w)) for k in words)
    up, down = has(UP_WORDS), has(DOWN_WORDS)
    if any(k in w for k in RISE_IS_BAD) and not any(k in w for k in ["nifty", "sensex", "stocks"]):
        up, down = down, up
    score = up - down + has(GOOD) - has(BAD)
    return "positive" if score > 0 else "negative" if score < 0 else "neutral"


def fetch_news(limit=45, max_age_h=48):
    import re
    import requests
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    now = dt.datetime.now(dt.timezone.utc)
    seen, items = set(), []
    for url in NEWS_FEEDS:
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": NSE_HEADERS["User-Agent"]})
            root = ET.fromstring(r.content)
        except Exception as e:
            print("News feed failed:", url[:70], e)
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            src_el = it.find("source")
            source = src_el.text.strip() if src_el is not None and src_el.text else ""
            if not source:
                source = "Economic Times" if "economictimes" in url else "Mint" if "livemint" in url else ""
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3].strip()
            try:
                when = parsedate_to_datetime(it.findtext("pubDate"))
                when = when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)
            except Exception:
                continue
            if not title or not link.startswith("http") or (now - when).total_seconds() > max_age_h * 3600:
                continue
            key = re.sub(r"[^a-z0-9]", "", title.lower())[:70]
            if key in seen:
                continue
            seen.add(key)
            low = title.lower()
            topic = next((name for name, kws in NEWS_TOPICS if any(k in low for k in kws)), "Markets")
            items.append({"title": title, "source": source, "link": link, "topic": topic, "tone": _tone(title),
                          "time": when.astimezone(IST).isoformat(timespec="minutes")})
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:limit]


def fetch_fii_dii():
    """Latest FII/FPI and DII cash-market activity (Rs crore) from NSE."""
    import requests
    s = requests.Session()
    s.headers.update(NSE_HEADERS | {"Referer": "https://www.nseindia.com/reports/fii-dii"})
    s.get(NSE + "/reports/fii-dii", timeout=20)
    rows = s.get(NSE + "/api/fiidiiTradeReact", timeout=20).json()
    num = lambda v: round(float(str(v).replace(",", "")), 2)
    out = {}
    for r in rows:
        cat = str(r.get("category", "")).upper()
        key = "fii" if "FII" in cat or "FPI" in cat else "dii" if "DII" in cat else None
        if key:
            out[key] = {"buy": num(r["buyValue"]), "sell": num(r["sellValue"]), "net": num(r["netValue"])}
            out["date"] = r.get("date")
    if "fii" not in out:
        raise ValueError("No FII row in NSE response")
    return out


def demo_news():
    now = dt.datetime.now(IST)
    rows = [
        ("FIIs net sellers for third straight session as global risk appetite weakens", "FII / DII"),
        ("DIIs absorb foreign selling with strong buying in banking stocks", "FII / DII"),
        ("US Fed signals patience on rate cuts; Asian markets trade mixed", "Global"),
        ("Crude oil prices jump on Middle East supply concerns", "Commodities"),
        ("Rupee slides to record low against the dollar", "Currency"),
        ("RBI keeps repo rate unchanged, retains neutral stance", "Policy"),
        ("Nifty ends lower as IT and metal stocks drag; midcaps outperform", "Markets"),
        ("Trade talks progress eases tariff worries, boosts global equities", "Global"),
        ("Banking major beats Q2 estimates on strong loan growth", "Earnings"),
    ]
    return [{"title": t, "source": "Demo source", "link": "https://example.com", "topic": tp, "tone": _tone(t),
             "time": (now - dt.timedelta(hours=2 * i + 1)).isoformat(timespec="minutes")} for i, (t, tp) in enumerate(rows)]


def get_news(demo):
    if demo:
        return {"items": demo_news(), "fii_dii": {"date": "20-Nov-2026", "fii": {"buy": 11234.5, "sell": 13890.2, "net": -2655.7},
                                                     "dii": {"buy": 14520.8, "sell": 11102.4, "net": 3418.4}},
                "updated": dt.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")}
    try:
        items = fetch_news()
    except Exception as e:
        print("News failed:", e)
        items = []
    try:
        flows = fetch_fii_dii()
    except Exception as e:
        print("FII/DII fetch failed:", e)
        flows = None
    return {"items": items, "fii_dii": flows, "updated": dt.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")}


# =====================================================================
# Global markets, GIFT Nifty and the opening-gap forecast
# =====================================================================
GLOBAL = [
    ("US", "Dow Jones", "^DJI"), ("US", "S&P 500", "^GSPC"), ("US", "Nasdaq", "^IXIC"),
    ("US futures", "S&P 500 futures", "ES=F"), ("US futures", "Nasdaq futures", "NQ=F"), ("US futures", "Dow futures", "YM=F"),
    ("Asia", "Nikkei 225", "^N225"), ("Asia", "Hang Seng", "^HSI"), ("Asia", "Shanghai", "000001.SS"),
    ("Asia", "Kospi", "^KS11"), ("Asia", "Taiwan", "^TWII"), ("Asia", "ASX 200", "^AXJO"),
    ("Europe", "FTSE 100", "^FTSE"), ("Europe", "DAX", "^GDAXI"), ("Europe", "CAC 40", "^FCHI"), ("Europe", "Euro Stoxx 50", "^STOXX50E"),
    ("Macro", "Brent crude", "BZ=F"), ("Macro", "Gold", "GC=F"), ("Macro", "Dollar index", "DX-Y.NYB"),
    ("Macro", "USD/INR", "INR=X"), ("Macro", "US 10-yr yield", "^TNX"), ("Macro", "US VIX", "^VIX"),
]
GAP_FLAT = 0.15   # |gap| below this % counts as a flat open
GAP_BIG = 0.75    # above this % counts as a big gap
GAP_TRACK = "gap_track.json"


def gap_label(pct):
    if pct is None:
        return "Unknown"
    if abs(pct) < GAP_FLAT:
        return "Flat open"
    size = "Big gap" if abs(pct) >= GAP_BIG else "Gap"
    return f"{size} {'up' if pct > 0 else 'down'}"


def _india_close_utc(as_of):
    return pd.Timestamp(f"{as_of} 10:00", tz="UTC")   # 3:30 PM IST


def fetch_global(as_of):
    import yfinance as yf
    tickers = [t for _, _, t in GLOBAL]
    raw = yf.download(tickers, period="1mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    rows = []
    for region, name, t in GLOBAL:
        try:
            cl = raw[t]["Close"].dropna()
            last, prev = float(cl.iloc[-1]), float(cl.iloc[-2])
            rows.append({"region": region, "name": name, "symbol": t, "last": round(last, 2),
                         "change": round(last - prev, 2), "pct": round((last / prev - 1) * 100, 2),
                         "date": cl.index[-1].strftime("%d %b"), "spark": [round(float(v), 2) for v in cl.iloc[-10:]]})
        except Exception as e:
            print("Global ticker failed:", t, e)
    # US futures move since Nifty's last close: the best single clue for the next open
    since = {}
    for t in ("ES=F", "NQ=F"):
        try:
            f = _yf(t, period="5d", interval="15m")["Close"].dropna()
            idx = f.index if f.index.tz is not None else f.index.tz_localize("UTC")
            f.index = idx.tz_convert("UTC")
            ref = f[f.index <= _india_close_utc(as_of)]
            if len(ref):
                since[t] = round((float(f.iloc[-1]) / float(ref.iloc[-1]) - 1) * 100, 3)
        except Exception as e:
            print("Futures intraday failed:", t, e)
    return rows, since


def demo_global():
    rng = np.random.default_rng(int(dt.datetime.now().strftime("%H%M")))
    rows = []
    base = {"^DJI": 44000, "^GSPC": 6100, "^IXIC": 19800, "ES=F": 6120, "NQ=F": 21500, "YM=F": 44100, "^N225": 39000,
            "^HSI": 20500, "000001.SS": 3350, "^KS11": 2550, "^TWII": 22500, "^AXJO": 8300, "^FTSE": 8300, "^GDAXI": 20000,
            "^FCHI": 7400, "^STOXX50E": 5000, "BZ=F": 74, "GC=F": 2650, "DX-Y.NYB": 106.5, "INR=X": 84.4, "^TNX": 4.4, "^VIX": 16}
    for region, name, t in GLOBAL:
        spark = list(base[t] * np.exp(np.cumsum(rng.normal(0, 0.008, 10))))
        rows.append({"region": region, "name": name, "symbol": t, "last": round(spark[-1], 2),
                     "change": round(spark[-1] - spark[-2], 2), "pct": round((spark[-1] / spark[-2] - 1) * 100, 2),
                     "date": dt.date.today().strftime("%d %b"), "spark": [round(v, 2) for v in spark]})
    return rows, {"ES=F": round(float(rng.normal(0.2, 0.5)), 3), "NQ=F": round(float(rng.normal(0.3, 0.7)), 3)}


KITE = "https://api.kite.trade"


def kite_access_token():
    """Return a Kite access token from the environment. Either KITE_ACCESS_TOKEN is set
    directly, or KITE_REQUEST_TOKEN (from this morning's login) is exchanged for one
    using KITE_API_SECRET. Tokens are never printed."""
    key = os.environ.get("KITE_API_KEY", "").strip()
    if not key:
        return None, None
    tok = os.environ.get("KITE_ACCESS_TOKEN", "").strip()
    if tok:
        return key, tok
    req, secret = os.environ.get("KITE_REQUEST_TOKEN", "").strip(), os.environ.get("KITE_API_SECRET", "").strip()
    if not req or not secret:
        return key, None
    import hashlib
    import requests
    checksum = hashlib.sha256((key + req + secret).encode()).hexdigest()
    r = requests.post(KITE + "/session/token", timeout=20, headers={"X-Kite-Version": "3"},
                      data={"api_key": key, "request_token": req, "checksum": checksum}).json()
    if r.get("status") != "success":
        raise RuntimeError(f"Kite login failed: {r.get('message', 'unknown error')}")
    return key, r["data"]["access_token"]


def fetch_gift_kite(as_of=None):
    """GIFT Nifty via Zerodha Kite Connect (paid plan). Returns the current price and
    its price at 3:30 PM IST on the last Nifty session (via the historical API)."""
    key, tok = kite_access_token()
    if not key or not tok:
        return None
    import requests
    hdr = {"X-Kite-Version": "3", "Authorization": f"token {key}:{tok}"}
    sym = "NSEIX:GIFT NIFTY"
    r = requests.get(KITE + "/quote", params={"i": sym}, headers=hdr, timeout=20).json()
    if r.get("status") != "success" or sym not in r.get("data", {}):
        raise RuntimeError(f"Kite quote failed: {r.get('message', 'GIFT NIFTY not in response')}")
    q = r["data"][sym]
    out = {"price": float(q["last_price"]), "prev_close": float(q["ohlc"]["close"]),
           "time": dt.datetime.now(IST).strftime("%d %b, %I:%M %p"), "at_nifty_close": None}
    if as_of:  # GIFT Nifty's price when Nifty closed (3:30 PM IST) on the last session
        try:
            h = requests.get(f"{KITE}/instruments/historical/{q['instrument_token']}/5minute", headers=hdr, timeout=20,
                             params={"from": f"{as_of} 15:00:00", "to": f"{as_of} 15:35:00"}).json()
            candles = [c for c in h["data"]["candles"] if c[0][11:16] <= "15:25"]
            if candles:
                out["at_nifty_close"] = float(candles[-1][4])
        except Exception as e:
            print("GIFT Nifty historical lookup failed:", type(e).__name__)
    return out


NSEIX = "https://www.nseix.com"


def fetch_gift_nseix():
    """GIFT Nifty futures from NSE IX's own public website (no login needed).
    Returns the nearest-expiry (current month) Nifty futures contract, plus the last
    price of every contract so the evening run can store a same-contract reference."""
    import requests
    hdr = {"User-Agent": NSE_HEADERS["User-Agent"], "Accept": "application/json, text/plain, */*",
           "Accept-Language": "en-US,en;q=0.9", "Referer": NSEIX + "/"}
    s = requests.Session()
    s.headers.update(hdr)
    try:
        s.get(NSEIX + "/", timeout=20)
    except Exception:
        pass
    rows = s.get(NSEIX + "/api/derivatives-watch", params={"inst_type1": "IDX", "inst_type2": "STK", "type": "live"},
                 timeout=20).json()["data"]
    now = dt.datetime.now(IST)
    today = now.date()
    futs = []
    for r in rows:
        if str(r.get("INSTRUMENTTYPE")).upper() != "FUTIDX" or str(r.get("SYMBOL")).upper() != "NIFTY":
            continue
        try:
            exp = dt.datetime.strptime(r["EXPIRYDATE"], "%d-%b-%Y").date()
            last = float(r["LASTPRICE"])
        except Exception:
            continue
        # On expiry day the expiring contract stops trading in the afternoon; roll to the next one
        expired = exp < today or (exp == today and now.time() >= dt.time(15, 30))
        if last > 0 and not expired:
            futs.append({"expiry": r["EXPIRYDATE"], "last": last, "close": float(r.get("CLOSE") or 0),
                         "volume": float(r.get("VOLUME") or 0), "time": r.get("TIMESTMP", "")})
    if not futs:
        raise ValueError("No live GIFT Nifty futures in NSE IX response")
    main = min(futs, key=lambda f: dt.datetime.strptime(f["expiry"], "%d-%b-%Y"))  # current-month contract
    return {"price": main["last"], "prev_close": main["close"] or main["last"], "expiry": main["expiry"],
            "time": main["time"], "source": "NSE IX", "at_nifty_close": None,
            "contracts": {f["expiry"]: f["last"] for f in futs}}


def get_gift(demo, nifty_close=None, as_of=None):
    if demo:
        move = np.random.default_rng(int(dt.datetime.now().timestamp() * 1000) % 2**32).normal(0.002, 0.005)
        price = round(nifty_close * (1.002 + move), 1)
        return {"price": price, "prev_close": round(nifty_close * 1.002, 1), "expiry": "24-Nov-2026", "source": "NSE IX",
                "contracts": {"24-Nov-2026": price, "29-Dec-2026": round(price * 1.004, 1)}, "at_nifty_close": None,
                "time": dt.datetime.now(IST).strftime("%d %b, %I:%M %p")}
    try:  # 1. Kite, if this run was given a login (most precise: exact 3:30 PM reference)
        g = fetch_gift_kite(as_of)
        if g:
            g["source"] = "Kite"
            print("GIFT Nifty: from Kite")
            return g
    except Exception as e:
        print("GIFT Nifty via Kite failed:", e)
    try:  # 2. NSE IX public website, fully automatic
        g = fetch_gift_nseix()
        print("GIFT Nifty: from NSE IX", g["expiry"], g["price"])
        return g
    except Exception as e:
        print("GIFT Nifty via NSE IX failed:", e)
    return None


def fit_gap_model(nifty, demo=False):
    """Fit: Nifty opening gap % = a + b × (S&P 500 move % since Nifty's previous close)."""
    if demo:
        spx = nifty["Close"] * np.exp(np.random.default_rng(5).normal(0, 0.006, len(nifty)))
        spx.index = nifty.index - pd.Timedelta(days=1)
    else:
        spx = _yf("^GSPC")["Close"].dropna()
    spx.index = pd.to_datetime(spx.index).tz_localize(None) if getattr(spx.index, "tz", None) else pd.to_datetime(spx.index)
    xs, ys = [], []
    dates = nifty.index
    for i in range(1, len(dates)):
        t, tp = dates[i], dates[i - 1]
        a, b = spx[spx.index < t], spx[spx.index < tp]
        if len(a) == 0 or len(b) == 0:
            continue
        xs.append(float(a.iloc[-1] / b.iloc[-1] - 1) * 100)
        ys.append(float(nifty["Open"].iloc[i] / nifty["Close"].iloc[i - 1] - 1) * 100)
    x, y = np.array(xs), np.array(ys)
    if demo:
        y = 0.05 + 0.55 * x + np.random.default_rng(6).normal(0, 0.25, len(x))
    b, a = np.polyfit(x, y, 1)
    pred = a + b * x
    big = np.abs(y) >= GAP_FLAT
    return {"a": round(float(a), 4), "b": round(float(b), 4), "r": round(float(np.corrcoef(x, y)[0, 1]), 2),
            "direction_hit": round(float((np.sign(pred[big]) == np.sign(y[big])).mean() * 100), 1),
            "mae": round(float(np.abs(pred - y).mean()), 2), "n": int(len(x))}


def predict_gap(close, as_of, levels, model, since, gift, gift_eve):
    out = {"close": close, "for_date": next_session(dt.date.fromisoformat(as_of)).strftime("%a %d %b %Y"),
           "made_at": dt.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST"), "methods": []}
    if gift:
        eve = None
        if isinstance(gift_eve, dict):
            eve = (gift_eve.get("contracts") or {}).get(gift.get("expiry"))
        elif isinstance(gift_eve, (int, float)):
            eve = gift_eve
        ref = gift.get("at_nifty_close") or eve or gift["prev_close"]
        how = "around Nifty's close yesterday" if (gift.get("at_nifty_close") or eve) else "(its previous close)"
        pct = (gift["price"] - ref) / close * 100
        out["methods"].append({"name": "GIFT Nifty", "pct": round(pct, 2), "pts": round(close * pct / 100, 1),
                               "detail": f"GIFT Nifty {gift['price']:,.1f} now vs {ref:,.1f} {how} "
                                         f"({gift.get('source', 'GIFT')}{', ' + gift['expiry'] + ' contract' if gift.get('expiry') else ''})."})
    if model and "ES=F" in since:
        pct = model["a"] + model["b"] * since["ES=F"]
        out["methods"].append({"name": "Global cues model", "pct": round(pct, 2), "pts": round(close * pct / 100, 1),
                               "detail": f"S&P 500 futures {since['ES=F']:+.2f}% since Nifty closed. Historically Nifty gaps about "
                                         f"{model['b']:.2f}× that move (right direction {model['direction_hit']}% of the time)."})
    if not out["methods"]:
        out["status"] = "unavailable"
        return out
    main = out["methods"][0]
    out.update(status="ready", method=main["name"], pct=main["pct"], pts=main["pts"], call=gap_label(main["pct"]),
               open_est=round(close + main["pts"], 1))
    if len(out["methods"]) > 1:
        a, b = out["methods"][0]["pct"], out["methods"][1]["pct"]
        d = lambda v: 0 if abs(v) < GAP_FLAT else int(np.sign(v))
        same = d(a) == d(b)
        out["agreement"] = "Both methods agree, so confidence is higher." if same else \
            "The two methods disagree, so treat this call with extra caution."
    o, f = out["open_est"], lambda v: f"{v:,.0f}"
    if o > levels["R1"]:
        out["meaning"] = f"An open near {f(o)} would be above R1 {f(levels['R1'])}, in the call-trigger zone. Wait 15 minutes to see if it holds before buying calls."
    elif o < levels["S1"]:
        out["meaning"] = f"An open near {f(o)} would be below S1 {f(levels['S1'])}, in the put-trigger zone. Wait 15 minutes to see if it holds before buying puts."
    else:
        out["meaning"] = f"An open near {f(o)} would be inside the S1–R1 range ({f(levels['S1'])} to {f(levels['R1'])}). No trade until one side breaks."
    return out


def load_gap_track():
    if os.path.exists(GAP_TRACK):
        with open(GAP_TRACK) as f:
            return json.load(f).get("entries", [])
    return []


def save_gap_track(entries):
    with open(GAP_TRACK, "w") as f:
        json.dump({"entries": entries[-300:]}, f, indent=1)


def grade_gaps(nifty):
    """Evening run: fill in the actual opening gap for forecasts made this morning."""
    entries = load_gap_track()
    dates = [d.strftime("%Y-%m-%d") for d in nifty.index]
    for e in entries:
        if e.get("actual_pct") is None and e["date"] in dates:
            i = dates.index(e["date"])
            if i > 0:
                act = float(nifty["Open"].iloc[i] / nifty["Close"].iloc[i - 1] - 1) * 100
                e["actual_pct"], e["actual_open"] = round(act, 2), round(float(nifty["Open"].iloc[i]), 1)
                e["actual_call"] = gap_label(act)
                e["right_direction"] = bool((gap_label(act) == "Flat open" and e["call"] == "Flat open") or
                                            (np.sign(act) == np.sign(e["pct"]) and abs(act) >= GAP_FLAT and e["call"] != "Flat open"))
                e["error_pts"] = round(float(nifty["Open"].iloc[i]) - e["open_est"], 1)
    save_gap_track(entries)
    graded = [e for e in entries if e.get("actual_pct") is not None]
    summary = {"graded": len(graded),
               "hit_rate": round(sum(bool(e["right_direction"]) for e in graded) / len(graded) * 100, 1) if graded else None,
               "avg_error_pts": round(float(np.mean([abs(e["error_pts"]) for e in graded])), 1) if graded else None}
    return entries[::-1][:30], summary


def log_gap_prediction(pred):
    if pred.get("status") != "ready":
        return
    date = dt.datetime.strptime(pred["for_date"], "%a %d %b %Y").strftime("%Y-%m-%d")
    entries = [e for e in load_gap_track() if e["date"] != date]
    entries.append({"date": date, "call": pred["call"], "pct": pred["pct"], "pts": pred["pts"],
                    "open_est": pred["open_est"], "method": pred["method"], "actual_pct": None})
    entries.sort(key=lambda e: e["date"])
    save_gap_track(entries)


def get_global(demo, as_of):
    try:
        rows, since = demo_global() if demo else fetch_global(as_of)
    except Exception as e:
        print("Global markets failed:", e)
        rows, since = [], {}
    return {"rows": rows, "since_close": since, "updated": dt.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")}


def premarket(demo):
    """Morning run (~8:15 AM IST): news, global markets and the opening-gap forecast."""
    with open("data.json") as f:
        data = json.load(f)
    fresh = get_news(demo)
    if not fresh["fii_dii"] and data.get("news", {}).get("fii_dii"):
        fresh["fii_dii"] = data["news"]["fii_dii"]
    data["news"] = fresh
    data["global"] = get_global(demo, data["as_of"])
    gift = get_gift(demo, data["last"]["close"], data["as_of"])
    pm = data.get("premarket", {})
    pred = predict_gap(data["last"]["close"], data["as_of"], data["levels"], pm.get("model"),
                       data["global"]["since_close"], gift, pm.get("gift_eve"))
    pred["gift"] = gift
    log_gap_prediction(pred)
    entries = load_gap_track()
    pm.update(status=pred.get("status"), prediction=pred, history=entries[::-1][:30])
    data["premarket"] = pm
    with open("data.json", "w") as f:
        json.dump(data, f)
    print("Pre-market:", pred.get("call"), pred.get("pct"), "via", pred.get("method"))


def hourly(demo):
    """Hourly run: refresh news and global markets only. Nifty prices, signals, the track
    record and the opening-gap forecast are left alone (those come from the 4 PM full run
    and the 8:15 AM pre-market run)."""
    with open("data.json") as f:
        data = json.load(f)
    fresh = get_news(demo)
    if not fresh["fii_dii"] and data.get("news", {}).get("fii_dii"):
        fresh["fii_dii"] = data["news"]["fii_dii"]  # keep the last figures rather than none
    data["news"] = fresh
    glob = get_global(demo, data["as_of"])
    if glob["rows"] or not data.get("global"):  # keep the last good snapshot if the fetch failed
        data["global"] = glob
    with open("data.json", "w") as f:
        json.dump(data, f)
    print(f"Hourly refresh: {len(fresh['items'])} headlines, {len(glob['rows'])} global markets")


def news_only(demo):
    """Refresh just the news section of an existing data.json (used by the morning run)."""
    with open("data.json") as f:
        data = json.load(f)
    fresh = get_news(demo)
    if not fresh["fii_dii"] and data.get("news", {}).get("fii_dii"):
        fresh["fii_dii"] = data["news"]["fii_dii"]  # keep yesterday's figures rather than none
    data["news"] = fresh
    with open("data.json", "w") as f:
        json.dump(data, f)
    print(f"News refreshed: {len(fresh['items'])} headlines")


# =====================================================================
# Indicators and signal
# =====================================================================
def add_indicators(df):
    c = df["Close"]
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200).mean()
    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = 100 - 100 / (1 + gain / loss)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIG"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIG"]
    sd = c.rolling(20).std()
    df["BB_UP"], df["BB_LO"] = df["SMA20"] + 2 * sd, df["SMA20"] - 2 * sd
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - c.shift()).abs(),
                    (df["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return df


def score_row(r, prev_hist, vix=None, vix_prev=None, oc=None):
    """Score > 0 bullish, < 0 bearish. Returns (score, reasons)."""
    s, why = 0.0, []

    def add(pts, text):
        nonlocal s
        s += pts
        why.append(text)

    add(1 if r.Close > r.SMA50 else -1,
        "Close above 50-day average (uptrend)" if r.Close > r.SMA50 else "Close below 50-day average (downtrend)")
    add(1 if r.SMA20 > r.SMA50 else -1,
        "20-DMA above 50-DMA" if r.SMA20 > r.SMA50 else "20-DMA below 50-DMA")
    add(1 if r.MACD_HIST > 0 else -1,
        "MACD above signal line" if r.MACD_HIST > 0 else "MACD below signal line")
    add(.5 if r.MACD_HIST > prev_hist else -.5,
        "MACD histogram rising" if r.MACD_HIST > prev_hist else "MACD histogram falling")
    if r.RSI > 60:
        add(1, f"RSI {r.RSI:.0f}: bullish zone")
    elif r.RSI < 40:
        add(-1, f"RSI {r.RSI:.0f}: bearish zone")
    else:
        why.append(f"RSI {r.RSI:.0f}: neutral")
    if r.RSI > 70:
        why.append("⚠ RSI overbought: pullback risk")
    if r.RSI < 30:
        why.append("⚠ RSI oversold: bounce risk")

    # Option chain: high PCR = heavy put writing (support), low PCR = heavy call writing
    if oc and not oc.get("stale"):
        p = oc["pcr"]
        if p >= 1.3:
            add(.5, f"PCR {p}: strong put writing (supportive)")
        elif p <= 0.7:
            add(-.5, f"PCR {p}: strong call writing (resistive)")
        else:
            why.append(f"PCR {p}: balanced")
        if r.Close >= oc["max_ce_oi_strike"]:
            why.append(f"Price at/above biggest call-OI strike {oc['max_ce_oi_strike']}")
        if r.Close <= oc["max_pe_oi_strike"]:
            why.append(f"Price at/below biggest put-OI strike {oc['max_pe_oi_strike']}")

    # VIX: does not give direction, but changes how risky option buying is
    if vix is not None:
        if vix_prev and vix > vix_prev * 1.08:
            add(-.5, f"India VIX jumped to {vix:.1f}: fear rising")
        elif vix_prev and vix < vix_prev * 0.92:
            add(.5, f"India VIX fell to {vix:.1f}: fear easing")
        if vix >= 20:
            why.append(f"⚠ VIX {vix:.1f} is high: premiums expensive, use smaller size")
        elif vix <= 12:
            why.append(f"VIX {vix:.1f} is low: premiums cheap, but moves may be small")
    return s, why


def bias_from(score):
    if score >= 2.5:
        return "CALL"
    if score <= -2.5:
        return "PUT"
    return "NONE"


BIAS_LABEL = {"CALL": "CALL (CE) bias", "PUT": "PUT (PE) bias", "NONE": "NO TRADE / neutral"}


def pivots(h, l, c):
    p = (h + l + c) / 3
    return {"R2": p + (h - l), "R1": 2 * p - l, "Pivot": p, "S1": 2 * p - h, "S2": p - (h - l)}


def make_plan(bias, lv, close):
    atm = int(round(close / STRIKE_STEP) * STRIKE_STEP)
    if bias == "CALL":
        return {"instrument": f"NIFTY {atm} CE (ATM)", "trigger": f"Only if Nifty trades above R1 {lv['R1']:.0f}",
                "target": f"R2 {lv['R2']:.0f}", "stop": f"Exit if Nifty falls below Pivot {lv['Pivot']:.0f}"}
    if bias == "PUT":
        return {"instrument": f"NIFTY {atm} PE (ATM)", "trigger": f"Only if Nifty trades below S1 {lv['S1']:.0f}",
                "target": f"S2 {lv['S2']:.0f}", "stop": f"Exit if Nifty rises above Pivot {lv['Pivot']:.0f}"}
    return {"instrument": "None", "trigger": f"Wait for a break above R1 {lv['R1']:.0f} or below S1 {lv['S1']:.0f}",
            "target": "-", "stop": "-"}


def backtest(df):
    hp = df["MACD_HIST"].shift()
    scores = [score_row(r, h)[0] for r, h in zip(df.itertuples(), hp)]
    df = df.assign(score=scores)
    df["ret1"] = df["Close"].shift(-1) / df["Close"] - 1
    df["ret5"] = df["Close"].shift(-5) / df["Close"] - 1
    out = {}
    for name, mask, sign in [("call", df.score >= 2.5, 1), ("put", df.score <= -2.5, -1)]:
        sub = df[mask].dropna(subset=["ret5"])
        n = len(sub)
        out[name] = {"signals": n,
                     "hit_1d": round(float((np.sign(sub.ret1) == sign).mean() * 100), 1) if n else None,
                     "hit_5d": round(float((np.sign(sub.ret5) == sign).mean() * 100), 1) if n else None}
    out["base_up_days_pct"] = round(float((df.ret1.dropna() > 0).mean() * 100), 1)
    out["note"] = "Technical rules only (no historical option-chain data)"
    return out, df["score"]


# =====================================================================
# Signal tracking
# =====================================================================
def make_entry(date, row, prev_hist, vix=None, vix_prev=None, oc=None, backfilled=False):
    score, _ = score_row(row, prev_hist, vix, vix_prev, oc)
    bias = bias_from(score)
    lv = {k: round(float(v), 1) for k, v in pivots(row.High, row.Low, row.Close).items()}
    return {"date": date, "bias": bias, "score": score, "close": round(float(row.Close), 2),
            "levels": lv, "vix": None if vix is None else round(float(vix), 2),
            "pcr": oc["pcr"] if oc and not oc.get("stale") else None,
            "backfilled": backfilled, "outcome": None}


def grade(entry, nxt):
    """Grade a signal against the next session's OHLC (a 1-day plan).
    Daily bars don't show which level was touched first, so if the stop and
    target were both hit we count it as a loss (the cautious assumption)."""
    lv, b = entry["levels"], entry["bias"]
    o = {"next_date": nxt["date"], "next_close": round(nxt["Close"], 2),
         "move": round(nxt["Close"] - entry["close"], 2)}
    if b == "CALL":
        entry_px, tgt, stop = lv["R1"], lv["R2"], lv["Pivot"]
        if nxt["High"] < entry_px:
            o.update(result="Not triggered", points=0.0)
        elif nxt["Low"] <= stop:
            o.update(result="Stopped out", points=round(stop - entry_px, 1))
        elif nxt["High"] >= tgt:
            o.update(result="Target hit", points=round(tgt - entry_px, 1))
        else:
            o.update(result="Closed at day end", points=round(nxt["Close"] - entry_px, 1))
        o["direction_ok"] = nxt["Close"] > entry["close"]
    elif b == "PUT":
        entry_px, tgt, stop = lv["S1"], lv["S2"], lv["Pivot"]
        if nxt["Low"] > entry_px:
            o.update(result="Not triggered", points=0.0)
        elif nxt["High"] >= stop:
            o.update(result="Stopped out", points=round(entry_px - stop, 1))
        elif nxt["Low"] <= tgt:
            o.update(result="Target hit", points=round(entry_px - tgt, 1))
        else:
            o.update(result="Closed at day end", points=round(entry_px - nxt["Close"], 1))
        o["direction_ok"] = nxt["Close"] < entry["close"]
    else:
        up, dn = nxt["High"] > lv["R1"], nxt["Low"] < lv["S1"]
        o["result"] = ("Broke both sides" if up and dn else "Broke above R1" if up
                       else "Broke below S1" if dn else "Stayed in range")
        o["points"], o["direction_ok"] = None, (not up and not dn)
    return o


def summarize_track(entries):
    def stats(es):
        trades = [e for e in es if e["outcome"] and e["bias"] != "NONE"]
        trig = [e for e in trades if e["outcome"]["result"] != "Not triggered"]
        wins = [e for e in trig if e["outcome"]["points"] > 0]
        nt = [e for e in es if e["outcome"] and e["bias"] == "NONE"]
        return {"signals": len(trades), "triggered": len(trig),
                "win_rate": round(len(wins) / len(trig) * 100, 1) if trig else None,
                "direction_ok": round(sum(e["outcome"]["direction_ok"] for e in trades) / len(trades) * 100, 1) if trades else None,
                "total_points": round(sum(e["outcome"]["points"] for e in trig), 1),
                "no_trade_days": len(nt),
                "no_trade_correct": round(sum(e["outcome"]["direction_ok"] for e in nt) / len(nt) * 100, 1) if nt else None}
    return {"all": stats(entries), "live": stats([e for e in entries if not e["backfilled"]])}


def update_track(df, vix_s, today_entry):
    track = []
    if os.path.exists(TRACK_FILE):
        with open(TRACK_FILE) as f:
            track = json.load(f).get("entries", [])

    if not track:  # first run: backfill recent history so the table isn't empty
        hp = df["MACD_HIST"].shift()
        for i in range(max(1, len(df) - 1 - BACKFILL_DAYS), len(df) - 1):
            d = df.index[i]
            v = vix_s.get(d) if len(vix_s) else None
            vp = vix_s.get(df.index[i - 1]) if len(vix_s) else None
            track.append(make_entry(d.strftime("%Y-%m-%d"), df.iloc[i], hp.iloc[i],
                                    v, vp, None, backfilled=True))

    track = [e for e in track if e["date"] != today_entry["date"]] + [today_entry]
    track.sort(key=lambda e: e["date"])

    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    pos = {d: i for i, d in enumerate(dates)}
    for e in track:
        if e["outcome"] is None and e["date"] in pos and pos[e["date"]] + 1 < len(df):
            j = pos[e["date"]] + 1
            r = df.iloc[j]
            e["outcome"] = grade(e, {"date": dates[j], "High": float(r.High),
                                     "Low": float(r.Low), "Close": float(r.Close)})
    track = track[-500:]
    with open(TRACK_FILE, "w") as f:
        json.dump({"entries": track}, f, indent=1)
    return track


# =====================================================================
# Playbook: levels to watch and what to do at each
# =====================================================================
def next_session(as_of):
    d = as_of + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d  # NSE holidays are not accounted for


def build_playbook(last, lv, oc, vix, bias):
    close = float(last.Close)
    pts = lambda v: f"{v:,.0f}"
    watch = [
        ("R2", lv["R2"], "Call target and strong resistance. Book profits on calls here."),
        ("R1", lv["R1"], "Call trigger. A 15-minute close above this starts the CE plan."
                         if bias == "CALL" else "First resistance. Rallies often stall here."),
        ("Pivot", lv["Pivot"], "Stop-loss line for both plans. Above it buyers control the day, below it sellers do."),
        ("S1", lv["S1"], "Put trigger. A 15-minute close below this starts the PE plan."
                         if bias == "PUT" else "First support. Dips often find buyers here."),
        ("S2", lv["S2"], "Put target and strong support. Book profits on puts here."),
        ("Last session high", float(last.High), "A break above often brings follow-through buying."),
        ("Last session low", float(last.Low), "A break below often brings follow-through selling."),
    ]
    for name, col, why in [("20-day average", "SMA20", "Short-term trend line."),
                           ("50-day average", "SMA50", "Medium-term trend line. Closing above or below it shifts the bias."),
                           ("200-day average", "SMA200", "Long-term trend line that large funds watch.")]:
        if not pd.isna(last[col]):
            watch.append((name, float(last[col]), why))
    if oc and not oc.get("stale"):
        watch += [
            ("Call-OI wall", oc["max_ce_oi_strike"], "Most call writers sit here. It tends to cap rallies; a clean break can trigger a fast short-covering move."),
            ("Put-OI wall", oc["max_pe_oi_strike"], "Most put writers sit here. It tends to hold dips; a break can speed up a fall."),
            ("Max pain", oc["max_pain"], f"Where option buyers lose the most at expiry ({oc['expiry']}). Nifty often drifts toward it close to expiry."),
        ]
    watch = sorted(({"name": n, "value": round(float(v), 1), "dist": round(float(v) - close, 1),
                     "dist_pct": round((float(v) / close - 1) * 100, 2), "why": w} for n, v, w in watch),
                   key=lambda x: -x["value"])

    gap = close * 0.005
    sc = [
        {"kind": "call", "when": f"Nifty closes a 15-minute candle above R1 {pts(lv['R1'])}",
         "then": f"Buy an ATM call. Target R2 {pts(lv['R2'])}, exit if Nifty falls back below the pivot {pts(lv['Pivot'])}."
                 + ("" if bias == "CALL" else " This goes against today's bias, so trade smaller or skip it.")},
        {"kind": "put", "when": f"Nifty closes a 15-minute candle below S1 {pts(lv['S1'])}",
         "then": f"Buy an ATM put. Target S2 {pts(lv['S2'])}, exit if Nifty climbs back above the pivot {pts(lv['Pivot'])}."
                 + ("" if bias == "PUT" else " This goes against today's bias, so trade smaller or skip it.")},
        {"kind": "wait", "when": f"Nifty stays between S1 {pts(lv['S1'])} and R1 {pts(lv['R1'])}",
         "then": "Don't buy options. Premiums lose value every hour in a sideways market."},
        {"kind": "wait", "when": f"Nifty opens more than {pts(gap)} points (0.5%) away from {pts(close)}",
         "then": "Wait 15 to 30 minutes. Big gaps often partly fill. Enter only if price holds beyond the first 15-minute high (gap up) or low (gap down)."},
    ]
    if oc and not oc.get("stale"):
        for name, k in [("call-OI wall", oc["max_ce_oi_strike"]), ("put-OI wall", oc["max_pe_oi_strike"])]:
            if abs(k - close) / close < 0.005:
                sc.append({"kind": "wait", "when": f"Price is within 0.5% of the {name} {pts(k)}",
                           "then": "Expect a fight at this level. Wait for a clear 15-minute close through it before trading the breakout."})
        try:
            exp = dt.datetime.strptime(oc["expiry"], "%d-%b-%Y").date()
            if exp == next_session(as_of=pd.Timestamp(last.name).date()):
                sc.append({"kind": "wait", "when": "Next session is expiry day",
                           "then": "Premiums decay very fast after noon. Avoid holding bought options into the last two hours."})
        except Exception:
            pass
    if vix is not None and vix >= 20:
        sc.append({"kind": "wait", "when": f"India VIX is high at {vix:.1f}",
                   "then": "Premiums are expensive. Use smaller size or spreads instead of plain option buying."})

    line = {"CALL": f"Leaning bullish. Watch R1 {pts(lv['R1'])}: the call plan starts above it.",
            "PUT": f"Leaning bearish. Watch S1 {pts(lv['S1'])}: the put plan starts below it.",
            "NONE": f"No clear edge. Stay flat unless Nifty breaks R1 {pts(lv['R1'])} or S1 {pts(lv['S1'])}."}[bias]
    return {"headline": line, "pivot": round(float(lv["Pivot"]), 1), "close": round(close, 1),
            "session": next_session(pd.Timestamp(last.name).date()).strftime("%a %d %b %Y"),
            "watch": watch, "scenarios": sc}


# =====================================================================
# Market alerts: breakouts, crossovers, gaps and other notable events
# =====================================================================
def build_alerts(df, oc, vix, vix_prev, bias, lv):
    A = []
    r, p = df.iloc[-1], df.iloc[-2]
    c = float(r.Close)
    f = lambda v: f"{v:,.0f}"

    def add(sev, kind, title, detail, levels=()):
        A.append({"severity": sev, "kind": kind, "title": title, "detail": detail,
                  "levels": [round(float(x), 0) for x in levels]})

    lean = {"CALL": " The trend signals currently favour an upside break.",
            "PUT": " The trend signals currently favour a downside break.",
            "NONE": " The trend signals don't favour either side yet."}[bias]

    # 1. Tight range / volatility squeeze -> breakout expected
    win = df.iloc[-10:]
    hi10, lo10 = float(win.High.max()), float(win.Low.min())
    rng_pct = (hi10 - lo10) / c * 100
    bbw = ((df.BB_UP - df.BB_LO) / df.SMA20).dropna()
    squeeze = (bbw.iloc[-126:] < bbw.iloc[-1]).mean() if len(bbw) > 20 else 1
    still_inside = float(df.Low.iloc[-10:-1].min()) <= c <= float(df.High.iloc[-10:-1].max())
    if (squeeze <= 0.15 or rng_pct < 2.5) and still_inside:
        add("high", "Breakout watch", f"Breakout expected: Nifty is stuck between {f(lo10)} and {f(hi10)}",
            f"The last 10 sessions moved within just {rng_pct:.1f}%, and Bollinger Bands are narrower than on "
            f"{100 - squeeze * 100:.0f}% of days in the last 6 months. Tight ranges usually end in a sharp move. "
            f"A daily close above {f(hi10)} signals an upside breakout; a close below {f(lo10)} signals a breakdown." + lean,
            (lo10, hi10))

    # 2. 20-day and 52-week highs / lows
    h20, l20 = float(df.High.iloc[-21:-1].max()), float(df.Low.iloc[-21:-1].min())
    if r.High > h20:
        add("high", "Breakout", f"Broke above the 20-day high of {f(h20)}",
            f"Holding above {f(h20)} keeps the breakout alive, with R2 {f(lv['R2'])} next. "
            f"Falling back below it would make this a false breakout.", (h20,))
    elif c >= h20 * 0.995:
        add("medium", "Breakout watch", f"Testing the 20-day high of {f(h20)}",
            f"Nifty closed {f(h20 - c)} points below it. A close above {f(h20)} could open a breakout move.", (h20,))
    if r.Low < l20:
        add("high", "Breakdown", f"Broke below the 20-day low of {f(l20)}",
            f"Staying below {f(l20)} keeps sellers in control, with S2 {f(lv['S2'])} next. "
            f"A quick recovery above it would make this a false breakdown.", (l20,))
    elif c <= l20 * 1.005:
        add("medium", "Breakdown watch", f"Testing the 20-day low of {f(l20)}",
            f"Nifty closed {f(c - l20)} points above it. A close below {f(l20)} could start a breakdown.", (l20,))
    if len(df) > 253:
        h52, l52 = float(df.High.iloc[-253:-1].max()), float(df.Low.iloc[-253:-1].min())
        if r.High > h52:
            add("high", "Breakout", f"New 52-week high above {f(h52)}", "A strong sign of momentum. Pullbacks toward the old high often find buyers.", (h52,))
        elif c >= h52 * 0.98:
            add("medium", "Breakout watch", f"Within 2% of the 52-week high of {f(h52)}", f"A move above {f(h52)} would be a major breakout.", (h52,))
        if r.Low < l52:
            add("high", "Breakdown", f"New 52-week low below {f(l52)}", "A sign of strong selling pressure. Avoid buying calls against this trend.", (l52,))

    # 3. Crossovers in the last 3 sessions
    def cross(a, b, n=3):
        sgn = np.sign((df[a] - df[b]).iloc[-n - 1:]).dropna()
        if len(sgn) < 2 or (sgn == sgn.iloc[-1]).all():
            return 0
        return int(sgn.iloc[-1])
    if not pd.isna(r.SMA200):
        x = cross("SMA50", "SMA200")
        if x:
            add("high", "Trend change", "Golden cross: 50-day average crossed above the 200-day" if x > 0
                else "Death cross: 50-day average crossed below the 200-day",
                "A long-term trend signal that many funds follow. It often marks a shift that lasts weeks or months.",
                (r.SMA200,))
    x = cross("SMA20", "SMA50")
    if x:
        add("medium", "Trend change", f"20-day average crossed {'above' if x > 0 else 'below'} the 50-day",
            f"Short-term momentum has turned {'up' if x > 0 else 'down'}.", (r.SMA50,))
    x = cross("MACD", "MACD_SIG", 1)
    if x:
        add("medium", "Momentum", f"MACD crossed {'above' if x > 0 else 'below'} its signal line today",
            f"An early sign that momentum is turning {'bullish' if x > 0 else 'bearish'}.")
    if p.RSI <= 70 < r.RSI:
        add("medium", "Momentum", f"RSI moved into overbought territory ({r.RSI:.0f})", "The rally is stretched. Expect pullbacks or sideways moves before the next leg up.")
    if p.RSI >= 30 > r.RSI:
        add("medium", "Momentum", f"RSI moved into oversold territory ({r.RSI:.0f})", "The fall is stretched. Sharp relief bounces are common from here.")

    # 4. Gaps, big moves and inside days
    gap = float(r.Open - p.Close)
    if abs(gap) / p.Close > 0.005:
        filled = (r.Low <= p.Close) if gap > 0 else (r.High >= p.Close)
        add("info", "Gap", f"Gap {'up' if gap > 0 else 'down'} of {f(abs(gap))} points at the open",
            f"The gap zone is {f(min(p.Close, r.Open))} to {f(max(p.Close, r.Open))}. "
            + ("It has already been filled." if filled else f"It is still open, so {f(p.Close)} may act as a magnet or as {'support' if gap > 0 else 'resistance'}."),
            (p.Close,))
    move = c - float(p.Close)
    if abs(move) > 1.5 * float(p.ATR):
        add("high", "Big move", f"Unusually large move of {'+' if move > 0 else '−'}{f(abs(move))} points",
            f"That's {abs(move) / p.ATR:.1f} times the normal daily range. Big days are often followed by more volatility, so expect wider swings.")
    if r.High < p.High and r.Low > p.Low:
        add("medium", "Breakout watch", f"Inside day: the next breakout level is {f(p.High)} or {f(p.Low)}",
            f"Today's range sat inside yesterday's, which shows indecision. A move beyond {f(p.High)} or {f(p.Low)} often sets the next direction.",
            (p.Low, p.High))

    # 5. Volatility
    if vix is not None and vix_prev:
        ch = (vix / vix_prev - 1) * 100
        if ch >= 10:
            add("high", "Volatility", f"India VIX spiked {ch:.0f}% to {vix:.1f}", "Fear is rising fast. Option premiums jump with VIX, so bought options cost more and swings get bigger.")
        elif ch <= -10:
            add("medium", "Volatility", f"India VIX dropped {abs(ch):.0f}% to {vix:.1f}", "Fear is easing. Premiums are shrinking, which hurts option buyers who hold overnight.")

    # 6. Option-chain walls nearby
    if oc and not oc.get("stale"):
        cw, pw = oc["max_ce_oi_strike"], oc["max_pe_oi_strike"]
        if 0 <= cw - c <= c * 0.006:
            add("medium", "Breakout watch", f"Call-OI wall at {f(cw)} is just {f(cw - c)} points above",
                f"Call writers will defend {f(cw)}. If Nifty closes above it, they may rush to cover, which can cause a fast rally.", (cw,))
        if 0 <= c - pw <= c * 0.006:
            add("medium", "Breakdown watch", f"Put-OI wall at {f(pw)} is just {f(c - pw)} points below",
                f"Put writers will defend {f(pw)}. If Nifty closes below it, the fall can speed up.", (pw,))

    order = {"high": 0, "medium": 1, "info": 2}
    A.sort(key=lambda a: order[a["severity"]])
    if not A:
        add("info", "Quiet", "No major setups today", f"Nifty is trading normally. Stick to the levels plan: R1 {f(lv['R1'])} above, S1 {f(lv['S1'])} below.")
    return A


# =====================================================================
# Technical analysis: candles, chart patterns, trendlines, S/R zones,
# Fibonacci, divergences. Feeds the AI analysis section.
# =====================================================================
ANALYSIS_TRACK = "analysis_track.json"
AI_MODEL = "claude-opus-5-5"


def swing_points(df, w):
    """Confirmed swing highs/lows: the bar's high (low) is the extreme of the w bars on either side.
    The last w bars can't be confirmed yet, so they never count."""
    hi, lo = df["High"].values, df["Low"].values
    H, L = [], []
    for i in range(w, len(df) - w):
        if hi[i] == hi[i - w:i + w + 1].max() and not (H and i - H[-1] <= w):
            H.append(i)
        if lo[i] == lo[i - w:i + w + 1].min() and not (L and i - L[-1] <= w):
            L.append(i)
    return H, L


def adx(df, n=14):
    up, dn = df["High"].diff(), -df["Low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def candle_patterns(df):
    """Candlestick patterns on the last session (and the two before it for 3-candle patterns)."""
    o, h, l, c = (df[k].values for k in ("Open", "High", "Low", "Close"))
    atr = float(df["ATR"].iloc[-1])
    i = len(df) - 1
    date = df.index[i].strftime("%Y-%m-%d")
    body = lambda k: abs(c[k] - o[k])
    rng = lambda k: max(h[k] - l[k], 1e-9)
    upper = lambda k: h[k] - max(o[k], c[k])
    lower = lambda k: min(o[k], c[k]) - l[k]
    bull = lambda k: c[k] > o[k]
    prior = c[i - 1] - c[i - 6]  # direction of the five sessions before today
    out = []

    def add(name, bias, detail):
        out.append({"name": name, "bias": bias, "date": date, "detail": detail})

    if bull(i) and not bull(i - 1) and c[i] >= o[i - 1] and o[i] <= c[i - 1] and body(i) > body(i - 1):
        add("Bullish engulfing", "bullish", "Today's up candle swallowed yesterday's down candle: buyers took back control.")
    elif not bull(i) and bull(i - 1) and o[i] >= c[i - 1] and c[i] <= o[i - 1] and body(i) > body(i - 1):
        add("Bearish engulfing", "bearish", "Today's down candle swallowed yesterday's up candle: sellers took back control.")
    if (not bull(i - 2) and body(i - 2) > 0.6 * rng(i - 2) and body(i - 1) < 0.3 * body(i - 2)
            and bull(i) and c[i] > (o[i - 2] + c[i - 2]) / 2):
        add("Morning star", "bullish", "A big down day, a small pause, then a strong up day: a classic bottoming sign.")
    if (bull(i - 2) and body(i - 2) > 0.6 * rng(i - 2) and body(i - 1) < 0.3 * body(i - 2)
            and not bull(i) and c[i] < (o[i - 2] + c[i - 2]) / 2):
        add("Evening star", "bearish", "A big up day, a small pause, then a strong down day: a classic topping sign.")
    if all(bull(k) and body(k) > 0.5 * rng(k) for k in (i - 2, i - 1, i)) and c[i] > c[i - 1] > c[i - 2]:
        add("Three white soldiers", "bullish", "Three strong up days in a row, each closing higher: steady buying.")
    if all(not bull(k) and body(k) > 0.5 * rng(k) for k in (i - 2, i - 1, i)) and c[i] < c[i - 1] < c[i - 2]:
        add("Three black crows", "bearish", "Three strong down days in a row, each closing lower: steady selling.")

    if body(i) >= 0.05 * rng(i) and lower(i) >= 2 * body(i) and upper(i) <= 0.3 * rng(i):
        if prior < 0:
            add("Hammer", "bullish", "After a fall, sellers pushed it down but buyers closed it near the high. A bounce often follows if the next day closes higher.")
        elif prior > 0:
            add("Hanging man", "bearish", "After a rise, a long lower shadow shows sellers testing the market. A lower close next day would confirm weakness.")
    elif body(i) >= 0.05 * rng(i) and upper(i) >= 2 * body(i) and lower(i) <= 0.3 * rng(i):
        if prior > 0:
            add("Shooting star", "bearish", "After a rise, buyers pushed it up but it closed near the low: rallies are being sold.")
        elif prior < 0:
            add("Inverted hammer", "bullish", "After a fall, buyers tried to push it up. Needs a higher close next day to confirm.")
    elif body(i) <= 0.1 * rng(i):
        add("Doji", "neutral", "Open and close almost equal: indecision. "
            + ("After a rise, it can warn of a pause or top." if prior > 0 else "After a fall, it can warn of a pause or bottom." if prior < 0 else ""))
    if body(i) >= 0.85 * rng(i) and rng(i) > 0.8 * atr:
        add("Bullish marubozu" if bull(i) else "Bearish marubozu", "bullish" if bull(i) else "bearish",
            f"A full-bodied {'up' if bull(i) else 'down'} candle with almost no shadows: one side was in control all day.")
    return out


def _line(idx, vals):
    """Least-squares line through swing points -> (slope per bar, intercept)."""
    if len(idx) < 2:
        return None
    m, b = np.polyfit(np.array(idx, float), np.array(vals, float), 1)
    return float(m), float(b)


def chart_patterns(df, H, L):
    hi, lo, cl = df["High"].values, df["Low"].values, df["Close"].values
    n, c = len(df), float(cl[-1])
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    out, lines = [], {}
    rH = [i for i in H if i >= n - 120]
    rL = [i for i in L if i >= n - 120]

    def add(name, bias, status, detail, level=None, target=None, points=()):
        # Skip patterns that have already played out (target reached) or are far from today's price
        if target is not None and ((bias == "bullish" and c >= target) or (bias == "bearish" and c <= target)):
            return
        if level is not None and abs(c / level - 1) > 0.05:
            return
        out.append({"name": name, "bias": bias, "status": status, "detail": detail,
                    "level": None if level is None else round(float(level), 1),
                    "target": None if target is None else round(float(target), 1),
                    "points": [{"date": dates[k], "price": round(float(v), 1)} for k, v in points]})

    # Double top / bottom: two similar peaks (troughs) at least 8 sessions apart
    if len(rH) >= 2:
        a, b = rH[-2], rH[-1]
        top, neck = max(hi[a], hi[b]), lo[a:b + 1].min()
        if b - a >= 8 and abs(hi[a] - hi[b]) / top < 0.015 and n - 1 - b <= 30 \
                and (top - neck) / neck >= 0.025 and c < top * 1.005:
            done = c < neck
            add("Double top", "bearish", "confirmed" if done else "forming",
                f"Two peaks near {top:,.0f} with a neckline at {neck:,.0f}. "
                + ("Price has closed below the neckline, which confirms it." if done else
                   f"A daily close below {neck:,.0f} would confirm it; until then it's only a warning."),
                neck, neck - (top - neck), [(a, hi[a]), (b, hi[b])])
    if len(rL) >= 2:
        a, b = rL[-2], rL[-1]
        bot, neck = min(lo[a], lo[b]), hi[a:b + 1].max()
        if b - a >= 8 and abs(lo[a] - lo[b]) / bot < 0.015 and n - 1 - b <= 30 \
                and (neck - bot) / bot >= 0.025 and c > bot * 0.995:
            done = c > neck
            add("Double bottom", "bullish", "confirmed" if done else "forming",
                f"Two troughs near {bot:,.0f} with a neckline at {neck:,.0f}. "
                + ("Price has closed above the neckline, which confirms it." if done else
                   f"A daily close above {neck:,.0f} would confirm it."),
                neck, neck + (neck - bot), [(a, lo[a]), (b, lo[b])])

    # Head and shoulders (and inverse): three peaks, the middle one highest
    if len(rH) >= 3:
        l_, m_, r_ = rH[-3:]
        if hi[m_] > max(hi[l_], hi[r_]) * 1.02 and abs(hi[l_] - hi[r_]) / hi[m_] < 0.03 and n - 1 - r_ <= 30:
            neck = (lo[l_:m_ + 1].min() + lo[m_:r_ + 1].min()) / 2
            if c < hi[m_]:
                done = c < neck
                add("Head and shoulders", "bearish", "confirmed" if done else "forming",
                    f"Peaks at {hi[l_]:,.0f}, {hi[m_]:,.0f} (head) and {hi[r_]:,.0f}; neckline about {neck:,.0f}. "
                    + ("Price is below the neckline: a major topping pattern is in play." if done else
                       f"A close below {neck:,.0f} would complete this topping pattern."),
                    neck, neck - (hi[m_] - neck), [(l_, hi[l_]), (m_, hi[m_]), (r_, hi[r_])])
    if len(rL) >= 3:
        l_, m_, r_ = rL[-3:]
        if lo[m_] < min(lo[l_], lo[r_]) * 0.98 and abs(lo[l_] - lo[r_]) / lo[m_] < 0.03 and n - 1 - r_ <= 30:
            neck = (hi[l_:m_ + 1].max() + hi[m_:r_ + 1].max()) / 2
            if c > lo[m_]:
                done = c > neck
                add("Inverse head and shoulders", "bullish", "confirmed" if done else "forming",
                    f"Troughs at {lo[l_]:,.0f}, {lo[m_]:,.0f} (head) and {lo[r_]:,.0f}; neckline about {neck:,.0f}. "
                    + ("Price is above the neckline: a major bottoming pattern is in play." if done else
                       f"A close above {neck:,.0f} would complete this bottoming pattern."),
                    neck, neck + (neck - lo[m_]), [(l_, lo[l_]), (m_, lo[m_]), (r_, lo[r_])])

    # Trendlines through the last 3 swing highs / lows of the past 60 sessions, and the shape they make
    tH = [i for i in H if i >= n - 60][-3:]
    tL = [i for i in L if i >= n - 60][-3:]
    lh, ll = _line(tH, hi[tH]), _line(tL, lo[tL])
    # A line that has drifted more than 5% from price no longer matters for the next session
    near = lambda ln: ln and abs((ln[0] * n + ln[1]) / c - 1) <= 0.05
    lh, ll = (lh if near(lh) else None), (ll if near(ll) else None)
    for key, ln, idx in [("resistance", lh, tH), ("support", ll, tL)]:
        if ln:
            m, b = ln
            lines[key] = {"from": {"date": dates[idx[0]], "price": round(m * idx[0] + b, 1)},
                          "to": {"date": dates[-1], "price": round(m * (n - 1) + b, 1)},
                          "today": round(m * (n - 1) + b, 1), "next": round(m * n + b, 1),
                          "slope_pct": round(m / c * 100 * 20, 2)}  # % per 20 sessions
    if lh and ll:
        sh, sl = lh[0] / c * 100, ll[0] / c * 100  # % per session
        up_line, lo_line = lines["resistance"]["next"], lines["support"]["next"]
        flat = 0.025
        shape = None
        if abs(sh) < flat and sl > flat:
            shape = ("Ascending triangle", "bullish", "Flat highs with rising lows: buyers keep stepping in higher. Usually breaks upward.")
        elif sh < -flat and abs(sl) < flat:
            shape = ("Descending triangle", "bearish", "Falling highs with flat lows: sellers keep pressing. Usually breaks downward.")
        elif sh < -flat and sl > flat:
            shape = ("Symmetrical triangle", "neutral", "Highs falling and lows rising: the range is squeezing. The break direction sets the next move.")
        elif sh > flat and sl > flat:
            shape = (("Rising wedge", "bearish", "Both lines rising but the lows climb faster: the rally is losing room. Often breaks down.")
                     if sl > sh * 1.3 else
                     ("Rising channel", "bullish", "Higher highs and higher lows inside parallel lines: an orderly uptrend."))
        elif sh < -flat and sl < -flat:
            shape = (("Falling wedge", "bullish", "Both lines falling but the highs drop faster: selling is running out. Often breaks up.")
                     if sh < sl * 1.3 else
                     ("Falling channel", "bearish", "Lower highs and lower lows inside parallel lines: an orderly downtrend."))
        if shape and up_line > lo_line:
            status = "broken up" if c > up_line * 1.003 else "broken down" if c < lo_line * 0.997 else "forming"
            add(shape[0], shape[1], status,
                shape[2] + f" Upper line next session about {up_line:,.0f}, lower line about {lo_line:,.0f}.",
                up_line if shape[1] != "bearish" else lo_line)
    return out, lines


def sr_zones(df, H, L, c, atr):
    """Group swing highs and lows of the last year that sit close together into price zones."""
    n = len(df)
    pts = sorted([(float(df["High"].iloc[i]), i) for i in H if i >= n - 250] +
                 [(float(df["Low"].iloc[i]), i) for i in L if i >= n - 250])
    tol = max(0.006 * c, 0.5 * atr)
    groups, cur = [], []
    for p in pts:
        if cur and p[0] - cur[0][0] > tol:
            groups.append(cur)
            cur = []
        cur.append(p)
    if cur:
        groups.append(cur)
    zones = []
    for g in groups:
        if len(g) < 2:
            continue
        lvl = float(np.mean([p for p, _ in g]))
        last = max(i for _, i in g)
        zones.append({"level": round(lvl, 1), "low": round(min(p for p, _ in g), 1), "high": round(max(p for p, _ in g), 1),
                      "touches": len(g), "last_touch": df.index[last].strftime("%Y-%m-%d"),
                      "side": "resistance" if lvl > c else "support",
                      "strength": round(len(g) + (1 if last >= n - 60 else 0), 1)})
    above = sorted([z for z in zones if z["side"] == "resistance"], key=lambda z: z["level"])[:3]
    below = sorted([z for z in zones if z["side"] == "support"], key=lambda z: -z["level"])[:3]
    return sorted(above + below, key=lambda z: -z["level"])


def fib_levels(df):
    w = df.iloc[-120:]
    ih, il = int(np.argmax(w["High"].values)), int(np.argmin(w["Low"].values))
    hi, lo = float(w["High"].iloc[ih]), float(w["Low"].iloc[il])
    up = il < ih  # swing went low -> high, so retracements are supports below the high
    lv = {f"{r * 100:g}%": round(hi - r * (hi - lo), 1) if up else round(lo + r * (hi - lo), 1)
          for r in (0.236, 0.382, 0.5, 0.618, 0.786)}
    return {"direction": "up" if up else "down", "swing_high": round(hi, 1), "swing_low": round(lo, 1),
            "high_date": w.index[ih].strftime("%Y-%m-%d"), "low_date": w.index[il].strftime("%Y-%m-%d"), "levels": lv}


def divergence(df):
    H, L = swing_points(df.iloc[-60:], 3)
    hi, lo, rsi = df["High"].values[-60:], df["Low"].values[-60:], df["RSI"].values[-60:]
    out = []
    if len(H) >= 2 and H[-1] >= 60 - 18:
        a, b = H[-2], H[-1]
        if hi[b] > hi[a] and rsi[b] < rsi[a] - 2:
            out.append({"name": "Bearish RSI divergence", "bias": "bearish",
                        "detail": f"Price made a higher high ({hi[b]:,.0f} vs {hi[a]:,.0f}) but RSI made a lower high "
                                  f"({rsi[b]:.0f} vs {rsi[a]:.0f}): the rally is losing strength."})
    if len(L) >= 2 and L[-1] >= 60 - 18:
        a, b = L[-2], L[-1]
        if lo[b] < lo[a] and rsi[b] > rsi[a] + 2:
            out.append({"name": "Bullish RSI divergence", "bias": "bullish",
                        "detail": f"Price made a lower low ({lo[b]:,.0f} vs {lo[a]:,.0f}) but RSI made a higher low "
                                  f"({rsi[b]:.0f} vs {rsi[a]:.0f}): selling pressure is fading."})
    return out


def trend_structure(df, H, L):
    hi, lo = df["High"].values, df["Low"].values
    if len(H) < 2 or len(L) < 2:
        return {"label": "unclear", "detail": "Not enough swings yet."}
    hh, hl = hi[H[-1]] > hi[H[-2]], lo[L[-1]] > lo[L[-2]]
    if hh and hl:
        return {"label": "uptrend", "detail": "Higher highs and higher lows."}
    if not hh and not hl:
        return {"label": "downtrend", "detail": "Lower highs and lower lows."}
    return {"label": "sideways", "detail": "Mixed swings: " + ("higher high but lower low (widening)." if hh else "lower high but higher low (narrowing).")}


def technical_analysis(df):
    c, atr = float(df["Close"].iloc[-1]), float(df["ATR"].iloc[-1])
    H, L = swing_points(df, 5)
    a, pdi, mdi = adx(df)
    patterns, lines = chart_patterns(df, H, L)
    zones = sr_zones(df, H, L, c, atr)
    fib = fib_levels(df)
    struct = trend_structure(df, H, L)
    hi52 = float(df["High"].iloc[-252:].max())
    lo52 = float(df["Low"].iloc[-252:].min())

    # Major points: merge every level source, drop near-duplicates, keep those within 8% of price
    cand = [(z["level"], f"{z['side'].title()} zone ({z['touches']} touches)", 3 + z["touches"]) for z in zones]
    cand += [(lines[k]["next"], "Trendline through swing " + ("highs" if k == "resistance" else "lows"), 3) for k in lines]
    cand += [(p["level"], f"{p['name']} {'neckline' if 'top' in p['name'] or 'bottom' in p['name'] or 'shoulders' in p['name'] else 'line'}", 4)
             for p in patterns if p["level"]]
    cand += [(p["target"], f"{p['name']} target", 2) for p in patterns if p["target"]]
    cand += [(v, f"Fibonacci {k}", 2) for k, v in fib["levels"].items() if k in ("38.2%", "50%", "61.8%")]
    cand += [(hi52, "52-week high", 3), (lo52, "52-week low", 3)]
    if not pd.isna(df["SMA200"].iloc[-1]):
        cand.append((float(df["SMA200"].iloc[-1]), "200-day average", 3))
    key = []
    for v, name, pr in sorted(cand, key=lambda t: -t[2]):
        if v is None or abs(v / c - 1) > 0.08:
            continue
        if any(abs(v / k["price"] - 1) < 0.0025 for k in key):
            continue
        key.append({"price": round(float(v), 1), "label": name, "side": "resistance" if v > c else "support",
                    "dist_pct": round((v / c - 1) * 100, 2)})
    key = sorted(key, key=lambda k: -k["price"])[:12]

    return {"close": round(c, 1), "atr": round(atr, 1),
            "adx": {"value": round(float(a.iloc[-1]), 1), "plus_di": round(float(pdi.iloc[-1]), 1),
                    "minus_di": round(float(mdi.iloc[-1]), 1),
                    "read": ("strong trend" if a.iloc[-1] >= 25 else "weak or no trend" if a.iloc[-1] < 20 else "trend building")
                            + (", buyers stronger" if pdi.iloc[-1] > mdi.iloc[-1] else ", sellers stronger")},
            "structure": struct, "candles": candle_patterns(df), "patterns": patterns,
            "divergence": divergence(df), "trendlines": lines, "zones": zones, "fib": fib,
            "range_52w": [round(lo52, 1), round(hi52, 1)], "key_levels": key}


# ---------- Outlook: rule-based, and the Claude-written version ----------
def rule_outlook(ta, D):
    """Score the evidence. Used as the fallback note and passed to Claude as one input."""
    s, ev = 0.0, []
    st = ta["structure"]["label"]
    if st in ("uptrend", "downtrend"):
        s += 1 if st == "uptrend" else -1
        ev.append(f"Swing structure: {ta['structure']['detail'].lower()}")
    A = ta["adx"]
    if A["value"] >= 20:
        s += 1 if A["plus_di"] > A["minus_di"] else -1
        ev.append(f"ADX {A['value']}: {A['read']}")
    for p in ta["patterns"]:
        w = 1.5 if p["status"] in ("confirmed", "broken up", "broken down") else 0.5
        s += {"bullish": w, "bearish": -w}.get(p["bias"], 0)
        ev.append(f"{p['name']} ({p['status']})")
    for p in ta["candles"] + ta["divergence"]:
        s += {"bullish": 0.5, "bearish": -0.5}.get(p["bias"], 0)
        ev.append(p["name"])
    s += max(-2, min(2, D["signal"]["score"] / 2))
    outlook = "bullish" if s >= 2 else "bearish" if s <= -2 else "range-bound" if A["value"] < 20 else "neutral"
    conf = "high" if abs(s) >= 4 else "medium" if abs(s) >= 2 else "low"
    return outlook, conf, round(s, 1), ev


def rule_note(ta, D, outlook, conf, ev):
    c = ta["close"]
    res = [k for k in ta["key_levels"] if k["price"] > c][-1:]  # nearest above
    sup = [k for k in ta["key_levels"] if k["price"] < c][:1]   # nearest below
    r = res[0] if res else {"price": D["levels"]["R1"], "label": "R1"}
    s_ = sup[0] if sup else {"price": D["levels"]["S1"], "label": "S1"}
    f = lambda v: f"{v:,.0f}"
    head = {"bullish": f"Charts lean bullish. Holding above {f(s_['price'])} keeps buyers in charge.",
            "bearish": f"Charts lean bearish. Staying below {f(r['price'])} keeps sellers in charge.",
            "neutral": f"Mixed signals. Let a break of {f(r['price'])} or {f(s_['price'])} pick the direction.",
            "range-bound": f"No trend. Expect a range between {f(s_['price'])} and {f(r['price'])}."}[outlook]
    sug = [
        {"kind": "call", "title": f"Upside trigger above {f(r['price'])}",
         "detail": f"A daily or 15-minute close above the {r['label'].lower()} at {f(r['price'])} opens the next leg up. "
                   + ("This fits the current lean." if outlook == "bullish" else "This goes against the current lean, so trade smaller.")},
        {"kind": "put", "title": f"Downside trigger below {f(s_['price'])}",
         "detail": f"A close below the {s_['label'].lower()} at {f(s_['price'])} opens room lower. "
                   + ("This fits the current lean." if outlook == "bearish" else "This goes against the current lean, so trade smaller.")},
        {"kind": "wait", "title": "Inside the range, stay patient",
         "detail": f"Between {f(s_['price'])} and {f(r['price'])} there's no edge for option buyers; time decay works against you."},
    ]
    for p in ta["patterns"] + ta["divergence"]:
        sug.append({"kind": "risk", "title": p["name"], "detail": p["detail"]})
    return {"outlook": outlook, "confidence": conf, "headline": head,
            "summary": "Rule-based read of the evidence: " + ("; ".join(ev) if ev else "no strong patterns today") + ".",
            "pattern_read": "; ".join(f"{p['name']} ({p['status']})" for p in ta["patterns"]) or "No chart patterns detected.",
            "suggestions": sug[:6],
            "key_points": [{"price": k["price"], "label": k["label"], "side": k["side"], "why": ""} for k in ta["key_levels"]],
            "invalidation": f"A close beyond {f(r['price'])} or {f(s_['price'])} against the lean."}


AI_SCHEMA = {
    "type": "object",
    "properties": {
        "outlook": {"type": "string", "enum": ["bullish", "bearish", "neutral", "range-bound"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "pattern_read": {"type": "string"},
        "suggestions": {"type": "array", "items": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["call", "put", "wait", "risk"]},
                           "title": {"type": "string"}, "detail": {"type": "string"}},
            "required": ["kind", "title", "detail"], "additionalProperties": False}},
        "key_points": {"type": "array", "items": {
            "type": "object",
            "properties": {"price": {"type": "number"}, "label": {"type": "string"},
                           "side": {"type": "string", "enum": ["resistance", "support", "pivot"]},
                           "why": {"type": "string"}},
            "required": ["price", "label", "side", "why"], "additionalProperties": False}},
        "invalidation": {"type": "string"},
    },
    "required": ["outlook", "confidence", "headline", "summary", "pattern_read", "suggestions", "key_points", "invalidation"],
    "additionalProperties": False,
}

AI_SYSTEM = """You write the after-close technical note on the Nifty 50 for a dashboard used by Indian retail traders, many of whom buy index options.

You receive the last 40 daily sessions, the current indicators, the rule-based signal, pivot and option-chain levels, and what a pattern scanner found: candlestick patterns, chart patterns, trendlines, support/resistance zones, Fibonacci levels, RSI divergence, ADX and swing structure. Treat the scanner's output as a first pass, not as truth. Check each finding against the price data, say plainly when a pattern is weak or the evidence conflicts, and weigh it accordingly.

Use only the data given. Do not mention news, events or prices that are not in it. Every price you cite must come from the data or follow directly from it.

What to write:
- outlook and confidence for the next session or two. Use low confidence when the evidence conflicts; that is common and fine.
- headline: one sentence, at most 25 words, that a trader can act on.
- summary: 3 to 5 sentences on trend, momentum and where price sits relative to the levels that matter.
- pattern_read: 2 to 4 sentences on the patterns that matter and how reliable they look here.
- suggestions: 3 to 6 items. Make them conditional and level-based ("if Nifty closes above X, then ..."), with a trigger, a target and an exit level where it applies. kind is call (upside plan), put (downside plan), wait (no-trade conditions) or risk (something that could go wrong). Include at least one wait or risk item.
- key_points: the 5 to 10 price levels to watch next session, each with a short reason. side is resistance above the last close, support below it, or pivot for a level price is sitting on.
- invalidation: the price action that would prove this outlook wrong.

Write in plain English for people who know the basics, with no jargon beyond the indicator names. Don't add disclaimers; the page already shows one."""


def ai_note(ctx):
    """Ask Claude for the note. Returns a dict, or None to fall back to the rule-based note."""
    try:
        import anthropic
    except ImportError:
        print("AI analysis skipped: the anthropic package isn't installed")
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("AI analysis skipped: ANTHROPIC_API_KEY isn't set (using the rule-based note)")
        return None
    try:
        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model=AI_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if the model declines, the API retries on a fallback model in the same call
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": AI_SCHEMA}},
            system=AI_SYSTEM,
            messages=[{"role": "user", "content": "Data for the note, as JSON:\n" + json.dumps(ctx, separators=(",", ":"))
                       + f"\n\nWrite the note for the session on {ctx['next_session']}."}],
        )
    except anthropic.AuthenticationError:
        print("AI analysis failed: the API key was rejected")
        return None
    except anthropic.RateLimitError:
        print("AI analysis failed: rate limited")
        return None
    except anthropic.APIStatusError as e:
        print(f"AI analysis failed: API error {e.status_code}")
        return None
    except anthropic.APIConnectionError:
        print("AI analysis failed: couldn't reach the API")
        return None
    if resp.stop_reason != "end_turn":
        print(f"AI analysis unusable: stop_reason={resp.stop_reason}")
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        note = json.loads(text)
    except (TypeError, ValueError):
        print("AI analysis unusable: response wasn't valid JSON")
        return None
    note["model"] = resp.model
    print(f"AI analysis by {resp.model}: {note['outlook']} ({note['confidence']}), "
          f"{resp.usage.input_tokens} in / {resp.usage.output_tokens} out tokens")
    return note


def ai_context(df, ta, D):
    w = df.iloc[-40:]
    r = df.iloc[-1]
    oc = D.get("option_chain")
    return {
        "as_of": D["as_of"], "next_session": D["playbook"]["session"],
        "sessions": [{"date": d.strftime("%Y-%m-%d"), "o": round(float(x.Open), 1), "h": round(float(x.High), 1),
                      "l": round(float(x.Low), 1), "c": round(float(x.Close), 1), "rsi": round(float(x.RSI), 1),
                      "macd_hist": round(float(x.MACD_HIST), 1)} for d, x in w.iterrows()],
        "indicators": {k: (None if pd.isna(r[k]) else round(float(r[k]), 1))
                       for k in ["SMA20", "SMA50", "SMA200", "BB_UP", "BB_LO", "RSI", "MACD", "MACD_SIG", "ATR"]},
        "signal": D["signal"], "pivots_and_oi_levels": D["levels"],
        "option_chain": None if not oc else {k: oc.get(k) for k in ("expiry", "pcr", "max_ce_oi_strike", "max_pe_oi_strike", "max_pain", "stale")},
        "india_vix": D.get("vix"), "alerts": [a["title"] for a in D.get("alerts", [])],
        "scanner": ta,
    }


def update_analysis_track(df, entry):
    """Log today's outlook and grade earlier ones against the next session's close."""
    entries = []
    if os.path.exists(ANALYSIS_TRACK):
        with open(ANALYSIS_TRACK) as f:
            entries = json.load(f).get("entries", [])
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    for e in entries:
        if e.get("result") is None and e["date"] in dates:
            i = dates.index(e["date"])
            if i + 1 < len(dates):
                nxt = float(df["Close"].iloc[i + 1])
                ch = (nxt / e["close"] - 1) * 100
                e["next_close"], e["next_change_pct"] = round(nxt, 1), round(ch, 2)
                e["result"] = ("right" if {"bullish": ch > 0, "bearish": ch < 0}.get(e["outlook"], abs(ch) < 0.5)
                               else "wrong")
    entries = [e for e in entries if e["date"] != entry["date"]] + [entry]
    entries.sort(key=lambda e: e["date"])
    entries = entries[-300:]
    with open(ANALYSIS_TRACK, "w") as f:
        json.dump({"entries": entries}, f, indent=1)
    graded = [e for e in entries if e.get("result")]
    return entries[::-1][:30], {
        "graded": len(graded),
        "hit_rate": round(sum(e["result"] == "right" for e in graded) / len(graded) * 100, 1) if graded else None,
        "ai_hit_rate": (lambda g: round(sum(e["result"] == "right" for e in g) / len(g) * 100, 1) if g else None)(
            [e for e in graded if e.get("source") == "claude"]),
    }


def build_analysis(demo, df, D):
    ta = technical_analysis(df)
    outlook, conf, score, ev = rule_outlook(ta, D)
    note = None if (demo or "--no-ai" in sys.argv) else ai_note(ai_context(df, ta, D))
    source = "claude" if note else "rules"
    if not note:
        note = rule_note(ta, D, outlook, conf, ev)
    c = ta["close"]
    note["key_points"] = sorted(
        ({**k, "price": round(float(k["price"]), 1), "dist_pct": round((float(k["price"]) / c - 1) * 100, 2)}
         for k in note["key_points"] if 0.85 < float(k["price"]) / c < 1.15),
        key=lambda k: -k["price"])
    hist, summary = update_analysis_track(df, {
        "date": D["as_of"], "close": c, "outlook": note["outlook"], "confidence": note["confidence"],
        "source": source, "headline": note["headline"], "result": None})
    return {"source": source, "for_session": D["playbook"]["session"], "made_at": D["updated"],
            "rule_outlook": {"outlook": outlook, "confidence": conf, "score": score, "evidence": ev},
            "note": note, "ta": ta, "history": hist, "summary": summary}


def premarket_evening(demo, df, close):
    """Evening run: grade this morning's forecast, refit the model, and note
    where GIFT Nifty stood at Nifty's close (the reference for tomorrow)."""
    hist, summary = grade_gaps(df)
    try:
        model = fit_gap_model(df[["Open", "Close"]], demo)
    except Exception as e:
        print("Gap model fit failed:", e)
        model = None
    gift = get_gift(demo, close, df.index[-1].strftime("%Y-%m-%d"))
    eve = None
    if gift:
        eve = {"contracts": gift.get("contracts") or ({gift["expiry"]: gift["price"]} if gift.get("expiry") else {}),
               "price": gift.get("at_nifty_close") or gift["price"], "time": gift.get("time")}
    return {"status": "waiting", "model": model, "gift_eve": eve, "gift_now": gift,
            "history": hist, "summary": summary,
            "next_run": next_session(df.index[-1].date()).strftime("%a %d %b") + ", about 8:15 AM IST"}


# =====================================================================
# Main
# =====================================================================
def main():
    demo = "--demo" in sys.argv
    if "--premarket" in sys.argv:
        return premarket(demo)
    if "--hourly" in sys.argv:
        return hourly(demo)
    if "--news-only" in sys.argv:
        return news_only(demo)
    df, vix_s = load_demo() if demo else load_live()
    if "--cut" in sys.argv:
        n = int(sys.argv[sys.argv.index("--cut") + 1])
        if n > 0:
            df, vix_s = df.iloc[:-n], vix_s.iloc[:-n]
    df = add_indicators(df).dropna(subset=["SMA50"])
    vix_s = vix_s.reindex(df.index).ffill() if len(vix_s) else vix_s

    bt, scores = backtest(df.copy())
    df["score"] = scores
    last, prev = df.iloc[-1], df.iloc[-2]
    as_of = df.index[-1].date()

    vix = float(vix_s.iloc[-1]) if len(vix_s) else None
    vix_prev = float(vix_s.iloc[-2]) if len(vix_s) > 1 else None
    oc = get_chain(demo, float(last.Close), as_of)

    score, reasons = score_row(last, prev.MACD_HIST, vix, vix_prev, oc)
    bias = bias_from(score)
    lv = pivots(last.High, last.Low, last.Close)

    today = make_entry(as_of.strftime("%Y-%m-%d"), last, prev.MACD_HIST, vix, vix_prev, oc)
    track = update_track(df, vix_s, today)

    def col(s, nd=2):
        return [None if pd.isna(v) else round(float(v), nd) for v in s]

    levels = {k: round(float(v), 1) for k, v in lv.items()}
    if oc:
        levels["Call-OI wall"] = oc["max_ce_oi_strike"]
        levels["Put-OI wall"] = oc["max_pe_oi_strike"]
        levels["Max pain"] = oc["max_pain"]

    data = {
        "symbol": "NIFTY 50" + (" (DEMO DATA)" if demo else ""),
        "updated": dt.datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST"),
        "updated_iso": dt.datetime.now(IST).isoformat(timespec="seconds"),
        "as_of": as_of.strftime("%Y-%m-%d"),
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        **{k.lower(): col(df[k]) for k in ["Open", "High", "Low", "Close", "SMA20", "SMA50", "SMA200",
                                             "BB_UP", "BB_LO", "RSI", "MACD", "MACD_SIG", "MACD_HIST", "score"]},
        "vix_series": col(vix_s) if len(vix_s) else [],
        "last": {"close": round(float(last.Close), 2),
                 "change": round(float(last.Close - prev.Close), 2),
                 "change_pct": round(float((last.Close / prev.Close - 1) * 100), 2),
                 "rsi": round(float(last.RSI), 1), "atr": round(float(last.ATR), 1)},
        "vix": None if vix is None else {
            "value": round(vix, 2),
            "change_pct": round((vix / vix_prev - 1) * 100, 2) if vix_prev else None,
            # VIX is annualised %, so 1-day expected move ≈ VIX / sqrt(252)
            "day_move": round(float(last.Close) * vix / 100 / np.sqrt(252), 1)},
        "levels": levels,
        "expected_range": [round(float(last.Close - last.ATR), 1), round(float(last.Close + last.ATR), 1)],
        "option_chain": oc,
        "signal": {"bias": BIAS_LABEL[bias], "score": score, "reasons": reasons,
                   "plan": make_plan(bias, lv, float(last.Close))},
        "backtest": bt,
        "track": {"entries": track[::-1], "summary": summarize_track(track)},
        "intraday": get_intraday(demo, float(last.Close)),
        "playbook": build_playbook(last, lv, oc, vix, bias),
        "alerts": build_alerts(df, oc, vix, vix_prev, bias, lv),
        "news": get_news(demo),
        "global": get_global(demo, as_of.strftime("%Y-%m-%d")),
        "premarket": premarket_evening(demo, df, float(last.Close)),
    }
    try:
        data["analysis"] = build_analysis(demo, df, data)
    except Exception as e:  # never let the analysis section block the main data update
        print("Technical analysis failed:", type(e).__name__, e)
    with open("data.json", "w") as f:
        json.dump(data, f)
    print(f"{data['as_of']} close={last.Close:.1f} vix={vix} pcr={oc and oc['pcr']} "
          f"score={score} -> {bias}; tracked={len(track)}")


if __name__ == "__main__":
    main()
