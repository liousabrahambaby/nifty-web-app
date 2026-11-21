import { useMemo, useState } from 'react'
import Plot from '../components/Plot.jsx'
import Seg from '../components/Seg.jsx'
import { fmt, pnCls } from '../lib/format'
import { C, AX, BASE } from '../lib/chartTheme'

const LABEL = { CALL: 'CALL', PUT: 'PUT', NONE: 'NO TRADE' }
const PILL = { CALL: 'call', PUT: 'put', NONE: 'none' }
const pct = v => (v == null ? '–' : v + '%')

export default function TrackPanel({ D, active }) {
  const [scope, setScope] = useState('live')
  const [filter, setFilter] = useState('all')
  const T = D.track
  const S = T.summary[scope] || {}

  const entries = useMemo(() => T.entries.filter(e => scope === 'all' || !e.backfilled), [T, scope])
  const rows = filter === 'all' ? entries : entries.filter(e => e.bias === filter)

  return (
    <div className="box">
      <h2>How past signals played out</h2>
      <div className="controls">
        <Seg className="trackScope" options={[['live', 'Live signals only'], ['all', 'Include backfilled']]} value={scope} onChange={setScope} />
      </div>
      <div className="tiles">
        <div className="tile"><span>Trade signals</span><b>{S.signals}</b></div>
        <div className="tile"><span>Triggered</span><b>{S.triggered}</b></div>
        <div className="tile"><span>Win rate when triggered</span><b>{pct(S.win_rate)}</b></div>
        <div className="tile"><span>Direction right</span><b>{pct(S.direction_ok)}</b></div>
        <div className="tile">
          <span>Net points</span>
          <b><span className={pnCls(S.total_points)}>{S.total_points >= 0 ? '+' : ''}{fmt(S.total_points, 1)}</span></b>
        </div>
        <div className="tile"><span>No-trade days that stayed in range</span><b>{pct(S.no_trade_correct)}</b></div>
      </div>
      <div className="grid two">
        {active ? <CumulativeChart entries={entries} /> : <div id="cumChart"></div>}
        <div>
          <div className="controls">
            <Seg
              className="trackFilter"
              options={[['all', 'All'], ['CALL', 'Calls'], ['PUT', 'Puts'], ['NONE', 'No trade']]}
              value={filter}
              onChange={setFilter}
            />
          </div>
          <div className="tablewrap">
            <table id="trackTable">
              <thead>
                <tr><th>Date</th><th>Signal</th><th>Close</th><th>Next close</th><th>Result</th><th>Pts</th></tr>
              </thead>
              <tbody>
                {rows.map(e => {
                  const o = e.outcome
                  return (
                    <tr key={e.date}>
                      <td>{e.date}{e.backfilled && <> <span className="mut">bf</span></>}</td>
                      <td><span className={`pill ${PILL[e.bias]}`}>{LABEL[e.bias]}</span></td>
                      <td className="num">{fmt(e.close, 0)}</td>
                      <td className="num">
                        {o ? (
                          <>
                            {fmt(o.next_close, 0)} <span className={pnCls(o.move)}>({o.move >= 0 ? '+' : ''}{fmt(o.move, 0)})</span>
                          </>
                        ) : (
                          <span className="mut">pending</span>
                        )}
                      </td>
                      <td>{o ? o.result : <span className="mut">next session</span>}</td>
                      <td className={`num ${o && o.points > 0 ? 'pos' : o && o.points < 0 ? 'neg' : ''}`}>
                        {o && o.points != null ? fmt(o.points, 1) : '–'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p className="small mut">
        Each signal is graded as a one-day plan on the next session: entry at R1 for calls or S1 for puts, target R2 or S2, and stop at the
        pivot. Points are Nifty index points, not option premium. Daily candles don't show which level was hit first, so a day that touched
        both the stop and the target counts as a loss. Rows marked "bf" were backfilled on the first run using price-based rules only.
      </p>
    </div>
  )
}

function CumulativeChart({ entries }) {
  const chart = useMemo(() => {
    const graded = entries.filter(e => e.outcome && e.bias !== 'NONE').slice().reverse() // oldest first
    if (!graded.length) return null
    let total = 0
    const cum = graded.map(e => (total += e.outcome.points || 0))
    return {
      data: [
        {
          x: graded.map(e => e.date), y: cum, type: 'scatter', mode: 'lines+markers',
          line: { color: C.ion, width: 2 },
          marker: { size: 6, color: graded.map(e => (e.outcome.points > 0 ? C.bull : e.outcome.points < 0 ? C.bear : C.mut)) },
        },
      ],
      layout: {
        ...BASE,
        margin: { l: 50, r: 10, t: 30, b: 40 },
        showlegend: false,
        title: { text: 'Running total of Nifty points', font: { size: 12 } },
        xaxis: { ...AX, type: 'category', nticks: 6 },
        yaxis: { ...AX },
      },
    }
  }, [entries])
  if (!chart) return <div id="cumChart"><p className="mut">No graded trade signals yet. Each signal is graded after the next trading day.</p></div>
  return <Plot id="cumChart" data={chart.data} layout={chart.layout} />
}
