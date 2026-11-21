import { useState } from 'react'
import { fmt } from '../lib/format'

const direction = kind => (/Breakout|up/i.test(kind) && !/down/i.test(kind) ? 'up' : /Breakdown/i.test(kind) ? 'down' : '')

export default function Alerts({ D }) {
  const [open, setOpen] = useState(false)
  const A = D.alerts || []
  const highs = A.filter(a => a.severity === 'high').length
  const shown = open ? A : A.slice(0, 3)

  return (
    <section className="alerts" aria-labelledby="alertsTitle">
      <div className="alerts-head">
        <h2 id="alertsTitle">Market alerts</h2>
        {A.length > 0 && (
          <span className="small mut">
            {A.length} for {D.playbook ? D.playbook.session : 'the next session'}
            {highs ? `, ${highs} high priority` : ''}
          </span>
        )}
      </div>
      <div className="alert-list">
        {A.length === 0 ? (
          <p className="mut">Alerts appear after the next data update.</p>
        ) : (
          shown.map((a, i) => (
            <article key={i} className={`alert ${a.severity}`}>
              <div className={`kind ${direction(a.kind)}`}>
                {a.kind}
                {a.severity === 'high' ? ', high priority' : ''}
              </div>
              <h3>{a.title}</h3>
              <p>{a.detail}</p>
              {a.levels.length > 0 && (
                <div className="lv">
                  {a.levels.map((v, j) => (
                    <span key={j}>{fmt(v, 0)}</span>
                  ))}
                </div>
              )}
            </article>
          ))
        )}
      </div>
      {A.length > 3 && (
        <button className="more" onClick={() => setOpen(o => !o)}>
          {open ? 'Show fewer alerts' : `Show all ${A.length} alerts`}
        </button>
      )}
    </section>
  )
}
