import { Fragment, useMemo } from 'react'
import Plot from '../components/Plot.jsx'
import { C, AX, BASE } from '../lib/chartTheme'
import { fmt, signed, pnCls } from '../lib/format'

const OUTLOOK_CLS = { bullish: 'call', bearish: 'put' }
const TAG = { call: 'CE', put: 'PE', wait: 'Wait', risk: 'Risk' }
const BIAS_CLS = { bullish: 'call', bearish: 'put' }

/** Daily technical analysis: Claude's (or the rule-based) note, the marked-up chart, and the scanner's findings. */
export default function AIAnalysisPanel({ D, active }) {
  const A = D.analysis
  if (!A) {
    return (
      <div className="box">
        <p className="headline">The AI analysis appears after the next 4 PM data update.</p>
      </div>
    )
  }
  const N = A.note
  const ta = A.ta
  return (
    <>
      <div className="grid main">
        <div className="stack">
          <div className={`signal ${OUTLOOK_CLS[N.outlook] || 'none'}`}>
            <p className="small mut" style={{ margin: 0 }}>
              Technical outlook for {A.for_session} · {N.confidence} confidence
            </p>
            <div className="bias-name" style={{ textTransform: 'capitalize' }}>{N.outlook}</div>
            <p className="headline" style={{ fontSize: 19 }}>{N.headline}</p>
            <p className="ai-text">{N.summary}</p>
            <p className="ai-src">
              {A.source === 'claude'
                ? `Written by Claude (${N.model || 'AI'}) from the scanner's findings · ${A.made_at}`
                : `Rule-based note (AI analysis unavailable) · ${A.made_at}`}
            </p>
          </div>
          <div className="box">
            <h2>Marked-up chart</h2>
            <p className="small mut" style={{ margin: '0 0 6px' }}>
              Key levels, support/resistance zones, trendlines and pattern points over the last 6 months.
            </p>
            {active && <TAChart D={D} A={A} />}
          </div>
        </div>
        <div className="stack">
          <div className="box">
            <h2>Suggestions</h2>
            <div className="scen">
              {N.suggestions.map((s, i) => (
                <div className={`sc ${s.kind}`} key={i}>
                  <span className="tag">{TAG[s.kind]}</span>
                  <div className="when">{s.title}</div>
                  <div className="small" style={{ color: '#C9D0F0' }}>{s.detail}</div>
                </div>
              ))}
            </div>
            {N.invalidation && (
              <p className="note" style={{ margin: '12px 0 0' }}><b>What would prove this wrong:</b> {N.invalidation}</p>
            )}
          </div>
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="box">
          <h2>Major points to watch</h2>
          <KeyPoints points={N.key_points} close={ta.close} />
        </div>
        <div className="box">
          <h2>Patterns found</h2>
          {N.pattern_read && <p className="ai-text" style={{ marginTop: 0 }}>{N.pattern_read}</p>}
          <Findings ta={ta} />
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="box">
          <h2>Trend and momentum</h2>
          <table className="kv">
            <tbody>
              <tr><td>Swing structure</td><td>{ta.structure.label}</td></tr>
              <tr><td>ADX (trend strength)</td><td>{ta.adx.value}</td></tr>
              <tr><td>+DI / −DI</td><td>{ta.adx.plus_di} / {ta.adx.minus_di}</td></tr>
              <tr><td>52-week range</td><td>{fmt(ta.range_52w[0], 0)} – {fmt(ta.range_52w[1], 0)}</td></tr>
              <tr><td>Average daily range (ATR)</td><td>{fmt(ta.atr, 0)} pts</td></tr>
              <tr><td>Rule-based score</td><td>{A.rule_outlook.score > 0 ? '+' : ''}{A.rule_outlook.score} ({A.rule_outlook.outlook})</td></tr>
            </tbody>
          </table>
          <p className="small mut" style={{ marginBottom: 0 }}>{ta.structure.detail} ADX reads: {ta.adx.read}.</p>
          <h3>Fibonacci retracement</h3>
          <p className="small mut" style={{ margin: '0 0 6px' }}>
            Of the {ta.fib.direction === 'up' ? 'rise' : 'fall'} from {fmt(ta.fib.direction === 'up' ? ta.fib.swing_low : ta.fib.swing_high, 0)} (
            {ta.fib.direction === 'up' ? ta.fib.low_date : ta.fib.high_date}) to {fmt(ta.fib.direction === 'up' ? ta.fib.swing_high : ta.fib.swing_low, 0)} (
            {ta.fib.direction === 'up' ? ta.fib.high_date : ta.fib.low_date})
          </p>
          <table className="kv">
            <tbody>
              {Object.entries(ta.fib.levels).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td>{fmt(v, 0)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="box">
          <h2>Past outlooks</h2>
          <History A={A} />
        </div>
      </div>
    </>
  )
}

function KeyPoints({ points, close }) {
  const hereAt = points.findIndex(p => p.price < close)
  const here = (
    <tr className="here" key="here">
      <td>Last close</td><td className="v">{fmt(close, 1)}</td><td className="d">0</td><td>You are here</td>
    </tr>
  )
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="watch">
        <thead>
          <tr><th>Level</th><th>Price</th><th style={{ textAlign: 'right' }}>Distance</th><th>Why it matters</th></tr>
        </thead>
        <tbody>
          {points.map((p, i) => {
            const dist = p.price - close
            return (
              <Fragment key={p.label + i}>
                {i === hereAt && here}
                <tr>
                  <td>{p.label}</td>
                  <td className="v">{fmt(p.price, 1)}</td>
                  <td className={`d ${pnCls(dist)}`}>
                    {signed(dist)}
                    <br />
                    <span className="small mut">{p.dist_pct >= 0 ? '+' : ''}{p.dist_pct}%</span>
                  </td>
                  <td className="why">{p.why || p.side}</td>
                </tr>
                <tr className="whyrow"><td colSpan={3}>{p.why || p.side}</td></tr>
              </Fragment>
            )
          })}
          {hereAt === -1 && here}
        </tbody>
      </table>
    </div>
  )
}

function Findings({ ta }) {
  const items = [
    ...ta.patterns.map(p => ({ ...p, group: 'Chart pattern' })),
    ...ta.candles.map(p => ({ ...p, group: 'Candle' })),
    ...ta.divergence.map(p => ({ ...p, group: 'Divergence' })),
  ]
  if (!items.length) return <p className="mut small">No chart or candlestick patterns stand out today.</p>
  return (
    <div className="ai-findings">
      {items.map((p, i) => (
        <div className="method" key={i}>
          <div className="method-top">
            <span>
              {p.name}
              <span className="small mut"> · {p.group}{p.status ? `, ${p.status}` : ''}</span>
            </span>
            <span className={`pill ${BIAS_CLS[p.bias] || 'none'}`}>{p.bias}</span>
          </div>
          <p>
            {p.detail}
            {p.target != null && ` Measured target: ${fmt(p.target, 0)}.`}
          </p>
        </div>
      ))}
      {ta.zones.length > 0 && (
        <>
          <h3>Support and resistance zones</h3>
          <table className="kv">
            <tbody>
              {ta.zones.map((z, i) => (
                <tr key={i}>
                  <td>
                    <span className={z.side === 'resistance' ? 'neg' : 'pos'}>{z.side}</span>, {z.touches} touches, last {z.last_touch}
                  </td>
                  <td>{fmt(z.low, 0)} – {fmt(z.high, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

function History({ A }) {
  const S = A.summary
  return (
    <>
      <div className="tiles">
        <div className="tile"><span>Outlooks graded</span><b>{S.graded}</b></div>
        <div className="tile"><span>Right next day</span><b>{S.hit_rate == null ? '–' : `${S.hit_rate}%`}</b></div>
        <div className="tile"><span>Claude's hit rate</span><b>{S.ai_hit_rate == null ? '–' : `${S.ai_hit_rate}%`}</b></div>
      </div>
      <p className="small mut" style={{ marginTop: 0 }}>
        Each day's outlook is checked against the next session's close: bullish is right if Nifty closed higher, bearish if lower,
        neutral or range-bound if it moved less than 0.5%.
      </p>
      <div className="tablewrap">
        <table className="hist">
          <thead>
            <tr><th>Date</th><th>Outlook</th><th>By</th><th style={{ textAlign: 'right' }}>Next day</th><th>Result</th></tr>
          </thead>
          <tbody>
            {A.history.map(e => (
              <tr key={e.date} title={e.headline}>
                <td>{e.date}</td>
                <td><span className={`pill ${OUTLOOK_CLS[e.outlook] || 'none'}`}>{e.outlook}</span> <span className="small mut">{e.confidence}</span></td>
                <td className="small mut">{e.source === 'claude' ? 'Claude' : 'Rules'}</td>
                <td style={{ textAlign: 'right' }} className={e.next_change_pct == null ? 'mut' : pnCls(e.next_change_pct)}>
                  {e.next_change_pct == null ? 'pending' : `${e.next_change_pct > 0 ? '+' : ''}${e.next_change_pct}%`}
                </td>
                <td className={e.result === 'right' ? 'pos' : e.result === 'wrong' ? 'neg' : 'mut'}>{e.result || '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function TAChart({ D, A }) {
  const chart = useMemo(() => buildChart(D, A), [D, A])
  return <Plot id="taChart" data={chart.data} layout={chart.layout} />
}

function buildChart(D, A) {
  const n = D.dates.length
  const start = Math.max(0, n - 126)
  const cut = a => a.slice(start)
  const x = cut(D.dates)
  const inView = d => d >= x[0]
  const ta = A.ta
  const data = [
    {
      x, open: cut(D.open), high: cut(D.high), low: cut(D.low), close: cut(D.close),
      type: 'candlestick', name: 'Nifty', showlegend: false,
      increasing: { line: { color: C.bull }, fillcolor: 'rgba(46,229,157,.55)' },
      decreasing: { line: { color: C.bear }, fillcolor: 'rgba(255,92,122,.55)' },
    },
  ]
  // Trendlines through swing highs / lows
  Object.entries(ta.trendlines).forEach(([k, t]) => {
    if (!inView(t.from.date)) return
    data.push({
      x: [t.from.date, t.to.date], y: [t.from.price, t.to.price], type: 'scatter', mode: 'lines',
      name: k === 'resistance' ? 'Trendline (highs)' : 'Trendline (lows)',
      line: { color: k === 'resistance' ? C.bear : C.bull, width: 2, dash: 'dash' },
    })
  })
  // Pattern anchor points (peaks / troughs)
  ta.patterns.forEach(p => {
    const pts = p.points.filter(q => inView(q.date))
    if (!pts.length) return
    data.push({
      x: pts.map(q => q.date), y: pts.map(q => q.price), type: 'scatter', mode: 'markers+text', name: p.name,
      text: pts.map(() => p.name.split(' ')[0]), textposition: p.bias === 'bearish' ? 'top center' : 'bottom center',
      textfont: { size: 10, color: C.amber }, marker: { symbol: 'circle-open', size: 13, color: C.amber, line: { width: 2 } },
    })
  })

  const shapes = []
  const annotations = []
  // Support/resistance zones as shaded bands
  ta.zones.forEach(z => {
    const pad = z.high - z.low < 10 ? 10 : 0
    shapes.push({
      type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: z.low - pad, y1: z.high + pad, line: { width: 0 },
      fillcolor: z.side === 'resistance' ? 'rgba(255,92,122,.10)' : 'rgba(46,229,157,.10)', layer: 'below',
    })
  })
  // Key points from the note
  A.note.key_points.forEach(p => {
    const color = p.side === 'resistance' ? C.bear : p.side === 'support' ? C.bull : C.ion
    shapes.push({ type: 'line', xref: 'paper', x0: 0.7, x1: 1, yref: 'y', y0: p.price, y1: p.price, line: { color, width: 1, dash: 'dot' } })
    annotations.push({
      xref: 'paper', x: 1, y: p.price, yref: 'y', text: `${p.label} ${Math.round(p.price)}`, showarrow: false,
      xanchor: 'right', yanchor: 'bottom', font: { size: 10, color },
    })
  })

  const lows = cut(D.low), highs = cut(D.high)
  const lvls = A.note.key_points.map(p => p.price)
  const lo = Math.min(...lows, ...lvls.filter(v => v > Math.min(...lows) * 0.97))
  const hi = Math.max(...highs, ...lvls.filter(v => v < Math.max(...highs) * 1.03))
  const layout = {
    ...BASE,
    margin: { l: 50, r: 10, t: 10, b: 30 },
    legend: { orientation: 'h', y: 1.08 },
    hovermode: 'x unified',
    shapes,
    annotations,
    xaxis: { ...AX, rangeslider: { visible: false }, type: 'category', nticks: 8 },
    yaxis: { ...AX, range: [lo * 0.995, hi * 1.005] },
  }
  return { data, layout }
}
