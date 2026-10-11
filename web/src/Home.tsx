import type { CSSProperties, ReactNode } from 'react'
import { DeviceArt } from './Art.tsx'
import type { Info, Samples, Zoo } from './api.ts'
import { configurations } from './fit.ts'
import * as icons from './icons.tsx'
import Mosaic from './Mosaic.tsx'

const QUESTIONS = ['Why is a pod used as the device?', 'Which model is the fastest?', 'Come fermo il cluster locale?']

const HOW = [
  { icon: <icons.Target />, title: 'Set a target', text: 'A device, a speed and an accuracy the pipeline must reach.' },
  { icon: <icons.Spark />, title: 'The agent chooses', text: 'A small model reads the documentation and picks a configuration.' },
  { icon: <icons.Shield />, title: 'A locked pod runs it', text: 'The CPU and memory of the device, no network, nothing to write to.' },
  { icon: <icons.Gauge />, title: 'Numbers come back', text: 'Measured on 200 pictures. Not enough? It changes one thing and retries.' },
]

type Props = {
  info: Info | null
  samples: Samples | null
  zoo: Zoo | null
  /** What to show at the top right of the "live" tile: the GPU reading, in the desktop app. */
  gpu: ReactNode
  onAsk: (question: string) => void
}

/** Tiles appear one after the other: each waits a little longer than the one before. */
const after = (position: number) => ({ '--d': position }) as CSSProperties

export default function Home({ info, samples, zoo, gpu, onAsk }: Props) {
  return (
    <div className="bento">
      <section className="card hero rise">
        <p className="eyebrow">
          <icons.Chip /> Edge AI · runs on this machine
        </p>
        <h1>
          Make a vision model <span className="grad">fit the device.</span>
        </h1>
        <p className="lead">
          Pick a device and a target. A small language model chooses the model, the precision and the input size, runs
          every try inside a Kubernetes pod that has exactly the CPU and memory of that device, and keeps going until
          the numbers fit.
        </p>
        <div className="actions">
          <a className="button primary" href="#/fit">
            Fit a device <icons.Arrow />
          </a>
          <a className="button" href="#/ask">
            <icons.Book /> Ask the docs
          </a>
        </div>
        <ul className="facts">
          <li>
            <icons.Gauge /> Measured, never guessed
          </li>
          <li>
            <icons.Shield /> Sandboxed runs
          </li>
          <li>
            <icons.Bolt /> No cloud, no cost
          </li>
        </ul>
      </section>

      <section className="card sees rise" style={after(1)}>
        <header>
          <p className="eyebrow">
            <icons.Eye /> What the device sees
          </p>
          <span className="pill mono">{samples ? `${samples.labels.length} pictures` : 'no pictures yet'}</span>
        </header>
        {samples ? (
          <Mosaic samples={samples} count={80} columns={10} ambient />
        ) : (
          <p className="muted placeholder">The pictures appear once the bench image is deployed.</p>
        )}
        <p className="muted small">The same pictures score every configuration, so two runs can be compared.</p>
      </section>

      <section className="card how rise" style={after(2)}>
        <p className="eyebrow">
          <icons.Layers /> How it works
        </p>
        <ol>
          {HOW.map((step, index) => (
            <li key={step.title}>
              <span className="how-icon">{step.icon}</span>
              <span className="how-number mono">0{index + 1}</span>
              <h3>{step.title}</h3>
              <p className="muted">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="card cluster rise" style={after(3)}>
        <header>
          <p className="eyebrow">
            <span className={info ? 'dot live' : 'dot'} /> {info ? 'Live' : 'Unreachable'}
          </p>
          {gpu}
        </header>
        <dl>
          <div>
            <dt>Language model</dt>
            <dd className="mono">{info?.model ?? '—'}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd className="mono">{info?.version ?? '—'}</dd>
          </div>
          <div>
            <dt>Answered by</dt>
            <dd className="mono">{info?.pod ?? '—'}</dd>
          </div>
          <div>
            <dt>Sandbox</dt>
            <dd className="mono">{zoo ? `${zoo.models.length} models ready` : 'not reachable'}</dd>
          </div>
        </dl>
      </section>

      <section className="card pod rise" style={after(4)}>
        <DeviceArt cpu={1} memory={512} live />
        <h2 className="title">The pod is the device</h2>
        <p className="muted">
          Kubernetes gives each run the cores and the memory of the device and nothing else. A model that needs more is
          stopped, exactly as it would be on the real thing.
        </p>
      </section>

      <section className="card docs rise" style={after(5)}>
        <p className="eyebrow">
          <icons.Book /> Ask the docs
        </p>
        <h2 className="title">The same agent answers questions on the project</h2>
        <ul>
          {QUESTIONS.map((question) => (
            <li key={question}>
              <button type="button" onClick={() => onAsk(question)}>
                {question} <icons.Arrow />
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card count rise" style={after(6)}>
        <p className="eyebrow">
          <icons.Search /> The search space
        </p>
        <p className="big grad mono">{zoo ? configurations(zoo) : '—'}</p>
        <p className="muted">
          configurations: {zoo?.models.length ?? '—'} models, {zoo?.precisions.length ?? '—'} precisions,{' '}
          {zoo?.input_sizes.length ?? '—'} input sizes, up to {zoo?.max_threads ?? '—'} threads. The agent gets 8 tries.
        </p>
      </section>
    </div>
  )
}
