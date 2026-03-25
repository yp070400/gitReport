import { useState } from 'react'

const MEDALS = { 1: '🥇', 2: '🥈', 3: '🥉' }
const CAT_EMOJI = { feature: '✨', bugfix: '🐛', infra: '⚙️', refactor: '♻️', test: '🧪', docs: '📝' }
const CAT_BG = { feature: 'bg-purple-100 text-purple-700', bugfix: 'bg-red-100 text-red-700', infra: 'bg-blue-100 text-blue-700', refactor: 'bg-amber-100 text-amber-700', test: 'bg-green-100 text-green-700', docs: 'bg-slate-100 text-slate-600' }
const CAT_BAR = { feature: 'bg-purple-500', bugfix: 'bg-red-500', infra: 'bg-blue-500', refactor: 'bg-amber-500', test: 'bg-green-500', docs: 'bg-slate-400' }

function tierBadge(tier) {
  const map = {
    'OUTSTANDING': 'bg-yellow-100 text-yellow-800 border-yellow-300',
    'EXCELLENT': 'bg-green-100 text-green-800 border-green-300',
    'GOOD': 'bg-blue-100 text-blue-800 border-blue-300',
    'AVERAGE': 'bg-amber-100 text-amber-800 border-amber-300',
    'LOW': 'bg-red-100 text-red-800 border-red-300',
  }
  return map[tier] || 'bg-slate-100 text-slate-700 border-slate-300'
}

function scoreBarColor(score) {
  if (score >= 8) return 'bg-green-500'
  if (score >= 6) return 'bg-blue-500'
  if (score >= 4) return 'bg-amber-500'
  return 'bg-red-500'
}

export default function DeveloperCard({ dev }) {
  const [showReasoning, setShowReasoning] = useState(false)
  const [showCommits, setShowCommits] = useState(false)

  const sortedCats = Object.entries(dev.categories)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
  const totalCats = sortedCats.reduce((a, [, v]) => a + v, 0) || 1

  const initials = dev.author.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
  const avatarColor = ['bg-blue-500', 'bg-purple-500', 'bg-green-500', 'bg-amber-500', 'bg-pink-500', 'bg-indigo-500']
  const avatarBg = avatarColor[dev.rank % avatarColor.length]

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden hover:shadow-md transition-shadow">

      {/* Card Header */}
      <div className="p-5 border-b border-slate-100">
        <div className="flex items-center gap-4">
          {/* Avatar */}
          <div className={`w-12 h-12 rounded-full ${avatarBg} flex items-center justify-center text-white font-bold text-lg flex-shrink-0`}>
            {initials}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-lg">{MEDALS[dev.rank] || `#${dev.rank}`}</span>
              <h3 className="font-bold text-slate-900 text-base truncate">{dev.author}</h3>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${tierBadge(dev.tier)}`}>
                {dev.tier}
              </span>
            </div>
            {/* Score bar */}
            <div className="flex items-center gap-3 mt-2">
              <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
                <div
                  className={`h-full rounded-full score-bar-fill ${scoreBarColor(dev.impact_score)}`}
                  style={{ width: `${dev.impact_score / 10 * 100}%` }}
                />
              </div>
              <span className="text-sm font-bold text-slate-700 flex-shrink-0">{dev.impact_score.toFixed(1)}/10</span>
            </div>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 mt-4">
          <div className="text-center">
            <div className="text-lg font-bold text-slate-800">{dev.total_commits}</div>
            <div className="text-xs text-slate-400">Commits</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-green-600">+{dev.additions.toLocaleString()}</div>
            <div className="text-xs text-slate-400">Added</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-red-500">-{dev.deletions.toLocaleString()}</div>
            <div className="text-xs text-slate-400">Removed</div>
          </div>
        </div>
      </div>

      <div className="p-5 space-y-5">
        {/* Themes */}
        {dev.themes?.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {dev.themes.map(t => (
              <span key={t} className={`text-xs font-medium px-2.5 py-1 rounded-full capitalize ${CAT_BG[t] || 'bg-slate-100 text-slate-600'}`}>
                {CAT_EMOJI[t] || ''} {t}
              </span>
            ))}
          </div>
        )}

        {/* Category breakdown */}
        {sortedCats.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Work Breakdown</p>
            <div className="space-y-2">
              {sortedCats.map(([cat, cnt]) => {
                const pct = Math.round(cnt / totalCats * 100)
                return (
                  <div key={cat} className="flex items-center gap-2">
                    <span className="text-sm w-4">{CAT_EMOJI[cat] || '•'}</span>
                    <span className="text-xs text-slate-600 capitalize w-16">{cat}</span>
                    <div className="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div className={`h-full rounded-full score-bar-fill ${CAT_BAR[cat] || 'bg-slate-400'}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs text-slate-400 w-10 text-right">{cnt} ({pct}%)</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* AI Summary */}
        {dev.ai_summary && (
          <div className="bg-slate-50 rounded-lg p-3 border-l-4 border-blue-400">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">Impact Summary</p>
            <p className="text-sm text-slate-700 leading-relaxed">{dev.ai_summary}</p>
          </div>
        )}

        {/* Key Contributions */}
        {dev.key_contributions?.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">🔑 Key Contributions</p>
            <ul className="space-y-1.5">
              {dev.key_contributions.map((c, i) => (
                <li key={i} className="flex gap-2 text-sm text-slate-700">
                  <span className="text-slate-300 flex-shrink-0 mt-0.5">•</span>
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Top Files */}
        {dev.top_files?.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">📂 Most Changed Files</p>
            <div className="space-y-1">
              {dev.top_files.slice(0, 5).map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="text-slate-500 font-mono truncate flex-1">{f.filename}</span>
                  <span className="text-green-600 flex-shrink-0">+{f.additions}</span>
                  <span className="text-red-500 flex-shrink-0">-{f.deletions}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* AI Reasoning (collapsible) */}
        {dev.reasoning && (
          <div>
            <button onClick={() => setShowReasoning(!showReasoning)}
              className="flex items-center gap-2 text-xs font-semibold text-slate-400 hover:text-slate-600 uppercase tracking-wide transition-colors">
              <span>{showReasoning ? '▾' : '▸'}</span> 💡 Score Reasoning
            </button>
            {showReasoning && (
              <div className="mt-2 text-sm text-slate-600 leading-relaxed bg-amber-50 rounded-lg p-3 border border-amber-100">
                {dev.reasoning}
              </div>
            )}
          </div>
        )}

        {/* Recent Commits (collapsible) */}
        {dev.recent_commits?.length > 0 && (
          <div>
            <button onClick={() => setShowCommits(!showCommits)}
              className="flex items-center gap-2 text-xs font-semibold text-slate-400 hover:text-slate-600 uppercase tracking-wide transition-colors">
              <span>{showCommits ? '▾' : '▸'}</span> 📝 Recent Commits ({dev.recent_commits.length})
            </button>
            {showCommits && (
              <div className="mt-2 space-y-1.5">
                {dev.recent_commits.map((c, i) => (
                  <div key={i} className="flex gap-2 text-xs">
                    <span className="text-slate-300 flex-shrink-0 font-mono">{c.sha}</span>
                    <span className="text-slate-400 flex-shrink-0">{c.date}</span>
                    <span className="text-slate-600 truncate">{c.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
