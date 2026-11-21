import { useLayoutEffect, useRef, useState } from 'react'
import { fmt, pnCls, biasCls, biasShort } from '../lib/format'

/** Price, quick readouts, and a ladder showing where the close sits among nearby levels. */
export default function Hero({ D }) {
  const L = D.last, S = D.signal, V = D.vix, O = D.option_chain
  return (
    <section className="hero" aria-label="Nifty price and key levels">
      <div className="hero-top">
        <div>
          <div className="sym">{D.symbol}</div>
          <div className="price">{fmt(L.close)}</div>
        </div>
        <div className="chg">
          <span className={pnCls(L.change)}>
            {L.change >= 0 ? '▲' : '▼'} {fmt(Math.abs(L.change))} ({L.change_pct >= 0 ? '+' : ''}
            {L.change_pct}%)
          </span>
        </div>
        <div className="readouts">
          <div className="readout bias">
            <span>Next session</span>
            <b className={biasCls(S.bias)}>{biasShort(S.bias)}</b>
          </div>
          <div className="readout">
            <span>India VIX</span>
            <b className="num">
              {V ? (
                <>
                  {V.value}{' '}
                  {V.change_pct != null && (
                    <span className={`small ${V.change_pct > 0 ? 'neg' : 'pos'}`}>
                      {V.change_pct > 0 ? '+' : ''}
                      {V.change_pct}%
                    </span>
                  )}
                </>
              ) : (
                'n/a'
              )}
            </b>
          </div>
          <div className="readout">
            <span>Put-call ratio</span>
            <b className="num">{O ? O.pcr + (O.stale ? ' (old)' : '') : 'n/a'}</b>
          </div>
        </div>
      </div>
      <Ladder D={D} />
      <div className="ladder-legend">
        <span><i style={{ background: 'var(--bull)' }}></i>Support</span>
        <span><i style={{ background: 'var(--bear)' }}></i>Resistance</span>
        <span><i style={{ background: 'var(--violet)' }}></i>Option-chain level</span>
        <span><i style={{ background: 'var(--ion)' }}></i>Last close</span>
      </div>
    </section>
  )
}

const LABEL_GAP = 62 // min px between labels on the same side, otherwise the label is dropped

function Ladder({ D }) {
  const ref = useRef(null)
  const [width, setWidth] = useState(800)

  useLayoutEffect(() => {
    const el = ref.current
    setWidth(el.clientWidth || 800)
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 800))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const close = D.last.close, lv = D.levels, oc = D.option_chain
  const pts = [['S2', lv.S2, 's'], ['S1', lv.S1, 's'], ['Pivot', lv.Pivot, ''], ['R1', lv.R1, 'r'], ['R2', lv.R2, 'r']]
  if (oc && !oc.stale) pts.push(['Call wall', oc.max_ce_oi_strike, 'w'], ['Put wall', oc.max_pe_oi_strike, 'w'], ['Max pain', oc.max_pain, 'w'])

  const near = pts.filter(p => Math.abs(p[1] / close - 1) < 0.025).sort((a, b) => a[1] - b[1])
  const vals = near.map(p => p[1]).concat(close)
  const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * 0.06 || 50
  const pct = v => ((v - lo + pad) / (hi - lo + 2 * pad)) * 100

  // Alternate labels above/below the track so neighbouring ones don't overlap
  const last = { up: -1e9, down: -1e9 }
  const ticks = near.map(([name, value, kind]) => {
    const x = (pct(value) / 100) * width
    const side = x - last.up >= LABEL_GAP ? 'up' : x - last.down >= LABEL_GAP ? 'down' : null
    if (side) last[side] = x
    return { name, value, kind, side }
  })

  return (
    <div className="ladder" ref={ref} role="img" aria-label="Current price relative to support and resistance levels">
      <div className="track"></div>
      {ticks.map(t => (
        <div
          key={t.name}
          className={`tick ${t.kind} ${t.side || ''}`}
          style={{ left: pct(t.value).toFixed(2) + '%' }}
          title={`${t.name} ${fmt(t.value, 0)}`}
        >
          {t.side && (
            <label>
              {t.name}
              <b>{fmt(t.value, 0)}</b>
            </label>
          )}
        </div>
      ))}
      <div className="marker" style={{ left: pct(close).toFixed(2) + '%' }} title={`Last close ${fmt(close)}`}></div>
    </div>
  )
}
