import { useRef } from 'react'

/** Accessible tab list: click, or Left/Right arrow keys to move between tabs. */
export default function Tabs({ tabs, value, onChange }) {
  const refs = useRef({})

  const onKeyDown = (e, i) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key]
    if (!step) return
    const [id] = tabs[(i + step + tabs.length) % tabs.length]
    refs.current[id].focus()
    onChange(id)
  }

  return (
    <nav className="tabs" role="tablist" aria-label="Sections">
      {tabs.map(([id, label], i) => (
        <button
          key={id}
          ref={el => (refs.current[id] = el)}
          className="tab"
          role="tab"
          id={`t-${id}`}
          aria-controls={`p-${id}`}
          aria-selected={id === value}
          tabIndex={id === value ? 0 : -1}
          onClick={() => onChange(id)}
          onKeyDown={e => onKeyDown(e, i)}
        >
          {label}
        </button>
      ))}
    </nav>
  )
}

/** Panels stay mounted (so their filters keep their state); charts inside only mount while active. */
export function Panel({ id, active, children }) {
  return (
    <section className="panel" id={`p-${id}`} role="tabpanel" aria-labelledby={`t-${id}`} hidden={!active}>
      {children}
    </section>
  )
}
