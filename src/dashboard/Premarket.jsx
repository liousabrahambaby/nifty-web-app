import { fmt, signed, pctTxt, signCls } from '../lib/format'

export default function Premarket({ D }) {
  const PM = D.premarket
  const P = PM && PM.prediction
  const ready = !!(PM && PM.status === 'ready' && P)
  const sub = !PM ? '' : ready ? `Made ${P.made_at}` : PM.next_run ? `Next forecast ${PM.next_run}` : ''

  return (
    <section className="pm" aria-labelledby="pmTitle">
      <div className="alerts-head">
        <h2 id="pmTitle">Opening forecast</h2>
        <span className="small mut">{sub}</span>
      </div>
      <div className="pm-grid">
        {!PM ? (
          <div className="gapcard">
            <p className="mut">The opening forecast appears after the next data update.</p>
          </div>
        ) : (
          <>
            {ready ? <ForecastCard P={P} /> : <WaitingCard PM={PM} />}
            <ForecastDetail PM={PM} ready={ready} />
          </>
        )}
      </div>
    </section>
  )
}

function ForecastCard({ P }) {
  const dir = Math.abs(P.pct) < 0.15 ? 'flat' : P.pct > 0 ? 'up' : 'down'
  return (
    <div className={`gapcard ${dir}`}>
      <div className="small mut">Nifty opening for {P.for_date}</div>
      <div className="gap-call">{P.call === 'Flat open' ? 'Flat open likely' : P.call + ' likely'}</div>
      <div className="gap-nums">
        <div><span>Expected gap</span><b className={signCls(P.pct)}>{signed(P.pts)} pts</b></div>
        <div><span>In percent</span><b className={signCls(P.pct)}>{pctTxt(P.pct)}</b></div>
        <div><span>Expected open near</span><b>{fmt(P.open_est, 0)}</b></div>
      </div>
      <p>{P.meaning}</p>
      {P.agreement && <span className="agree">{P.agreement}</span>}
    </div>
  )
}

function WaitingCard({ PM }) {
  const last = (PM.history || []).find(h => h.actual_pct != null)
  return (
    <div className="gapcard wait">
      <div className="small mut">Next forecast</div>
      <div className="gap-call" style={{ fontSize: 'clamp(24px,4vw,34px)' }}>{PM.next_run || 'Tomorrow, about 8:15 AM IST'}</div>
      <p>
        The forecast is made before the market opens, using GIFT Nifty (if connected) and how US futures and Asian markets have moved since
        Nifty closed.
      </p>
      {last && (
        <p style={{ marginTop: 14 }}>
          <b>Last forecast, {last.date}:</b> {last.call} ({pctTxt(last.pct)}). Actual: {last.actual_call} ({pctTxt(last.actual_pct)}), open{' '}
          {fmt(last.actual_open, 0)}. <b className={last.right_direction ? 'pos' : 'neg'}>{last.right_direction ? 'Right call' : 'Missed'}</b>
        </p>
      )}
    </div>
  )
}

function ForecastDetail({ PM, ready }) {
  const P = PM.prediction, M = PM.model, S = PM.summary || {}
  const rows = (PM.history || []).slice(0, 6)
  return (
    <div className="box">
      <h2>{ready ? 'How it was worked out' : 'About the forecast'}</h2>
      {ready &&
        P.methods.map(m => (
          <div className="method" key={m.name}>
            <div className="method-top">
              <span>
                {m.name}
                {m.name === P.method ? ' (used)' : ''}
              </span>
              <b className={signCls(m.pct)}>{pctTxt(m.pct)}</b>
            </div>
            <p>{m.detail}</p>
          </div>
        ))}
      {ready && !P.gift && (
        <div className="note" style={{ marginTop: 10 }}>
          GIFT Nifty couldn't be fetched from NSE IX this morning, so this forecast uses global markets only. It's fetched automatically and
          will be tried again next run.{' '}
          <a href="kite.html" style={{ display: 'inline-block', marginTop: 6, fontWeight: 600, color: 'var(--ion)' }}>
            Use Kite instead (optional)
          </a>
        </div>
      )}
      {M && (
        <p className="small mut">
          Model fitted on {M.n} sessions: opening gap ≈ {M.b.toFixed(2)} × S&amp;P 500 move since Nifty closed. It got the direction right{' '}
          {M.direction_hit}% of the time, with a typical error of {M.mae}%.
        </p>
      )}
      <h3>Forecast track record</h3>
      <div className="tiles" style={{ marginBottom: 6 }}>
        <div className="tile"><span>Forecasts graded</span><b>{S.graded ?? 0}</b></div>
        <div className="tile"><span>Right direction</span><b>{S.hit_rate != null ? S.hit_rate + '%' : '–'}</b></div>
        <div className="tile"><span>Average miss</span><b>{S.avg_error_pts != null ? fmt(S.avg_error_pts, 0) + ' pts' : '–'}</b></div>
      </div>
      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="hist">
            <thead>
              <tr><th>Date</th><th>Forecast</th><th>Actual</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map(h => (
                <tr key={h.date}>
                  <td>{h.date}</td>
                  <td className={signCls(h.pct)}>{h.call} {pctTxt(h.pct)}</td>
                  <td>
                    {h.actual_pct != null ? <span className={signCls(h.actual_pct)}>{pctTxt(h.actual_pct)}</span> : <span className="mut">after open</span>}
                  </td>
                  <td>{h.actual_pct != null && (h.right_direction ? <span className="pos">✓</span> : <span className="neg">✗</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
