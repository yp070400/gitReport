import { useState, useEffect } from 'react'
import { fetchReport, runScan } from './api'
import Header from './components/Header'
import ScanPanel from './components/ScanPanel'
import TeamOverview from './components/TeamOverview'
import Leaderboard from './components/Leaderboard'
import DeveloperCard from './components/DeveloperCard'

export default function App() {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [scanOpen, setScanOpen] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')

  useEffect(() => {
    fetchReport()
      .then(data => {
        if (!data.error) setReport(data)
      })
      .catch(() => {})
  }, [])

  async function handleScan(config) {
    setLoading(true)
    setError(null)
    setStatusMsg('Fetching commits and analysing with AI...')
    setScanOpen(false)
    try {
      const data = await runScan(config)
      if (data.error) throw new Error(data.error)
      setReport(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setStatusMsg('')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <Header onScan={() => setScanOpen(true)} report={report} />

      {scanOpen && (
        <ScanPanel onSubmit={handleScan} onClose={() => setScanOpen(false)} />
      )}

      <main className="max-w-7xl mx-auto px-4 py-8 space-y-8">
        {loading && (
          <div className="flex flex-col items-center justify-center py-24 space-y-4">
            <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-slate-500 text-sm">{statusMsg}</p>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            {error}
          </div>
        )}

        {!loading && !report && !error && (
          <div className="flex flex-col items-center justify-center py-24 text-slate-400 space-y-3">
            <span className="text-5xl">📊</span>
            <p className="text-lg font-medium">No report yet</p>
            <p className="text-sm">Click <strong>New Scan</strong> to analyse your repositories</p>
          </div>
        )}

        {!loading && report && (
          <>
            <TeamOverview team={report.team} meta={report.meta} />
            <Leaderboard developers={report.developers} />
            <section>
              <h2 className="text-xl font-bold text-slate-800 mb-4">👤 Developer Details</h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {report.developers.map(dev => (
                  <DeveloperCard key={dev.author} dev={dev} />
                ))}
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
