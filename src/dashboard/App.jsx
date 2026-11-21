import { useEffect, useState } from 'react'
import TopBar from './TopBar.jsx'
import Hero from './Hero.jsx'
import Alerts from './Alerts.jsx'
import Premarket from './Premarket.jsx'
import GlobalMarkets from './GlobalMarkets.jsx'
import News from './News.jsx'
import Tabs, { Panel } from './Tabs.jsx'
import DashboardPanel from './DashboardPanel.jsx'
import PlaybookPanel from './PlaybookPanel.jsx'
import OptionsPanel from './OptionsPanel.jsx'
import TrackPanel from './TrackPanel.jsx'

const TABS = [
  ['dash', 'Dashboard'],
  ['tips', 'Levels & tips'],
  ['opt', 'Options & VIX'],
  ['track', 'Track record'],
]

const DEFAULT_OVERLAYS = { sma20: true, sma50: true, sma200: false, bb: false, lv: true, oi: true, sig: true }

export default function App() {
  const [D, setD] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | missing
  const [tab, setTab] = useState('dash')
  // Shared by the price chart and the VIX chart: a number of daily candles (0 = all) or an intraday view key ('1d', '5d')
  const [days, setDays] = useState(132)
  const [overlays, setOverlays] = useState(DEFAULT_OVERLAYS)

  useEffect(() => {
    fetch('data.json?t=' + Date.now())
      .then(r => {
        if (!r.ok) throw new Error(r.status)
        return r.json()
      })
      .then(d => {
        setD(d)
        setStatus('ready')
      })
      .catch(() => setStatus('missing'))
  }, [])

  return (
    <>
      <TopBar D={D} status={status} />
      <div className="wrap">
        {D ? (
          <>
            <Hero D={D} />
            <Alerts D={D} />
            <Premarket D={D} />
            <GlobalMarkets D={D} />
            <News D={D} />
            <Tabs tabs={TABS} value={tab} onChange={setTab} />
            <Panel id="dash" active={tab === 'dash'}>
              <DashboardPanel D={D} active={tab === 'dash'} days={days} setDays={setDays} overlays={overlays} setOverlays={setOverlays} />
            </Panel>
            <Panel id="tips" active={tab === 'tips'}>
              <PlaybookPanel D={D} />
            </Panel>
            <Panel id="opt" active={tab === 'opt'}>
              <OptionsPanel D={D} active={tab === 'opt'} days={days} />
            </Panel>
            <Panel id="track" active={tab === 'track'}>
              <TrackPanel D={D} active={tab === 'track'} />
            </Panel>
          </>
        ) : (
          status === 'missing' && (
            <div className="box">
              <h2>No data yet</h2>
              <p className="mut" style={{ margin: 0 }}>
                data.json wasn't found. Run the "Update Nifty data" workflow in GitHub Actions, or locally run{' '}
                <code>python analyze.py --demo</code> in this folder and reload.
              </p>
            </div>
          )
        )}
      </div>
      <footer>
        This is an educational tool, not investment advice. Signals come from simple rules and are often wrong. Buying options can lose the
        whole premium quickly, and SEBI's study found most individual F&amp;O traders lose money. Option-chain data comes from NSE and can be
        missing or delayed. Talk to a SEBI-registered adviser before trading.
      </footer>
    </>
  )
}
