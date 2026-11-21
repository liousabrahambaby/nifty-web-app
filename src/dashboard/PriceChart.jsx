import { useMemo } from 'react'
import Plot from '../components/Plot.jsx'
import { C, AX, BASE } from '../lib/chartTheme'

/** Candles + overlays on top, RSI in the middle, MACD at the bottom. */
export default function PriceChart({ D, days, overlays }) {
  const chart = useMemo(() => buildChart(D, days, overlays), [D, days, overlays])
  return (
    <>
      <div className="small mut" style={{ marginBottom: 4 }}>{chart.note}</div>
      {chart.empty ? (
        <div id="chart">
          <p className="mut" style={{ padding: 40, textAlign: 'center' }}>Intraday candles appear after the next data update.</p>
        </div>
      ) : (
        <Plot id="chart" data={chart.data} layout={chart.layout} />
      )}
    </>
  )
}

function buildChart(D, days, show) {
  const intra = typeof days === 'string' // '1d' / '5d' use intraday candles
  const src = intra ? (D.intraday || {})[days] : D
  if (!src) return { empty: true, note: '' }

  const note = intra
    ? `${src.interval === '5m' ? '5-minute' : '15-minute'} candles for ${src.from === src.to ? src.to : src.from + ' to ' + src.to}. This is the last completed session, not a live chart.`
    : 'Daily candles'

  const n = src.dates.length
  const start = !intra && days ? Math.max(0, n - days) : 0
  const cut = a => a.slice(start)
  const x = cut(src.dates)
  const line = (y, name, color, extra = {}) => ({ x, y: cut(y), name, type: 'scatter', mode: 'lines', line: { width: 1.5, color }, ...extra })

  const data = [
    {
      x, open: cut(src.open), high: cut(src.high), low: cut(src.low), close: cut(src.close),
      type: 'candlestick', name: 'Nifty',
      increasing: { line: { color: C.bull }, fillcolor: 'rgba(46,229,157,.55)' },
      decreasing: { line: { color: C.bear }, fillcolor: 'rgba(255,92,122,.55)' },
    },
  ]
  if (show.sma20) data.push(line(src.sma20, 'SMA 20', C.ion))
  if (show.sma50) data.push(line(src.sma50, 'SMA 50', C.amber))
  if (show.sma200) data.push(line(src.sma200, 'SMA 200', C.violet))
  if (show.bb) {
    data.push(line(src.bb_up, 'BB upper', C.mut, { line: { dash: 'dot', width: 1, color: C.mut } }))
    data.push(line(src.bb_lo, 'BB lower', C.mut, { line: { dash: 'dot', width: 1, color: C.mut }, fill: 'tonexty', fillcolor: 'rgba(142,152,200,.07)' }))
  }
  if (show.sig && !intra) {
    // mark the first day of each run of strong call/put scores
    const sc = cut(D.score), lo = cut(D.low), hi = cut(D.high)
    const firsts = f => x.map((_, i) => i).filter(i => f(sc[i]) && (i === 0 || !f(sc[i - 1])))
    const ci = firsts(v => v >= 2.5), pi = firsts(v => v <= -2.5)
    data.push({ x: ci.map(i => x[i]), y: ci.map(i => lo[i] * 0.995), mode: 'markers', type: 'scatter', name: 'Call bias', marker: { symbol: 'triangle-up', size: 10, color: C.bull } })
    data.push({ x: pi.map(i => x[i]), y: pi.map(i => hi[i] * 1.005), mode: 'markers', type: 'scatter', name: 'Put bias', marker: { symbol: 'triangle-down', size: 10, color: C.bear } })
  }
  data.push({ ...line(src.rsi, 'RSI', C.violet), yaxis: 'y2' })
  const hist = cut(src.macd_hist)
  data.push({ x, y: hist, type: 'bar', name: 'MACD hist', yaxis: 'y3', marker: { color: hist.map(v => (v >= 0 ? 'rgba(46,229,157,.7)' : 'rgba(255,92,122,.7)')) } })
  data.push({ ...line(src.macd, 'MACD', C.ion), yaxis: 'y3' })
  data.push({ ...line(src.macd_sig, 'Signal', C.amber), yaxis: 'y3' })

  const shapes = [70, 30].map(v => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y2', y0: v, y1: v, line: { color: C.mut, dash: 'dot', width: 1 } }))
  const annotations = []
  const hline = (v, label, color, dash) => {
    shapes.push({ type: 'line', xref: 'paper', x0: 0.8, x1: 1, yref: 'y', y0: v, y1: v, line: { color, width: 1, dash } })
    annotations.push({ xref: 'paper', x: 1, y: v, yref: 'y', text: `${label} ${Math.round(v)}`, showarrow: false, xanchor: 'right', yanchor: 'bottom', font: { size: 10, color } })
  }
  if (intra && src.prev_close) hline(src.prev_close, 'Prev close', C.mut, 'dot')
  if (show.lv) ['R2', 'R1', 'Pivot', 'S1', 'S2'].forEach(k => hline(D.levels[k], k, k[0] === 'R' ? C.bear : k[0] === 'S' ? C.bull : '#E8ECFF', 'dash'))
  if (show.oi && D.option_chain) {
    hline(D.option_chain.max_ce_oi_strike, 'Call wall', C.violet, 'dot')
    hline(D.option_chain.max_pe_oi_strike, 'Put wall', C.violet, 'dot')
  }

  const layout = {
    ...BASE,
    margin: { l: 50, r: 10, t: 10, b: 30 },
    legend: { orientation: 'h', y: 1.07 },
    hovermode: 'x unified',
    shapes,
    annotations,
    xaxis: { ...AX, rangeslider: { visible: false }, type: 'category', nticks: intra ? 10 : 8 },
    yaxis: { ...AX, domain: [0.42, 1] },
    yaxis2: { ...AX, domain: [0.22, 0.38], range: [0, 100], title: { text: 'RSI', font: { size: 10 } } },
    yaxis3: { ...AX, domain: [0, 0.18], title: { text: 'MACD', font: { size: 10 } } },
  }
  return { note, data, layout }
}
