import { useMemo, useState } from 'react'
import Plot from '../components/Plot.jsx'
import Seg from '../components/Seg.jsx'
import { AX, BASE, C } from '../lib/chartTheme'
import { fmt, pnCls } from '../lib/format'

const cr = v => `${v >= 0 ? '+' : '−'}₹${fmt(Math.abs(v), 0)} cr`

function streakTxt(n, who) {
  if (!n) return `${who}: no streak`
  const days = Math.abs(n)
  return `${who} net ${n > 0 ? 'buyers' : 'sellers'} ${days} session${days > 1 ? 's' : ''} running`
}

/** FII / DII daily net flows built up from fii_dii_track.json, one row per trading day. */
export default function FlowHistory({ H }) {
  const [view, setView] = useState('daily')
  const [span, setSpan] = useState(30)
  const entries = useMemo(() => (H ? H.entries.slice(-span) : []), [H, span])
  const chart = useMemo(() => buildChart(entries, view), [entries, view])

  if (!H || !H.entries.length) return null
  const S = H.summary
  const few = H.days < 5

  return (
    <div className="box flowhist">
      <div className="alerts-head">
        <h2>FII / DII trend</h2>
        <div className="controls">
          <Seg options={[['daily', 'Daily net'], ['cum', 'Cumulative']]} value={view} onChange={setView} />
          <Seg options={[[20, '20D'], [30, '30D'], [60, '60D']]} value={span} onChange={setSpan} />
        </div>
      </div>
      <div className="tiles">
        <div className="tile"><span>FII, last {S.days_5} days</span><b className={pnCls(S.fii_5d)}>{cr(S.fii_5d)}</b></div>
        <div className="tile"><span>FII, last {S.days_20} days</span><b className={pnCls(S.fii_20d)}>{cr(S.fii_20d)}</b></div>
        <div className="tile"><span>DII, last {S.days_5} days</span><b className={pnCls(S.dii_5d)}>{cr(S.dii_5d)}</b></div>
        <div className="tile"><span>DII, last {S.days_20} days</span><b className={pnCls(S.dii_20d)}>{cr(S.dii_20d)}</b></div>
      </div>
      <p className="flow-read" style={{ margin: '0 0 6px' }}>
        {streakTxt(S.fii_streak, 'FIIs')}. {streakTxt(S.dii_streak, 'DIIs')}.
      </p>
      <Plot id="flowChart" data={chart.data} layout={chart.layout} />
      <p className="small mut" style={{ margin: '6px 0 0' }}>
        Cash-market figures from NSE, in ₹ crore. NSE only publishes the latest day, so this history is collected one day at a
        time from each update{few ? `; it has ${H.days} day${H.days > 1 ? 's' : ''} so far and fills in as the days go by` : ''}.
      </p>
    </div>
  )
}

function buildChart(entries, view) {
  const x = entries.map(e => e.date)
  const fii = entries.map(e => e.fii.net)
  const dii = entries.map(e => e.dii.net)
  const hover = '%{x}<br>%{fullData.name}: ₹%{y:,.0f} cr<extra></extra>'
  let data
  if (view === 'daily') {
    data = [
      { x, y: fii, name: 'FII / FPI', type: 'bar', marker: { color: C.ion }, hovertemplate: hover },
      { x, y: dii, name: 'DII', type: 'bar', marker: { color: C.amber }, hovertemplate: hover },
      {
        x, y: fii.map((v, i) => v + dii[i]), name: 'Combined', type: 'scatter', mode: 'lines+markers',
        line: { color: '#E6EAFF', width: 1.5, dash: 'dot' }, marker: { size: 4 }, hovertemplate: hover,
      },
    ]
  } else {
    const run = xs => { let t = 0; return xs.map(v => (t += v)) }
    data = [
      { x, y: run(fii), name: 'FII / FPI', type: 'scatter', mode: 'lines', line: { color: C.ion, width: 2.5 }, hovertemplate: hover },
      { x, y: run(dii), name: 'DII', type: 'scatter', mode: 'lines', line: { color: C.amber, width: 2.5 }, hovertemplate: hover },
      {
        x, y: run(fii.map((v, i) => v + dii[i])), name: 'Combined', type: 'scatter', mode: 'lines',
        line: { color: '#E6EAFF', width: 1.5, dash: 'dot' }, hovertemplate: hover,
      },
    ]
  }
  return {
    data,
    layout: {
      ...BASE,
      barmode: 'group',
      bargap: 0.25,
      margin: { l: 80, r: 10, t: 10, b: 40 },
      legend: { orientation: 'h', y: 1.08, x: 0 },
      xaxis: { ...AX, type: 'category', nticks: 8 },
      yaxis: { ...AX, tickprefix: '₹', ticksuffix: ' cr', tickformat: ',.0f', zerolinecolor: C.mut },
    },
  }
}
