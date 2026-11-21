import Seg from '../components/Seg.jsx'
import PriceChart from './PriceChart.jsx'
import { fmt, biasCls } from '../lib/format'

const RANGES = [['1d', '1D'], ['5d', '5D'], [22, '1M'], [66, '3M'], [132, '6M'], [252, '1Y'], [0, 'All']]
const OVERLAYS = [
  ['sma20', 'SMA 20'],
  ['sma50', 'SMA 50'],
  ['sma200', 'SMA 200'],
  ['bb', 'Bollinger'],
  ['lv', 'Pivots'],
  ['oi', 'OI walls'],
  ['sig', 'Past signals'],
]

export default function DashboardPanel({ D, active, days, setDays, overlays, setOverlays }) {
  return (
    <div className="grid main">
      <div className="box">
        <div className="controls">
          <Seg className="ranges" options={RANGES} value={days} onChange={setDays} />
        </div>
        <div className="controls">
          {OVERLAYS.map(([key, label]) => (
            <label className="tog" key={key}>
              <input type="checkbox" checked={overlays[key]} onChange={e => setOverlays(o => ({ ...o, [key]: e.target.checked }))} /> {label}
            </label>
          ))}
        </div>
        {/* charts can't measure their size inside a hidden tab, so only mount while visible */}
        {active && <PriceChart D={D} days={days} overlays={overlays} />}
      </div>

      <div className="stack">
        <SignalBox D={D} />
        <div className="box">
          <h2>Expected move</h2>
          <table className="kv">
            <tbody>
              <tr><td>Range from ATR</td><td>{fmt(D.expected_range[0], 0)} to {fmt(D.expected_range[1], 0)}</td></tr>
              <tr><td>Move implied by VIX</td><td>{D.vix ? `± ${fmt(D.vix.day_move, 0)} pts` : 'n/a'}</td></tr>
            </tbody>
          </table>
        </div>
        <Backtest b={D.backtest} />
      </div>
    </div>
  )
}

function SignalBox({ D }) {
  const S = D.signal, P = D.playbook
  const needle = Math.min(100, Math.max(0, ((S.score + 6.5) / 13) * 100))
  return (
    <div className={`signal ${biasCls(S.bias)}`}>
      <div className="small mut">Plan for <span>{P ? P.session : 'the next session'}</span></div>
      <div className="bias-name">{S.bias}</div>
      <div className="small mut">
        Signal strength <b className="num" style={{ color: 'var(--txt)' }}>{S.score}</b> on a scale of −6.5 to +6.5
      </div>
      <div className="meter"><span style={{ left: `calc(${needle}% - 2px)` }}></span></div>
      <table className="kv">
        <tbody>
          {Object.entries(S.plan).map(([k, v]) => (
            <tr key={k}>
              <td>{k[0].toUpperCase() + k.slice(1)}</td>
              <td style={{ fontFamily: 'var(--body)', fontSize: 13 }}>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="reasons">
        {S.reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  )
}

function Backtest({ b }) {
  const row = (name, x) => (
    <tr>
      <td>{name} ({x.signals})</td>
      <td>1d {x.hit_1d ?? '–'}%, 5d {x.hit_5d ?? '–'}%</td>
    </tr>
  )
  return (
    <div className="box">
      <h2>Rule backtest, 2 years</h2>
      <table className="kv">
        <tbody>
          {row('Call signals', b.call)}
          {row('Put signals', b.put)}
        </tbody>
      </table>
      <p className="small mut" style={{ margin: '8px 0 0' }}>
        How often the market moved the way the signal said. For comparison, {b.base_up_days_pct}% of all days closed higher. {b.note}.
      </p>
    </div>
  )
}
