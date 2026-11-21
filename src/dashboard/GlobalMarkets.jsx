import { fmt, signed, signCls, pnCls } from '../lib/format'
import { C } from '../lib/chartTheme'

const REGIONS = [
  ['US futures', 'US futures (live)'],
  ['Asia', 'Asia'],
  ['US', 'US (last close)'],
  ['Europe', 'Europe'],
  ['Macro', 'Oil, gold & rates'],
]
const TWO_DECIMALS = ['^TNX', 'INR=X', 'DX-Y.NYB', '^VIX', 'BZ=F']

export default function GlobalMarkets({ D }) {
  const G = D.global
  const hasRows = G && G.rows.length > 0
  return (
    <section className="globe" aria-labelledby="globeTitle">
      <div className="alerts-head">
        <h2 id="globeTitle">Global markets</h2>
        <span className="small mut">{hasRows && `Refreshed ${G.updated}. Changes are from each market's previous close.`}</span>
      </div>
      {!hasRows ? (
        <p className="mut">Global market data appears after the next data update.</p>
      ) : (
        <>
          <GiftCard D={D} />
          <div>
            {REGIONS.map(([region, label]) => {
              const rows = G.rows.filter(r => r.region === region)
              if (!rows.length) return null
              return (
                <div className="region" key={region}>
                  <h3>{label}</h3>
                  <div className="mkts">
                    {rows.map(r => (
                      <div className="mkt" key={r.symbol} title={`${r.name}: ${r.date}`}>
                        <div className="n">{r.name}</div>
                        <div className="v">{fmt(r.last, TWO_DECIMALS.includes(r.symbol) ? 2 : 0)}</div>
                        <div className={`c ${pnCls(r.pct)}`}>
                          {r.pct >= 0 ? '▲' : '▼'} {Math.abs(r.pct).toFixed(2)}%
                        </div>
                        <div className="d">{r.date}</div>
                        <Spark values={r.spark} up={r.pct >= 0} />
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}

function Spark({ values, up }) {
  if (!values || values.length < 2) return null
  const lo = Math.min(...values), hi = Math.max(...values), r = hi - lo || 1
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * 56).toFixed(1)},${(22 - ((v - lo) / r) * 22).toFixed(1)}`).join(' ')
  return (
    <svg viewBox="0 0 56 22" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={up ? C.bull : C.bear} strokeWidth="1.5" strokeLinejoin="round" opacity=".85" />
    </svg>
  )
}

function GiftCard({ D }) {
  const PM = D.premarket || {}
  const P = PM.status === 'ready' ? PM.prediction : null
  const g = (P && P.gift) || PM.gift_now
  if (!g || !g.price) return null

  const chg = g.price - (g.prev_close || g.price)
  const pc = g.prev_close ? (chg / g.prev_close) * 100 : 0
  const exp = g.expiry ? new Date(g.expiry.replace(/-/g, ' ')) : null
  const expTxt =
    exp && !isNaN(exp)
      ? `${exp.toLocaleDateString('en-IN', { month: 'long' })} contract, expires ${exp.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`
      : 'Near-month contract'
  const prem = g.price - D.last.close
  const usedGift = P && P.method === 'GIFT Nifty'

  const facts = [
    ['Vs Nifty close', <span className={pnCls(prem)}>{signed(prem)}</span>],
    usedGift && ['Implied gap', <span className={signCls(P.pct)}>{signed(P.pts)} pts</span>],
    usedGift && ['Implied open', fmt(P.open_est, 0)],
    ['Last trade', g.time ? String(g.time).replace(/:\d\d$/, '') : '–'],
  ].filter(Boolean)

  return (
    <div className="giftcard">
      <div className="lbl">
        GIFT Nifty<small>{expTxt}, NSE IX</small>
      </div>
      <div>
        <div className="big">{fmt(g.price, 1)}</div>
        <div className={`chg ${pnCls(chg)}`}>
          {chg >= 0 ? '▲' : '▼'} {fmt(Math.abs(chg), 1)} ({pc >= 0 ? '+' : '−'}
          {Math.abs(pc).toFixed(2)}%)
        </div>
      </div>
      <div className="facts">
        {facts.map(([k, v]) => (
          <div key={k}>
            <span>{k}</span>
            <b>{v}</b>
          </div>
        ))}
      </div>
    </div>
  )
}
