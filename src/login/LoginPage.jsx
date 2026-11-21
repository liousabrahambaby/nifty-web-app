import { useRef, useState } from 'react'
import { signIn } from '../lib/auth'

/*
  DEMO LOGIN ONLY. This page runs entirely in the browser, so it keeps casual
  visitors out but is NOT real security: anyone can read the source or open
  data.json directly. Change the credentials below:
    USERNAME  – plain text
    PASS_HASH – SHA-256 of the password. Generate one in a browser console:
      crypto.subtle.digest('SHA-256', new TextEncoder().encode('newpass'))
        .then(b => console.log([...new Uint8Array(b)].map(x => x.toString(16).padStart(2,'0')).join('')))
*/
const USERNAME = 'admin'
const PASS_HASH = '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9' // admin123

async function sha256(text) {
  if (!window.crypto || !crypto.subtle) return null // needs https or localhost
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(buf)].map(x => x.toString(16).padStart(2, '0')).join('')
}

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState('')
  const passwordRef = useRef(null)

  async function onSubmit(e) {
    e.preventDefault()
    const hash = await sha256(password)
    if (hash === null) {
      setError('Open this page over https (or localhost) to sign in.')
      return
    }
    if (username.trim() === USERNAME && hash === PASS_HASH) {
      signIn(remember)
      location.replace('index.html')
    } else {
      setError('Wrong username or password. Try again.')
      setPassword('')
      passwordRef.current.focus()
    }
  }

  return (
    <form className="card" onSubmit={onSubmit} autoComplete="on">
      <img className="logo" src="icons/icon.svg" alt="" width="56" height="56" />
      <h1 className="brand">NIFTY<span>/</span>COCKPIT</h1>
      <p className="sub">Sign in to see today's analysis</p>
      <label htmlFor="u">Username</label>
      <input type="text" id="u" name="username" autoComplete="username" required autoFocus value={username} onChange={e => setUsername(e.target.value)} />
      <label htmlFor="p">Password</label>
      <input
        type="password" id="p" name="password" autoComplete="current-password" required
        ref={passwordRef} value={password} onChange={e => setPassword(e.target.value)}
      />
      <label className="row">
        <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} /> Keep me signed in on this device
      </label>
      <button type="submit">Sign in</button>
      <p className="err" role="alert">{error}</p>
      <p className="demo">Demo login. It keeps casual visitors out but isn't real security.</p>
    </form>
  )
}
