import { useState } from 'react'

function RepoList({ repos, onChange, placeholder, label }) {
  function add() { onChange([...repos, '']) }
  function remove(i) { onChange(repos.filter((_, idx) => idx !== i)) }
  function update(i, val) { onChange(repos.map((r, idx) => idx === i ? val : r)) }

  return (
    <div>
      <label className="block text-sm font-semibold text-slate-700 mb-2">{label}</label>
      <div className="space-y-2">
        {repos.map((repo, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="text"
              value={repo}
              onChange={e => update(i, e.target.value)}
              placeholder={placeholder}
              className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            {repos.length > 1 && (
              <button type="button" onClick={() => remove(i)}
                className="text-red-400 hover:text-red-600 px-2 text-lg">×</button>
            )}
          </div>
        ))}
      </div>
      <button type="button" onClick={add}
        className="mt-2 text-sm text-blue-500 hover:text-blue-700 font-medium">
        + Add repository
      </button>
    </div>
  )
}

function TokenInput({ label, hint, value, onChange, placeholder }) {
  return (
    <div>
      <label className="block text-sm font-semibold text-slate-700 mb-2">
        {label} {hint && <span className="font-normal text-slate-400">{hint}</span>}
      </label>
      <input
        type="password"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
    </div>
  )
}

export default function ScanPanel({ onSubmit, onClose }) {
  const [source, setSource] = useState('github')
  const [githubRepos, setGithubRepos] = useState([''])
  const [bitbucketRepos, setBitbucketRepos] = useState([''])
  const [months, setMonths] = useState(3)
  const [githubToken, setGithubToken] = useState('')
  const [bitbucketToken, setBitbucketToken] = useState('')
  const [geminiToken, setGeminiToken] = useState('')
  const [noAi, setNoAi] = useState(false)
  const [noDetails, setNoDetails] = useState(false)

  const showGithub = source === 'github' || source === 'both'
  const showBitbucket = source === 'bitbucket' || source === 'both'

  function handleSubmit(e) {
    e.preventDefault()
    const validGh = githubRepos.filter(r => r.trim())
    const validBb = bitbucketRepos.filter(r => r.trim())

    if (showGithub && !validGh.length && !showBitbucket) return
    if (showBitbucket && !validBb.length && !showGithub) return

    onSubmit({
      source,
      github_repos: showGithub ? validGh : [],
      bitbucket_repos: showBitbucket ? validBb : [],
      months,
      github_token: githubToken || undefined,
      bitbucket_token: bitbucketToken || undefined,
      gemini_token: geminiToken || undefined,
      no_ai: noAi,
      no_details: noDetails,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* Drawer */}
      <div className="w-full max-w-md bg-white shadow-2xl flex flex-col overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b bg-slate-900 text-white">
          <h2 className="text-lg font-bold">New Scan</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 px-6 py-6 space-y-6">

          {/* Source */}
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">Source</label>
            <div className="flex gap-2">
              {['github', 'bitbucket', 'both'].map(s => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSource(s)}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors capitalize
                    ${source === s
                      ? 'bg-blue-500 text-white border-blue-500'
                      : 'bg-white text-slate-600 border-slate-300 hover:border-blue-400'}`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* GitHub repos */}
          {showGithub && (
            <RepoList
              repos={githubRepos}
              onChange={setGithubRepos}
              placeholder="owner/repo"
              label="GitHub Repositories"
            />
          )}

          {/* Bitbucket repos */}
          {showBitbucket && (
            <RepoList
              repos={bitbucketRepos}
              onChange={setBitbucketRepos}
              placeholder="PROJECT_KEY/repo-slug"
              label="Bitbucket Server Repositories"
            />
          )}

          {/* Months */}
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">
              Lookback Period: <span className="text-blue-500">{months} month{months > 1 ? 's' : ''}</span>
            </label>
            <input type="range" min="1" max="12" value={months} onChange={e => setMonths(+e.target.value)}
              className="w-full accent-blue-500" />
            <div className="flex justify-between text-xs text-slate-400 mt-1">
              <span>1 month</span><span>6 months</span><span>12 months</span>
            </div>
          </div>

          {/* GitHub Token */}
          {showGithub && (
            <TokenInput
              label="GitHub Token"
              hint="(optional for public repos)"
              value={githubToken}
              onChange={setGithubToken}
              placeholder="ghp_..."
            />
          )}

          {/* Bitbucket Token */}
          {showBitbucket && (
            <TokenInput
              label="Bitbucket Server Token"
              hint="(Personal Access Token)"
              value={bitbucketToken}
              onChange={setBitbucketToken}
              placeholder="PAT from stash.gto.db.com"
            />
          )}

          {/* Gemini Token */}
          <TokenInput
            label="AI Service Token"
            hint="(overrides env var)"
            value={geminiToken}
            onChange={setGeminiToken}
            placeholder="Bearer token for AI service"
          />

          {/* Options */}
          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={noAi} onChange={e => setNoAi(e.target.checked)}
                className="w-4 h-4 accent-blue-500" />
              <div>
                <span className="text-sm font-medium text-slate-700">Skip AI analysis</span>
                <p className="text-xs text-slate-400">Use heuristic scores only (faster)</p>
              </div>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={noDetails} onChange={e => setNoDetails(e.target.checked)}
                className="w-4 h-4 accent-blue-500" />
              <div>
                <span className="text-sm font-medium text-slate-700">Skip file details</span>
                <p className="text-xs text-slate-400">Faster but no per-file diff analysis</p>
              </div>
            </label>
          </div>

          <button type="submit"
            className="w-full bg-blue-500 hover:bg-blue-600 text-white font-bold py-3 rounded-lg transition-colors">
            🚀 Run Scan
          </button>
        </form>
      </div>
    </div>
  )
}
