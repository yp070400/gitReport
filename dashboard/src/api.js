const BASE = '/api'

export async function fetchReport() {
  const res = await fetch(`${BASE}/report`)
  if (!res.ok) throw new Error('Failed to fetch report')
  return res.json()
}

export async function runScan(config) {
  const res = await fetch(`${BASE}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || err.error || `Scan failed (${res.status})`)
  }
  return res.json()
}
