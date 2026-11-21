import { useEffect, useRef, useState } from 'react'
import { fmt, ago } from '../lib/format'

const MARK = { positive: '▲', negative: '▼', neutral: '•' }
const WORD = { positive: 'Likely positive', negative: 'Likely negative', neutral: 'Neutral' }

export default function News({ D }) {
  const N = D.news
  return (
    <section className="newsblock" aria-labelledby="newsTitle">
      <div className="alerts-head">
        <h2 id="newsTitle">News that could move the market</h2>
        <span className="small mut">{N && `Refreshed ${N.updated}`}</span>
      </div>
      <div className="news-grid">
        {N && <Flows F={N.fii_dii} />}
        <div className="box news">
          <Headlines items={N ? N.items || [] : null} />
          <p className="small mut" style={{ margin: '10px 0 0' }}>
            Headlines from Google News, Economic Times and Mint; tap one to read it at the source. The ▲ ▼ tags are an automatic guess from the
            headline's wording about whether it's good or bad for Indian stocks, and can be wrong.
          </p>
        </div>
      </div>
    </section>
  )
}

function Flows({ F }) {
  if (!F) {
    return (
      <div className="box flows">
        <h2>Money flows</h2>
        <p className="small mut">
          NSE didn't return FII/DII figures this time. They often block cloud servers; running the update from your own computer usually fixes
          it.
        </p>
      </div>
    )
  }
  const max = Math.max(F.fii.buy, F.fii.sell, F.dii.buy, F.dii.sell)
  const f = F.fii.net, d = F.dii.net
  const read =
    f < 0 && d > 0
      ? d >= -f
        ? 'Foreign funds sold, but domestic funds bought even more. Local buying is cushioning the market.'
        : 'Foreign funds sold more than domestic funds bought. Net selling pressure on the market.'
      : f > 0 && d < 0
        ? 'Foreign funds are buying while domestic funds book profits. Foreign buying usually lifts large caps like Nifty stocks.'
        : f > 0 && d > 0
          ? 'Both foreign and domestic funds were buyers. A strong supportive sign.'
          : 'Both foreign and domestic funds were sellers. A weak sign for the market.'

  return (
    <div className="box flows">
      <h2>Money flows</h2>
      <p className="small mut" style={{ margin: '-6px 0 4px' }}>Cash market, {F.date || 'last session'}</p>
      <Flow name="Foreign investors (FII/FPI)" x={F.fii} max={max} />
      <Flow name="Domestic institutions (DII)" x={F.dii} max={max} />
      <p className="flow-read">{read}</p>
    </div>
  )
}

function Flow({ name, x, max }) {
  return (
    <div className="flow">
      <div className="flow-top">
        <span>{name} net</span>
        <b className={x.net >= 0 ? 'pos' : 'neg'}>
          {x.net >= 0 ? '+' : '−'}₹{fmt(Math.abs(x.net), 0)} cr
        </b>
      </div>
      <div className="flow-bars">
        <div>Buy<i style={{ width: `${(x.buy / max) * 100}%`, background: 'var(--bull)' }}></i><em>₹{fmt(x.buy, 0)}</em></div>
        <div>Sell<i style={{ width: `${(x.sell / max) * 100}%`, background: 'var(--bear)' }}></i><em>₹{fmt(x.sell, 0)}</em></div>
      </div>
    </div>
  )
}

// Headline links come from outside RSS feeds: only allow real web links
const safeHref = url => (/^https?:\/\//i.test(url || '') ? url : undefined)

function Headlines({ items }) {
  const [topic, setTopic] = useState('All')
  const listRef = useRef(null)
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = 0
  }, [topic])

  if (!items) {
    return (
      <ul className="news-list" aria-label="Headlines, scrollable">
        <li><span></span><span className="mut">Headlines appear after the next data update.</span></li>
      </ul>
    )
  }

  const topics = ['All', ...new Set(items.map(i => i.topic))]
  const current = topics.includes(topic) ? topic : 'All'
  const list = items.filter(i => current === 'All' || i.topic === current)

  return (
    <>
      <div className="chips" role="group" aria-label="Filter news by topic">
        {topics.map(t => (
          <button key={t} className={t === current ? 'on' : ''} onClick={() => setTopic(t)}>
            {t}
            <span>{t === 'All' ? items.length : items.filter(i => i.topic === t).length}</span>
          </button>
        ))}
      </div>
      <ul className="news-list" ref={listRef} tabIndex={0} aria-label="Headlines, scrollable">
        {list.length ? (
          list.map((i, k) => (
            <li key={i.link || k}>
              <span className={`t ${i.tone}`} title={`${WORD[i.tone]} for Indian stocks`} aria-label={WORD[i.tone]}>
                {MARK[i.tone]}
              </span>
              <div>
                <a href={safeHref(i.link)} target="_blank" rel="noopener noreferrer">{i.title}</a>
                <div className="meta">
                  {i.source}
                  {i.source ? ', ' : ''}
                  {ago(i.time)} <span className="topic">{i.topic}</span>
                </div>
              </div>
            </li>
          ))
        ) : (
          <li><span></span><span className="mut">No headlines came back in the last update. They'll be fetched again at the next run.</span></li>
        )}
      </ul>
    </>
  )
}
