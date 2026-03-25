export default function Header({ onScan, report }) {
  const meta = report?.meta

  return (
    <header className="bg-slate-900 text-white shadow-lg">
      <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">🔬 AI Engineering Impact Analyzer</h1>
          {meta && (
            <p className="text-slate-400 text-sm mt-0.5">
              {meta.repos.join(', ')} · {meta.since} → {meta.until} · {meta.source}
            </p>
          )}
        </div>
        <button
          onClick={onScan}
          className="bg-blue-500 hover:bg-blue-600 active:bg-blue-700 text-white font-semibold px-4 py-2 rounded-lg transition-colors text-sm"
        >
          ＋ New Scan
        </button>
      </div>
    </header>
  )
}
