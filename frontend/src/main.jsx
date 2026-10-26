import { createRoot } from 'react-dom/client'
import { useEffect, useState } from 'react'
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Label,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import './styles.css'

const EMPTY = '—'

function useJson(url) {
  const [state, setState] = useState({ data: null, loading: Boolean(url), error: null })

  useEffect(() => {
    if (!url) {
      setState({ data: null, loading: false, error: null })
      return undefined
    }
    const controller = new AbortController()
    setState({ data: null, loading: true, error: null })
    fetch(url, { headers: { Accept: 'application/json' }, signal: controller.signal })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}))
        if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`)
        return body
      })
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((error) => {
        if (error.name !== 'AbortError') setState({ data: null, loading: false, error: error.message })
      })
    return () => controller.abort()
  }, [url])

  return state
}

function formatMw(value, digits = 0) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return EMPTY
  return `${new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(Number(value))} MW`
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return EMPTY
  return new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(Number(value))
}

function formatGw(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return EMPTY
  return `${new Intl.NumberFormat('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Number(value) / 1000)} GW`
}

function formatMwAxis(value) {
  if (!Number.isFinite(Number(value))) return EMPTY
  return new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 }).format(Number(value))
}

function decisionTicks(rows) {
  const values = rows.flatMap((row) => [row.forecast, row.actual, row.rangeLow, row.rangeHigh])
    .map(Number).filter(Number.isFinite)
  const maximum = values.length ? Math.max(...values) : 0
  const top = Math.max(5000, Math.ceil(maximum / 5000) * 5000)
  return Array.from({ length: top / 5000 + 1 }, (_, index) => index * 5000)
}

function formatDayLabel(value) {
  if (!value) return EMPTY
  const parsed = new Date(`${String(value).slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short' }).format(parsed)
}

function formatOutputBand(value) {
  const numbers = String(value).match(/-?[\d,.]+/g)?.map((item) => Number(item.replaceAll(',', '')))
  if (!numbers || numbers.length < 2) return String(value ?? EMPTY)
  return `${formatNumber(numbers[0] / 1000, 1)}-${formatNumber(numbers[1] / 1000, 1)} GW`
}

function formatLocalTime(value, options = {}) {
  if (!value) return EMPTY
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    ...options,
  }).format(new Date(value))
}

function formatLocalHour(value) {
  if (!value) return EMPTY
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value))
}

function formatUtc(value) {
  if (!value) return EMPTY
  return `${new Date(value).toISOString().replace('.000Z', 'Z')} UTC`
}

function formatDateWords(value) {
  if (!value) return EMPTY
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
  }).format(new Date(`${value}T12:00:00Z`)).replace(',', '')
}

function ErrorState({ error }) {
  return <div className="state error-state">Could not load this view: {error}</div>
}

function LoadingState() {
  return <div className="state">Loading snapshot…</div>
}

function AsyncState({ query, children }) {
  if (query.loading) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} />
  if (!query.data) return <div className="state">No data returned.</div>
  return children(query.data)
}

function MetricCard({ label, value, tone = '' }) {
  return <div className={`metric-card ${tone}`}><span>{label}</span><strong>{value}</strong></div>
}

function cutoffParams(cutoff) {
  return `cutoff_hour=${encodeURIComponent(cutoff.hour)}&cutoff_minute=${encodeURIComponent(cutoff.minute)}`
}

function CutoffControls({ cutoff, setCutoff, onReset }) {
  return (
    <div className="cutoff-controls">
      <label>Cutoff hour
        <input type="number" min="0" max="23" value={cutoff.hour} onChange={(event) => setCutoff({ ...cutoff, hour: event.target.value })} />
      </label>
      <label>Minute
        <input type="number" min="0" max="59" value={cutoff.minute} onChange={(event) => setCutoff({ ...cutoff, minute: event.target.value })} />
      </label>
      <span className="timezone-note">Europe/London, on D−1</span>
      <button className="button secondary" onClick={onReset}>Reset to 09:00</button>
    </div>
  )
}

function ChartTooltip({ active, payload, label, valueFormatter = formatMw, labelFormatter }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <strong>{labelFormatter ? labelFormatter(label) : label}</strong>
      {payload.map((entry) => <div key={entry.dataKey}>{entry.name}: {valueFormatter(entry.value)}</div>)}
    </div>
  )
}

function Panel({ title, subtitle, children, className = '' }) {
  return <section className={`panel ${className}`}><div className="panel-heading"><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{children}</section>
}

function DecisionView({ meta, day, setDay, cutoff, setCutoff, resetCutoff }) {
  const dayUrl = meta && day ? `/api/day?day=${day}&${cutoffParams(cutoff)}` : null
  const vintagesUrl = meta && day ? `/api/day/vintages?day=${day}&${cutoffParams(cutoff)}` : null
  const fullAccuracyUrl = meta ? `/api/accuracy?from=${meta.delivery_days_available.from}&to=${meta.delivery_days_available.to}&${cutoffParams(cutoff)}` : null
  const dayQuery = useJson(dayUrl)
  const vintagesQuery = useJson(vintagesUrl)
  const accuracyQuery = useJson(fullAccuracyUrl)

  return (
    <>
      <Panel title="Decision view" subtitle="What the day-ahead buying decision sees for one London delivery day.">
        <div className="controls-row">
          <label>Delivery day
            <input type="date" min={meta?.delivery_days_available.from} max={meta?.delivery_days_available.to} value={day || ''} onChange={(event) => setDay(event.target.value)} />
          </label>
          <span className="date-words">{formatDateWords(day)}</span>
          <CutoffControls cutoff={cutoff} setCutoff={setCutoff} onReset={resetCutoff} />
        </div>
      </Panel>
      <AsyncState query={dayQuery}>{(data) => <DecisionContent data={data} accuracy={accuracyQuery} vintages={vintagesQuery} />}</AsyncState>
    </>
  )
}

function DecisionContent({ data, accuracy, vintages }) {
  const rows = data.hours || []
  const firstForecast = rows.find((row) => row.forecast !== null && row.forecast !== undefined)
  const avgForecast = rows.reduce((sum, row) => sum + (Number(row.forecast) || 0), 0) / Math.max(1, rows.filter((row) => row.forecast !== null).length)
  const avgActual = rows.reduce((sum, row) => sum + (Number(row.actual) || 0), 0) / Math.max(1, rows.filter((row) => row.actual !== null).length)
  const p05 = accuracy.data?.accuracy_summary?.p05_error
  const p95 = accuracy.data?.accuracy_summary?.p95_error
  const chartRows = rows.map((row) => ({
    label: formatLocalHour(row.startTime),
    forecast: row.forecast,
    actual: row.actual,
    rangeLow: Number.isFinite(Number(row.forecast)) && Number.isFinite(Number(p95)) ? Number(row.forecast) - Number(p95) : null,
    rangeHigh: Number.isFinite(Number(row.forecast)) && Number.isFinite(Number(p05)) ? Number(row.forecast) - Number(p05) : null,
  }))
  const ticks = decisionTicks(chartRows)
  return (
    <>
      <div className="headline-grid">
        <MetricCard label="Forecast used" value={firstForecast ? <><span>{formatLocalTime(firstForecast.publishTime)}</span><small>{formatUtc(firstForecast.publishTime)}</small></> : EMPTY} />
        <MetricCard label="Average forecast" value={formatMw(avgForecast, 0)} />
        <MetricCard label="Average actual" value={formatMw(avgActual, 0)} />
        <MetricCard label="Day MAE" value={formatMw(data.accuracy_summary?.mae)} />
        <MetricCard label="Day bias (forecast − actual)" value={formatMw(data.accuracy_summary?.bias)} tone={Number(data.accuracy_summary?.bias) > 0 ? 'warning' : ''} />
      </div>
      <Panel title="Forecast versus actual" subtitle={`Delivery day ${formatDateWords(data.day)} · hourly values shown in Europe/London. Hover for the UTC-backed values.`}>
        <div className="chart-legend-note"><span className="band-key" /> Range containing about 90% of actual values in the January backtest (in-sample, not a guarantee).</div>
        <div className="chart-wrap"><ResponsiveContainer width="100%" height={360}><ComposedChart data={chartRows} margin={{ top: 4, right: 20, left: 4, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d9e2ec" /><XAxis dataKey="label" angle={0} textAnchor="middle" height={30} interval={2} padding={{ left: 12, right: 12 }} /><YAxis ticks={ticks} domain={[0, ticks[ticks.length - 1]]} tickFormatter={formatMwAxis}><Label value="MW" angle={-90} position="insideLeft" /></YAxis><Tooltip content={<ChartTooltip />} /><Legend verticalAlign="top" height={32} />
          <Area type="monotone" dataKey="rangeHigh" stroke="none" fill="#d9eaf7" fillOpacity={0.72} legendType="none" name="Actual range" isAnimationActive={false} />
          <Area type="monotone" dataKey="rangeLow" stroke="none" fill="#ffffff" fillOpacity={1} legendType="none" name="Range base" isAnimationActive={false} />
          <Line type="monotone" dataKey="forecast" stroke="#1769aa" strokeWidth={2.5} dot={false} name="Forecast" connectNulls={false} />
          <Line type="monotone" dataKey="actual" stroke="#e76f51" strokeWidth={2} dot={false} name="Actual" />
        </ComposedChart></ResponsiveContainer></div>
      </Panel>
      <Panel title="Forecast vintages" subtitle="Most recent publications available before the selected cutoff.">
        <AsyncState query={vintages}>{(vintageData) => <div className="vintage-list">{vintageData.vintages.map((vintage) => <div className={`vintage-row ${vintage.selected ? 'selected' : ''}`} key={vintage.publishTime}><div><strong>{formatLocalTime(vintage.publishTime)}</strong><small>{formatUtc(vintage.publishTime)}</small></div><span>{vintage.hours?.length || 0} hourly values</span>{vintage.selected && <em>Selected</em>}</div>)}</div>}</AsyncState>
      </Panel>
    </>
  )
}

function AccuracyView({ meta, cutoff, setCutoff, resetCutoff }) {
  const [from, setFrom] = useState(meta?.delivery_days_available.from || '')
  const [to, setTo] = useState(meta?.delivery_days_available.to || '')
  useEffect(() => {
    if (meta) { setFrom(meta.delivery_days_available.from); setTo(meta.delivery_days_available.to) }
  }, [meta])
  const url = meta && from && to ? `/api/accuracy?from=${from}&to=${to}&${cutoffParams(cutoff)}` : null
  const query = useJson(url)
  return (
    <>
      <Panel title="Accuracy" subtitle="Explore the selected day-ahead backtest range.">
        <div className="controls-row">
          <label>From <input type="date" min={meta?.delivery_days_available.from} max={meta?.delivery_days_available.to} value={from} onChange={(event) => setFrom(event.target.value)} /></label>
          <label>To <input type="date" min={meta?.delivery_days_available.from} max={meta?.delivery_days_available.to} value={to} onChange={(event) => setTo(event.target.value)} /></label>
          <CutoffControls cutoff={cutoff} setCutoff={setCutoff} onReset={resetCutoff} />
        </div>
      </Panel>
      <AsyncState query={query}>{(data) => <AccuracyContent data={data} />}</AsyncState>
    </>
  )
}

function AccuracyContent({ data }) {
  const summary = data.accuracy_summary || {}
  const positiveDays = (data.by_day || []).filter((row) => Number(row.bias) > 0).length
  const totalDays = (data.by_day || []).length
  const sentence = `Over this range the forecast was higher than actual wind on ${positiveDays} of ${totalDays} days, by ${formatMw(summary.bias)} on average.`
  return (
    <>
      <div className="metric-grid">
        <MetricCard label="MAE" value={formatMw(summary.mae)} /><MetricCard label="RMSE" value={formatMw(summary.rmse)} /><MetricCard label="Bias (forecast − actual)" value={formatMw(summary.bias)} tone={Number(summary.bias) > 0 ? 'warning' : ''} /><MetricCard label="MAE / mean actual" value={Number.isFinite(Number(summary.mae_pct_of_mean_actual)) ? `${formatNumber(summary.mae_pct_of_mean_actual, 1)}%` : EMPTY} /><MetricCard label="P90 absolute error" value={formatMw(summary.p90_absolute_error)} /><MetricCard label="P95 absolute error" value={formatMw(summary.p95_absolute_error)} /><MetricCard label="Hours with no forecast" value={formatNumber(data.no_forecast_hours, 0)} />
      </div>
      <p className="plain-language"><strong>{sentence}</strong> Positive bias means forecast above actual; for a buyer, that may mean under-procuring.</p>
      <div className="chart-grid">
        <ChartPanel title="Error by horizon band" data={data.by_horizon} x="horizon_band" bars={[['mae', 'MAE', '#1769aa'], ['bias', 'Bias', '#e76f51']]} />
        <ChartPanel title="Error by London hour" data={data.by_hour} x="hour" bars={[['mae', 'MAE', '#1769aa'], ['bias', 'Bias', '#e76f51']]} xFormatter={(value) => `${String(value).padStart(2, '0')}:00`} xInterval={1} tooltipLabel={(value) => `${String(value).padStart(2, '0')}:00`} />
        <ChartPanel title="Daily bias" data={data.by_day} x="delivery_date" bars={[['bias', 'Bias', '#e76f51']]} xFormatter={formatDayLabel} xInterval={2} />
        <ChartPanel title="Error by actual-output band" data={data.by_output_band} x="output_band" bars={[['mae', 'MAE', '#1769aa'], ['bias', 'Bias', '#e76f51']]} outputBand xFormatter={formatOutputBand} />
      </div>
    </>
  )
}

function ChartPanel({ title, data, x, bars, xFormatter, xInterval = 0, tooltipLabel, outputBand = false }) {
  const chartData = (data || []).map((row, index) => ({ ...row, [x]: String(row[x] ?? EMPTY), fifth: index + 1 }))
  const formatter = (value) => formatNumber(Number(value) / 1000, 1)
  const titleFormatter = (value) => {
    if (tooltipLabel) return tooltipLabel(value)
    if (outputBand) {
      const row = chartData.find((item) => item[x] === value)
      return `${formatOutputBand(value)} · fifth ${row?.fifth ?? EMPTY} of actual output`
    }
    return value
  }
  return <Panel title={title}><div className="chart-wrap small"><ResponsiveContainer width="100%" height={280}><BarChart data={chartData} margin={{ top: 38, right: 12, left: 8, bottom: 18 }}><CartesianGrid strokeDasharray="3 3" stroke="#d9e2ec" /><XAxis dataKey={x} tickFormatter={xFormatter} angle={0} textAnchor="middle" height={30} interval={xInterval} /><YAxis tickFormatter={formatter} allowDecimals><Label value="GW" angle={-90} position="insideLeft" /></YAxis><Tooltip content={<ChartTooltip valueFormatter={formatGw} labelFormatter={titleFormatter} />} /><Legend verticalAlign="top" height={32} />{bars.map(([key, name, color]) => <Bar key={key} dataKey={key} name={name} fill={color} radius={[3, 3, 0, 0]} />)}</BarChart></ResponsiveContainer></div></Panel>
}

function MethodView({ meta }) {
  return <Panel title="Method and assumptions" subtitle="What this pilot does—and what it deliberately does not claim.">
    <div className="method-copy">
      <h3>Live snapshot</h3><p>This pilot serves a precomputed January 2026 snapshot from Elexon FUELHH WIND actuals and WINDFOR forecasts. The browser never calls Elexon directly.</p>
      <h3>Assumptions from the backend</h3><ul>{(meta?.assumptions || []).map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
      <h3>Coverage caveat</h3><p>Elexon documents coverage differences between the datasets. Those differences have not been quantified here, so forecast bias should not be presented as a proven cause or as a guarantee of future performance.</p>
      <h3>Pilot scope</h3><p>This is a pilot on January 2026 data only. It is not a live trading or procurement recommendation.</p>
    </div>
  </Panel>
}

function App() {
  const metaQuery = useJson('/api/meta')
  const [view, setView] = useState('decision')
  const [day, setDay] = useState('')
  const [cutoff, setCutoff] = useState({ hour: 9, minute: 0 })
  useEffect(() => {
    if (metaQuery.data && !day) setDay(metaQuery.data.delivery_days_available.from)
  }, [metaQuery.data, day])
  const resetCutoff = () => setCutoff({ hour: 9, minute: 0 })
  if (metaQuery.loading) return <div className="app-shell"><LoadingState /></div>
  if (metaQuery.error) return <div className="app-shell"><ErrorState error={metaQuery.error} /></div>
  const meta = metaQuery.data
  return <div className="app-shell">
    <header className="topbar"><div><p className="eyebrow">GB WIND · DAY-AHEAD BUYING</p><h1>Wind forecast portal</h1><p className="lede">A decision-support view for forecast versus actual national wind generation.</p></div><div className="snapshot-pill">Elexon snapshot<br /><strong>Jan 2026</strong></div></header>
    <nav className="tabs" aria-label="Views">{[['decision', 'Decision view'], ['accuracy', 'Accuracy'], ['method', 'Method and assumptions']].map(([key, label]) => <button key={key} className={view === key ? 'active' : ''} onClick={() => setView(key)}>{label}</button>)}</nav>
    <main>{view === 'decision' && <DecisionView meta={meta} day={day} setDay={setDay} cutoff={cutoff} setCutoff={setCutoff} resetCutoff={resetCutoff} />}{view === 'accuracy' && <AccuracyView meta={meta} cutoff={cutoff} setCutoff={setCutoff} resetCutoff={resetCutoff} />}{view === 'method' && <MethodView meta={meta} />}</main>
    <footer>UTC is the storage/reference time. London local time is used for delivery-day and cutoff presentation.</footer>
  </div>
}

export default App

createRoot(document.getElementById('root')).render(<App />)
