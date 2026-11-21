import { useState } from 'react'

// ---- Settings: edit these two lines ----
const KITE_API_KEY = 'PASTE_YOUR_KITE_API_KEY_HERE' // the API key only. NEVER put the API secret here.
const REPO = '' // leave empty to detect it (works for <user>.github.io/<repo>). Otherwise e.g. 'yourname/nifty-dashboard'
// -----------------------------------------

// Read Kite's redirect once, then strip the one-time token from the address bar and history.
const query = new URLSearchParams(location.search)
const status = query.get('status')
const token = status === 'success' && query.get('request_token') ? query.get('request_token').replace(/[^A-Za-z0-9]/g, '') : null
const failedStatus = status && status !== 'success' ? status.replace(/[^a-z_ ]/gi, '') : null
if (token) history.replaceState(null, '', location.pathname)

const repo = REPO || (location.hostname.endsWith('.github.io') ? `${location.hostname.split('.')[0]}/${location.pathname.split('/')[1]}` : '')
const actionsUrl = repo ? `https://github.com/${repo}/actions/workflows/update.yml` : 'https://github.com'

const Logo = () => <img src="icons/icon.svg" alt="" width="48" height="48" />

export default function KitePage() {
  return <main className="card">{token ? <Success token={token} /> : failedStatus !== null ? <Failed status={failedStatus} /> : <Start />}</main>
}

function Success({ token }) {
  const [copyLabel, setCopyLabel] = useState('Copy code')
  async function copy() {
    try {
      await navigator.clipboard.writeText(token)
      setCopyLabel('Copied')
    } catch {
      setCopyLabel('Press and hold the code to copy it')
    }
  }
  return (
    <>
      <Logo />
      <h1 className="ok">Logged in to Kite</h1>
      <p>Here's today's one-time code. It expires in about 5 minutes, so finish the steps now.</p>
      <div className="code">{token}</div>
      <button className="btn" onClick={copy}>{copyLabel}</button>
      <ol style={{ marginTop: 18 }}>
        <li>Tap <b>Open GitHub</b> below.</li>
        <li>Tap <b>Run workflow</b>, set mode to <b>premarket</b>, and paste the code into <b>Kite request token</b>.</li>
        <li>Tap the green <b>Run workflow</b> button. The forecast with GIFT Nifty is ready in about 2 minutes.</li>
      </ol>
      <a className="btn alt" href={actionsUrl} target="_blank" rel="noopener">Open GitHub</a>
      <a className="back" href="index.html">Back to the cockpit</a>
    </>
  )
}

function Failed({ status }) {
  return (
    <>
      <Logo />
      <h1 className="bad">Kite login didn't finish</h1>
      <p>Kite returned "{status}". Try logging in again.</p>
      <a className="btn" href="kite.html">Try again</a>
    </>
  )
}

function Start() {
  const ist = new Date(Date.now() + 330 * 60000)
  const early = ist.getUTCHours() * 60 + ist.getUTCMinutes() < 7 * 60 + 35
  const configured = /^[a-z0-9]{8,}$/i.test(KITE_API_KEY)
  return (
    <>
      <Logo />
      <h1>Add GIFT Nifty to today's forecast</h1>
      <p>Kite needs a fresh login every morning. It takes about a minute: log in, copy a code, paste it into GitHub.</p>
      {early && <div className="note">Kite resets logins at 7:30 AM and issues new ones from 7:35 AM. Logging in before 7:35 won't work for today.</div>}
      {configured ? (
        <a className="btn" href={`https://kite.zerodha.com/connect/login?v=3&api_key=${encodeURIComponent(KITE_API_KEY)}`}>Log in with Kite</a>
      ) : (
        <div className="note">
          Setup needed: open <b>src/kite/KitePage.jsx</b> in your GitHub repo and paste your Kite <b>API key</b> (not the secret) into the
          KITE_API_KEY line.
        </div>
      )}
      <a className="back" href="index.html">Back to the cockpit</a>
    </>
  )
}
