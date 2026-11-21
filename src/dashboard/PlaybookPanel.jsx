import { Fragment } from 'react'
import { fmt, signed, pnCls } from '../lib/format'

const TAG = { call: 'CE', put: 'PE', wait: 'Wait' }

export default function PlaybookPanel({ D }) {
  const P = D.playbook
  return (
    <>
      <div className="grid main">
        <div className="box">
          {P ? (
            <>
              <p className="small mut" style={{ margin: '0 0 4px' }}>For {P.session}</p>
              <p className="headline">{P.headline}</p>
              <h3>Levels to watch, highest to lowest</h3>
              <WatchTable P={P} />
            </>
          ) : (
            <p className="headline">The playbook appears after the next data update.</p>
          )}
        </div>
        <div className="stack">
          <div className="box">
            <h2>If this happens, do this</h2>
            <div className="scen">
              {P &&
                P.scenarios.map((s, i) => (
                  <div className={`sc ${s.kind}`} key={i}>
                    <span className="tag">{TAG[s.kind]}</span>
                    <div className="when">{s.when}</div>
                    <div className="small" style={{ color: '#C9D0F0' }}>{s.then}</div>
                  </div>
                ))}
            </div>
          </div>
        </div>
      </div>
      <GroundRules />
    </>
  )
}

function WatchTable({ P }) {
  // Insert a "You are here" row where the last close falls in the (descending) list of levels
  const hereAt = P.watch.findIndex(w => w.value < P.close)
  const here = (
    <tr className="here" key="here">
      <td>Last close</td><td className="v">{fmt(P.close, 1)}</td><td className="d">0</td><td>You are here</td>
    </tr>
  )
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="watch">
        <thead>
          <tr><th>Level</th><th>Price</th><th style={{ textAlign: 'right' }}>Distance</th><th>Why it matters</th></tr>
        </thead>
        <tbody>
          {P.watch.map((w, i) => (
            <Fragment key={w.name + i}>
              {i === hereAt && here}
              <tr>
                <td>{w.name}</td>
                <td className="v">{fmt(w.value, 1)}</td>
                <td className={`d ${pnCls(w.dist)}`}>
                  {signed(w.dist)}
                  <br />
                  <span className="small mut">{w.dist_pct >= 0 ? '+' : ''}{w.dist_pct}%</span>
                </td>
                <td className="why">{w.why}</td>
              </tr>
              <tr className="whyrow"><td colSpan={3}>{w.why}</td></tr>
            </Fragment>
          ))}
          {hereAt === -1 && here}
        </tbody>
      </table>
    </div>
  )
}

function GroundRules() {
  return (
    <div className="box" style={{ marginTop: 16 }}>
      <h2>Ground rules for option buyers</h2>
      <div className="tips">
        <div>
          <h3>Before the open</h3>
          <ul>
            <li>Write down your trigger, target and stop from the plan above before 9:15. Don't decide in the heat of the move.</li>
            <li>Check the global cues: GIFT Nifty, US markets overnight, and any big news or results due.</li>
            <li>Decide your size first. Risk no more than 1–2% of your capital on one trade.</li>
          </ul>
        </div>
        <div>
          <h3>During the session</h3>
          <ul>
            <li>Skip the first 15 minutes. Opening moves often reverse.</li>
            <li>Wait for a 15-minute candle to close beyond a level. A quick poke through it often fails.</li>
            <li>Use ATM or one strike in-the-money for direction trades. Cheap far-OTM options rarely pay off.</li>
            <li>Set your stop on the Nifty level, not on the option price. Premiums swing too much to be a reliable stop.</li>
          </ul>
        </div>
        <div>
          <h3>Protecting capital</h3>
          <ul>
            <li>Never add to a losing option position. Time decay works against you every hour.</li>
            <li>Book part of the profit at the first target and trail the rest.</li>
            <li>On expiry day, avoid holding bought options after 1:30 PM unless the trade is well in profit.</li>
            <li>After two losing trades in a day, stop for the day.</li>
          </ul>
        </div>
      </div>
      <h3 style={{ marginTop: 22 }}>What the numbers mean</h3>
      <dl className="gloss">
        <div><dt>Pivot, R1, R2, S1, S2</dt><dd>Levels calculated from the last session's high, low and close. R means resistance above the price, S means support below it.</dd></div>
        <div><dt>Open interest (OI)</dt><dd>The number of option contracts still open at a strike. Large OI shows where option sellers have placed their bets.</dd></div>
        <div><dt>Put-call ratio (PCR)</dt><dd>Total put OI divided by total call OI. Above 1.3 usually means heavy put selling (supportive); below 0.7 means heavy call selling (bearish).</dd></div>
        <div><dt>Max pain</dt><dd>The strike where option buyers as a whole would lose the most at expiry. Nifty often drifts toward it near expiry.</dd></div>
        <div><dt>India VIX</dt><dd>The market's expected volatility over the next 30 days. Higher VIX means bigger expected moves and more expensive options.</dd></div>
        <div><dt>ATR</dt><dd>Average true range: how many points Nifty has typically moved in a day recently.</dd></div>
      </dl>
    </div>
  )
}
