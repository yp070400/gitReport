const MEDALS = { 1: '🥇', 2: '🥈', 3: '🥉' }

function scoreColor(score) {
  if (score >= 8) return 'text-green-600 bg-green-50 border-green-200'
  if (score >= 6) return 'text-blue-600 bg-blue-50 border-blue-200'
  if (score >= 4) return 'text-amber-600 bg-amber-50 border-amber-200'
  return 'text-red-600 bg-red-50 border-red-200'
}

function ScoreBar({ score }) {
  const pct = score / 10 * 100
  const color = score >= 8 ? 'bg-green-500' : score >= 6 ? 'bg-blue-500' : score >= 4 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
      <div className={`h-full rounded-full score-bar-fill ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export default function Leaderboard({ developers }) {
  return (
    <section>
      <h2 className="text-xl font-bold text-slate-800 mb-4">🏆 Leaderboard</h2>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3 w-10">Rank</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3">Developer</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3">Score</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3 hidden md:table-cell">Progress</th>
              <th className="text-right text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3 hidden sm:table-cell">Commits</th>
              <th className="text-right text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3 hidden lg:table-cell">Lines</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wide px-5 py-3 hidden xl:table-cell">Focus</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {developers.map(dev => (
              <tr key={dev.author} className="hover:bg-slate-50 transition-colors">
                <td className="px-5 py-3.5 text-xl">{MEDALS[dev.rank] || `#${dev.rank}`}</td>
                <td className="px-5 py-3.5">
                  <span className="font-semibold text-slate-800">{dev.author}</span>
                  {dev.is_high_impact && <span className="ml-2 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">High Impact</span>}
                  {dev.is_low_value && <span className="ml-2 text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-medium">Low Value</span>}
                </td>
                <td className="px-5 py-3.5">
                  <span className={`text-sm font-bold px-2 py-0.5 rounded border ${scoreColor(dev.impact_score)}`}>
                    {dev.impact_score.toFixed(1)}
                  </span>
                </td>
                <td className="px-5 py-3.5 hidden md:table-cell w-40">
                  <ScoreBar score={dev.impact_score} />
                </td>
                <td className="px-5 py-3.5 text-sm text-slate-600 text-right hidden sm:table-cell">{dev.total_commits}</td>
                <td className="px-5 py-3.5 text-sm hidden lg:table-cell text-right">
                  <span className="text-green-600">+{dev.additions.toLocaleString()}</span>
                  <span className="text-slate-300 mx-1">/</span>
                  <span className="text-red-500">-{dev.deletions.toLocaleString()}</span>
                </td>
                <td className="px-5 py-3.5 hidden xl:table-cell">
                  <span className="text-xs text-slate-500 capitalize">{dev.dominant_category}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
