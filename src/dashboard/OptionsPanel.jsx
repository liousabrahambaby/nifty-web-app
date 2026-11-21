import { useMemo, useState } from 'react'
import Plot from '../components/Plot.jsx'
import Seg from '../components/Seg.jsx'
import { fmt } from '../lib/format'
import { C, AX, BASE } from '../lib/chartTheme'

export default function OptionsPanel({ D, active, days }) {
  const [oiMode, setOiMode] = useState('oi')
  const O = D.option_chain, V = D.vix

  const tiles = O
    ? [
        ['Expiry', O.expiry],
        ['PCR by OI', O.pcr],
        ['PCR by change in OI', O.pcr_chg_oi ?? '–'],
        ['Max pain', fmt(O.max_pain, 0)],
        ['Call-OI wall', fmt(O.max_ce_oi_strike, 0)],
        ['Put-OI wall', fmt(O.max_pe_oi_strike, 0)],
        ...(V ? [['India VIX', V.value]] : []),
      ]
    : []

  return (
    <div className="box">
      <h2>Option chain and volatility</h2>
      {!O ? (
        <div className="note">NSE didn't return option-chain data. NSE often blocks cloud servers, so run the update from your own computer (see the README).</div>
      ) : (
        O.stale && <div className="note">Today's NSE request failed, so this is the last saved snapshot from {O.fetched_at}. It isn't used in today's signal.</div>
      )}
      <div className="tiles">
        {tiles.map(([k, v]) => (
          <div className="tile" key={k}><span>{k}</span><b>{v}</b></div>
        ))}
      </div>
      <div className="grid two">
        <div>
          <div className="controls">
            <Seg className="oiMode" options={[['oi', 'Open interest'], ['chg', 'Change in OI']]} value={oiMode} onChange={setOiMode} />
          </div>
          {active && (O ? <OIChart O={O} mode={oiMode} /> : <div id="oiChart"><p className="mut">No option-chain data yet.</p></div>)}
          <p className="small mut">Large call OI above the price often acts as resistance. Large put OI below it often acts as support.</p>
        </div>
        <div>
          <div className="controls">
            <span className="small mut" style={{ padding: '6px 0' }}>India VIX, following the chart range on the Dashboard tab</span>
          </div>
          {active && <VixChart D={D} days={days} />}
          <p className="small mut">Above 20 means high fear and expensive premiums. Below 12 means a calm market and cheap premiums.</p>
        </div>
      </div>
    </div>
  )
}

function OIChart({ O, mode }) {
  const { data, layout } = useMemo(() => {
    const x = O.strikes.map(String)
    // Position of the strike nearest to spot. Shapes on a category axis need the category's index:
    // passing the strike itself ("25650") is read as position 25650 and squashes the bars to a sliver.
    const nearest = O.strikes.reduce((best, s, i) => (Math.abs(s - O.spot) < Math.abs(O.strikes[best] - O.spot) ? i : best), 0)
    const atm = nearest
    return {
      data: [
        { x, y: mode === 'oi' ? O.ce_oi : O.ce_chg, type: 'bar', name: 'Calls (CE)', marker: { color: 'rgba(255,92,122,.8)' } },
        { x, y: mode === 'oi' ? O.pe_oi : O.pe_chg, type: 'bar', name: 'Puts (PE)', marker: { color: 'rgba(46,229,157,.8)' } },
      ],
      layout: {
        ...BASE,
        barmode: 'group',
        margin: { l: 55, r: 10, t: 10, b: 40 },
        legend: { orientation: 'h', y: 1.12 },
        hovermode: 'x unified',
        xaxis: { ...AX, type: 'category', title: { text: 'Strike', font: { size: 10 } }, nticks: 12 },
        yaxis: { ...AX },
        shapes: [{ type: 'line', x0: atm, x1: atm, yref: 'paper', y0: 0, y1: 1, line: { color: C.ion, dash: 'dot' } }],
        annotations: [{ x: atm, yref: 'paper', y: 1, text: `Spot ${fmt(O.spot, 0)}`, showarrow: false, yanchor: 'bottom', font: { size: 10, color: C.ion } }],
      },
    }
  }, [O, mode])
  return <Plot id="oiChart" data={data} layout={layout} />
}

function VixChart({ D, days }) {
  const chart = useMemo(() => {
    if (!D.vix_series.length) return null
    const span = typeof days === 'string' ? 22 : days // intraday views show the last month of VIX
    const n = D.dates.length, start = span ? Math.max(0, n - span) : 0
    return {
      data: [
        {
          x: D.dates.slice(start), y: D.vix_series.slice(start), type: 'scatter', mode: 'lines', name: 'India VIX',
          line: { color: C.amber, width: 1.8 }, fill: 'tozeroy', fillcolor: 'rgba(255,181,71,.08)',
        },
      ],
      layout: {
        ...BASE,
        margin: { l: 40, r: 10, t: 10, b: 30 },
        showlegend: false,
        hovermode: 'x unified',
        xaxis: { ...AX, type: 'category', nticks: 6 },
        yaxis: { ...AX },
        shapes: [20, 12].map(v => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: v, y1: v, line: { color: C.mut, dash: 'dot', width: 1 } })),
      },
    }
  }, [D, days])
  if (!chart) return <div id="vixChart"><p className="mut">No VIX data yet.</p></div>
  return <Plot id="vixChart" data={chart.data} layout={chart.layout} />
}
