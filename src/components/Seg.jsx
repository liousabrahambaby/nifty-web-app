/** Segmented button group: options = [[value, label], ...] */
export default function Seg({ className = '', options, value, onChange }) {
  return (
    <div className={`seg ${className}`}>
      {options.map(([v, label]) => (
        <button key={String(v)} className={v === value ? 'on' : ''} onClick={() => onChange(v)}>
          {label}
        </button>
      ))}
    </div>
  )
}
