// Demo login only: it keeps casual visitors out but is NOT real security.
// The same key is checked by the small inline scripts in index.html and login.html.
const KEY = 'nc_auth'

export function signIn(remember) {
  sessionStorage.setItem(KEY, '1')
  if (remember) localStorage.setItem(KEY, '1')
}

export function signOut() {
  sessionStorage.removeItem(KEY)
  localStorage.removeItem(KEY)
  location.replace('login.html')
}
