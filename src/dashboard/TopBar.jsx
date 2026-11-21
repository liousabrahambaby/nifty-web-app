import { signOut } from '../lib/auth'
import { nextRun, istLabel } from '../lib/format'

function stampText(D, status) {
  if (status === 'missing') return { title: 'No data yet', sub: 'Run the "Update Nifty data" workflow in GitHub Actions', late: false }
  if (!D) return { title: 'Loading…', sub: '', late: false }

  const up = new Date(D.updated_iso || Date.now())
  const due = nextRun(up)
  const now = new Date()
  const hours = Math.round((now - up) / 3600000)
  const late = now - due > 2 * 3600000 // more than 2h past the scheduled run
  const asOf = new Date(D.as_of).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
  return {
    title: `Last updated ${D.updated.replace(' IST', '')}`,
    sub: late ? `Update overdue since ${istLabel(due)}. Check the Actions tab.` : `Market data from ${asOf}. Next update ${istLabel(nextRun(now))}`,
    tooltip: `Updated ${hours < 1 ? 'less than an hour' : hours + ' hours'} ago`,
    late,
  }
}

export default function TopBar({ D, status }) {
  const s = stampText(D, status)
  return (
    <div className="topbar">
      <div className="topbar-in">
        <div className="brand">
          <img src="icons/icon.svg" alt="" width="30" height="30" />
          NIFTY<span>/</span>COCKPIT
        </div>
        <div className="stamp" title={s.tooltip || "When this page's data was last refreshed"}>
          <span className={`dot${s.late ? ' late' : ''}`}></span>
          <div>
            <b>{s.title}</b>
            <span className="small mut">{s.sub}</span>
          </div>
        </div>
        <button className="signout" onClick={signOut}>
          Sign out
        </button>
      </div>
    </div>
  )
}
