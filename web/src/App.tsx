import { useEffect, useState } from 'react'
import type { PointerEvent } from 'react'
import Ask from './Ask.tsx'
import type { Seed } from './Ask.tsx'
import { fetchInfo, fetchSamples, fetchZoo } from './api.ts'
import type { Info, Samples, Zoo } from './api.ts'
import { gigabytes, gpuStatus, isDesktop, shortName } from './desktop.ts'
import type { Gpu } from './desktop.ts'
import Fit from './Fit.tsx'
import Home from './Home.tsx'
import * as icons from './icons.tsx'

const VIEWS = [
  { path: '#/', name: 'Overview', icon: <icons.Home /> },
  { path: '#/fit', name: 'Fit', icon: <icons.Chip /> },
  { path: '#/ask', name: 'Ask', icon: <icons.Book /> },
]

/** The view is the part of the address after #, so the back button and links work. */
function useView(): number {
  const read = () => Math.max(0, VIEWS.findIndex((view) => view.path === window.location.hash))
  const [view, setView] = useState(read)
  useEffect(() => {
    const onChange = () => setView(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return view
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') ?? 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])
  return [theme, () => setTheme(theme === 'dark' ? 'light' : 'dark')]
}

/** Only in the desktop app: how busy the graphics card is, read by the native side every two seconds. */
function GpuMeter() {
  const [gpu, setGpu] = useState<Gpu | null>(null)

  useEffect(() => {
    let mounted = true
    function read() {
      gpuStatus()
        .then((value) => {
          if (mounted) setGpu(value)
        })
        .catch(() => {
          if (mounted) setGpu(null)
        })
    }
    read()
    const timer = setInterval(read, 2000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [])

  if (!gpu) return null
  return (
    <span className="pill gpu" title={gpu.name}>
      {shortName(gpu.name)} · {gigabytes(gpu.memory_used_mb)} / {gigabytes(gpu.memory_total_mb)} GB ·{' '}
      {gpu.utilization_percent}%
      <meter
        aria-label="Video memory in use"
        min={0}
        max={gpu.memory_total_mb}
        high={gpu.memory_total_mb * 0.92}
        value={gpu.memory_used_mb}
      />
    </span>
  )
}

/** Tells the card under the pointer where the pointer is, so its light can follow it (see .card in index.css). */
function moveLight(event: PointerEvent) {
  const card = (event.target as Element).closest<HTMLElement>('.card')
  if (!card) return
  const box = card.getBoundingClientRect()
  card.style.setProperty('--mx', `${event.clientX - box.left}px`)
  card.style.setProperty('--my', `${event.clientY - box.top}px`)
}

export default function App() {
  const view = useView()
  const [theme, toggleTheme] = useTheme()
  const [info, setInfo] = useState<Info | null>(null)
  const [samples, setSamples] = useState<Samples | null>(null)
  const [zoo, setZoo] = useState<Zoo | null>(null)
  const [seed, setSeed] = useState<Seed | null>(null)

  useEffect(() => {
    // each of the three can be missing without breaking the page: a tile then says so
    fetchInfo().then(setInfo, () => setInfo(null))
    fetchSamples().then(setSamples, () => setSamples(null))
    fetchZoo().then(setZoo, () => setZoo(null))
  }, [])

  function askFromHome(text: string) {
    setSeed((last) => ({ n: (last?.n ?? 0) + 1, text }))
    window.location.hash = '#/ask'
  }

  const gpu = isDesktop ? <GpuMeter /> : null

  return (
    <div className="shell" onPointerMove={moveLight}>
      <div className="backdrop">
        <i />
        <i />
        <i />
      </div>

      <header className="bar">
        <a className="brand" href="#/">
          <icons.Logo />
          <span className="hide-narrow">Edge Lab</span>
        </a>
        <nav className="tabs" style={{ ['--active' as string]: view }}>
          {VIEWS.map((item, index) => (
            <a key={item.path} className="tab" href={item.path} aria-current={index === view ? 'page' : undefined}>
              {item.icon} {item.name}
            </a>
          ))}
        </nav>
        <div className="bar-side">
          <span className="pill hide-narrow" title={info ? `Answered by ${info.pod}` : undefined}>
            <span className={info ? 'dot live' : 'dot'} />
            {info ? (
              <>
                <b>{info.model}</b> · {info.version}
              </>
            ) : (
              'connecting…'
            )}
          </span>
          <button type="button" className="icon-button" aria-label="Switch between dark and light" onClick={toggleTheme}>
            {theme === 'dark' ? <icons.Sun /> : <icons.Moon />}
          </button>
        </div>
      </header>

      {/* the three views stay alive when hidden: a run goes on while you look at another one */}
      <main>
        <div hidden={view !== 0}>
          <Home info={info} samples={samples} zoo={zoo} gpu={gpu} onAsk={askFromHome} />
        </div>
        <div hidden={view !== 1}>
          <Fit samples={samples} />
        </div>
        <div hidden={view !== 2}>
          <Ask active={view === 2} seed={seed} />
        </div>
      </main>

      <footer className="foot">
        k3s · MCP · Ollama · ONNX Runtime · React — everything on this page runs on this machine.
      </footer>
    </div>
  )
}
