import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist-min'
import { CFG } from '../lib/chartTheme'

/** Plotly draws into a div React owns. Pass memoised `data`/`layout` so it only redraws when they change. */
export default function Plot({ id, data, layout }) {
  const ref = useRef(null)

  useEffect(() => {
    Plotly.react(ref.current, data, layout, CFG)
  }, [data, layout])

  useEffect(() => {
    const el = ref.current
    return () => Plotly.purge(el)
  }, [])

  return <div id={id} ref={ref} />
}
