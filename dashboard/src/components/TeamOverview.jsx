const CATEGORY_COLORS = {
  feature: 'bg-purple-500',
  bugfix: 'bg-red-500',
  infra: 'bg-blue-500',
  refactor: 'bg-amber-500',
  test: 'bg-green-500',
  docs: 'bg-slate-400',
}

const CATEGORY_EMOJI = {
  feature: '✨', bugfix: '🐛', infra: '⚙️', refactor: '♻️', test: '🧪', docs: '📝',
}

export default function TeamOverview({ team, meta }) {
  const totalCats = Object.values(team.categories).reduce((a, b) => a + b, 0) || 1
  const sortedCats = Object.entries(team.categories)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])

  const scoreColor = team.avg_score >= 8 ? 'text-green-600' : team.avg_score >= 6 ? 'text-blue-600' : team.avg_score >= 4 ? 'text-amber-600' : 'text-red-600'

  return (
    <section>
      <h2 className="text-xl font-bold text-slate-800 mb-4">🏢 Team Overview</h2>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
        {[
          { label: 'Commits', value: team.total_commits, icon: '📝' },
          { label: 'Contributors', value: team.contributors, icon: '👥' },
          { label: 'Lines Added', value: `+${team.total_additions.toLocaleString()}`, icon: '➕', cls: 'text-green-600' },
          { label: 'Lines Removed', value: `-${team.total_deletions.toLocaleString()}`, icon: '➖', cls: 'text-red-500' },
          { label: 'Avg Score', value: `${team.avg_score}/10`, icon: '⭐', cls: scoreColor },
          { label: 'High Impact', value: team.high_impact_count, icon: '🌟', cls: 'text-amber-600' },
        ].map(({ label, value, icon, cls }) => (
          <div key={label} className="bg-white rounded-xl border border-slate-200 p-4 text-center shadow-sm">
            <div className="text-2xl mb-1">{icon}</div>
            <div className={`text-xl font-bold ${cls || 'text-slate-800'}`}>{value}</div>
            <div className="text-xs text-slate-400 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Category distribution */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-600 mb-4 uppercase tracking-wide">Work Distribution</h3>
        <div className="space-y-3">
          {sortedCats.map(([cat, cnt]) => {
            const pct = Math.round(cnt / totalCats * 100)
            return (
              <div key={cat} className="flex items-center gap-3">
                <span className="text-base w-5">{CATEGORY_EMOJI[cat] || '•'}</span>
                <span className="text-sm font-medium text-slate-700 w-20 capitalize">{cat}</span>
                <div className="flex-1 bg-slate-100 rounded-full h-2.5 overflow-hidden">
                  <div
                    className={`h-full rounded-full score-bar-fill ${CATEGORY_COLORS[cat] || 'bg-slate-400'}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-sm text-slate-500 w-16 text-right">{cnt} ({pct}%)</span>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
