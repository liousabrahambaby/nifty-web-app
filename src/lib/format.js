export const fmt = (n, d = 2) => (n == null ? '–' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d }))

/** "+123" / "−123" with a real minus sign */
export const signed = (n, d = 0) => `${n >= 0 ? '+' : '−'}${fmt(Math.abs(n), d)}`

export const pctTxt = v => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}%`

/** colour class for a % move, ignoring tiny ones */
export const signCls = v => (v == null ? '' : Math.abs(v) < 0.15 ? '' : v > 0 ? 'pos' : 'neg')

export const pnCls = v => (v >= 0 ? 'pos' : 'neg')

/** signal bias label -> css class / short label */
export const biasCls = b => (b.startsWith('CALL') ? 'call' : b.startsWith('PUT') ? 'put' : 'none')
export const biasShort = b => (b.startsWith('CALL') ? 'Call bias' : b.startsWith('PUT') ? 'Put bias' : 'No trade')

export function ago(iso) {
  const m = Math.round((Date.now() - new Date(iso)) / 60000)
  return m < 60 ? `${Math.max(1, m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
}

const IST_OFFSET = 330 * 60000

/** next weekday 4:00 PM IST after `from` (NSE holidays not included) */
export function nextRun(from) {
  const ist = new Date(from.getTime() + IST_OFFSET) // shift to IST wall-clock, read with UTC getters
  const t = new Date(Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate(), 16, 0))
  if (ist >= t) t.setUTCDate(t.getUTCDate() + 1)
  while ([0, 6].includes(t.getUTCDay())) t.setUTCDate(t.getUTCDate() + 1)
  return new Date(t.getTime() - IST_OFFSET)
}

export const istLabel = d =>
  d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
