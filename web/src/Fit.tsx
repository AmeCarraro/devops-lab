import { useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { DeviceArt } from './Art.tsx'
import { fitStream } from './api.ts'
import type { Attempt, FitStep, Samples, Targets } from './api.ts'
import Chart from './Chart.tsx'
import { DEVICES, apply, asYaml, formatCpu, newSession, outcome } from './fit.ts'
import type { Session } from './fit.ts'
import * as icons from './icons.tsx'
import Mosaic from './Mosaic.tsx'

const ICONS = { ok: <icons.Check />, warn: <icons.Target />, bad: <icons.Cross />, busy: <icons.Spark /> }

function Meter(props: { label: string; value: number; unit: string; share: number; mark?: number; good: boolean }) {
  const percent = (share: number) => `${Math.max(0, Math.min(1, share)) * 100}%`
  return (
    <div className={props.good ? 'meter good' : 'meter'}>
      <p>
        {props.label}
        <b className="mono">
          {props.value}
          <small> {props.unit}</small>
        </b>
      </p>
      <div className="track">
        <i style={{ width: percent(props.share) }} />
        {props.mark !== undefined && <u style={{ left: percent(props.mark) }} />}
      </div>
    </div>
  )
}

/** The three numbers of a measurement, each against what it had to reach or fit in. */
function Meters({ attempt, session }: { attempt: Attempt; session: Session }) {
  const result = attempt.result
  if (!result) return null
  const { min_fps, min_accuracy } = session.targets
  const fastest = Math.max(min_fps * 2, result.fps * 1.1)
  return (
    <div className="meters">
      <Meter
        label="Speed"
        value={result.fps}
        unit="img/s"
        share={result.fps / fastest}
        mark={min_fps / fastest}
        good={result.fps >= min_fps}
      />
      <Meter
        label="Accuracy"
        value={result.accuracy}
        unit="%"
        share={(result.accuracy - 40) / 60}
        mark={(min_accuracy - 40) / 60}
        good={result.accuracy >= min_accuracy}
      />
      <Meter
        label="Memory"
        value={result.memory_mb}
        unit={`of ${session.device.memory_mb} MB`}
        share={result.memory_mb / session.device.memory_mb}
        good
      />
    </div>
  )
}

function Tags({ attempt }: { attempt: Attempt }) {
  const { model, precision, input_size, threads } = attempt.pipeline
  return (
    <div className="config">
      <b className="mono">{model}</b>
      <span className="tag">{precision}</span>
      <span className="tag">{input_size} px</span>
      <span className="tag">
        {threads} thread{threads === 1 ? '' : 's'}
      </span>
    </div>
  )
}

function AttemptCard(props: { attempt: Attempt; session: Session; selected: boolean; onSelect: () => void }) {
  const { attempt, session } = props
  const { label, tone } = outcome(attempt)
  const waiting = !attempt.result && !attempt.failure

  function onKey(event: KeyboardEvent) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      props.onSelect()
    }
  }

  return (
    <li className="rise">
      <div
        className={`attempt ${tone} ${props.selected ? 'selected' : ''}`}
        role="button"
        tabIndex={0}
        aria-pressed={props.selected}
        onClick={props.onSelect}
        onKeyDown={onKey}
      >
        <header>
          <span className="number mono">{attempt.n}</span>
          <Tags attempt={attempt} />
          <span className={`badge ${tone}`}>
            {ICONS[tone]} {label}
          </span>
        </header>
        {attempt.reason && <p className="reason">“{attempt.reason}”</p>}
        <Meters attempt={attempt} session={session} />
        {attempt.failure && <p className="failure">{attempt.message}</p>}
        {waiting && (
          <div className="track busy">
            <i style={{ width: `${attempt.total ? (attempt.done / attempt.total) * 100 : 0}%` }} />
          </div>
        )}
      </div>
    </li>
  )
}

function StepRow({ step }: { step: FitStep }) {
  const query = String(step.arguments.query ?? step.arguments.name ?? '')
  if (step.refused === 'no_call') {
    return (
      <li className="lookup refused rise">
        <icons.Spark /> <span>The model wrote text instead of choosing a configuration: asked again.</span>
      </li>
    )
  }
  if (step.refused) {
    return (
      <li className="lookup refused rise">
        <icons.Cross />
        <span>
          {step.refused === 'repeated' ? 'Asked for a configuration it had already run' : 'Asked for an invalid configuration'}
          {step.message && <small> · {step.message}</small>}
        </span>
      </li>
    )
  }
  return (
    <li className="lookup rise">
      <icons.Book />
      <span>
        {step.by === 'agent' ? 'The agent looked up' : 'The model looked up'}: <q>{query}</q>
      </span>
      <small>{step.new_excerpts ? `${step.new_excerpts} excerpt${step.new_excerpts === 1 ? '' : 's'}` : 'nothing new'}</small>
    </li>
  )
}

function Verdict({ session, best }: { session: Session; best: Attempt | undefined }) {
  const [copied, setCopied] = useState(false)
  const summary = session.summary
  if (session.status === 'error') {
    return (
      <section className="card verdict bad rise" role="alert">
        <h2>Something broke.</h2>
        <p className="muted">{session.error}</p>
      </section>
    )
  }
  if (session.status === 'stopped') {
    return (
      <section className="card verdict rise">
        <h2>Stopped.</h2>
        <p className="muted">The run in the sandbox was cancelled. What was measured so far is below.</p>
      </section>
    )
  }

  if (!session.outcome) return null

  const fits = session.outcome === 'fits'
  const headline = fits ? 'It fits.' : best ? 'No fit this time.' : 'Nothing could be measured.'
  const yaml = best ? asYaml(best.pipeline) : ''

  function copy() {
    void navigator.clipboard.writeText(yaml).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    })
  }

  return (
    <section className={`card verdict ${fits ? 'ok' : ''} rise`}>
      <div className="verdict-text">
        <p className="eyebrow">
          <icons.Target /> Result
        </p>
        <h2 className={fits ? 'grad' : undefined}>{headline}</h2>
        {/* written by the agent from the measurements, not by the model */}
        <p className="note">{session.note}</p>
        {!fits && best && <p className="muted">Lower a target or choose a larger device, and search again.</p>}
        {summary && (
          <p className="ending">
            {summary.steps} steps · {summary.seconds.toFixed(0)} s · chosen by {summary.model}, measured in the sandbox
          </p>
        )}
      </div>
      {best && (
        <div className="verdict-config">
          <header>
            <span className="mono">pipeline.yaml</span>
            <button type="button" onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          </header>
          <pre>{yaml}</pre>
          <Meters attempt={best} session={session} />
        </div>
      )}
    </section>
  )
}

export default function Fit({ samples }: { samples: Samples | null }) {
  const [deviceId, setDeviceId] = useState('camera')
  const [targets, setTargets] = useState<Targets>({ min_fps: 30, min_accuracy: 85 })
  const [session, setSession] = useState<Session | null>(null)
  // the attempt the user clicked; until then the view follows the run
  const [picked, setPicked] = useState<number | null>(null)
  const controller = useRef<AbortController | null>(null)

  const device = DEVICES.find((preset) => preset.id === deviceId) ?? DEVICES[0]
  const running = session?.status === 'running'
  const attempts = session?.attempts ?? []
  const best = attempts.find((attempt) => attempt.n === session?.best)
  const selected = attempts.find((attempt) => attempt.n === picked) ?? best ?? attempts.at(-1)
  const measuring = selected && !selected.result && !selected.failure

  async function start() {
    const abort = new AbortController()
    controller.current = abort
    setPicked(null)
    setSession(newSession({ cpu: device.cpu, memory_mb: device.memory_mb }, targets))

    let finished = false
    try {
      for await (const event of fitStream({ cpu: device.cpu, memory_mb: device.memory_mb }, targets, abort.signal)) {
        if (event.type === 'done' || event.type === 'error') finished = true
        setSession((current) => current && apply(current, event))
      }
      if (!finished) {
        const error = 'The connection closed before the run was complete.'
        setSession((current) => current && { ...current, status: 'error', error })
      }
    } catch (error) {
      // aborting the request is how Stop works, so that is not a failure
      const message = error instanceof Error ? error.message : String(error)
      setSession(
        (current) =>
          current && (abort.signal.aborted ? { ...current, status: 'stopped' } : { ...current, status: 'error', error: message }),
      )
    }
  }

  const slider = (value: number, min: number, max: number) => ({ '--fill': `${((value - min) / (max - min)) * 100}%` }) as CSSProperties

  return (
    <div className="fit">
      <aside className="card panel rise">
        <div>
          <h1>
            Fit a pipeline <span className="grad">to a device.</span>
          </h1>
          <p className="muted">The agent searches for a configuration that reaches the target inside the device.</p>
        </div>

        <fieldset disabled={running}>
          <legend className="eyebrow">
            <icons.Chip /> The device
          </legend>
          <div className="devices">
            {DEVICES.map((preset) => (
              <label key={preset.id} className={preset.id === deviceId ? 'device chosen' : 'device'}>
                <input
                  type="radio"
                  name="device"
                  checked={preset.id === deviceId}
                  onChange={() => setDeviceId(preset.id)}
                />
                <DeviceArt cpu={preset.cpu} memory={preset.memory_mb} live={preset.id === deviceId} />
                <span>
                  <b>{preset.name}</b>
                  <small className="mono">
                    {formatCpu(preset.cpu)} · {preset.memory_mb} MB
                  </small>
                </span>
              </label>
            ))}
          </div>
          <p className="muted small">{device.blurb}</p>
        </fieldset>

        <fieldset disabled={running}>
          <legend className="eyebrow">
            <icons.Target /> The target
          </legend>
          <label className="slider">
            <span>
              <icons.Bolt /> Speed
              <b className="mono">
                ≥ {targets.min_fps} <small>img/s</small>
              </b>
            </span>
            <input
              type="range"
              min={5}
              max={300}
              step={5}
              value={targets.min_fps}
              style={slider(targets.min_fps, 5, 300)}
              onChange={(event) => setTargets({ ...targets, min_fps: Number(event.target.value) })}
            />
          </label>
          <label className="slider">
            <span>
              <icons.Eye /> Accuracy
              <b className="mono">
                ≥ {targets.min_accuracy} <small>%</small>
              </b>
            </span>
            <input
              type="range"
              min={50}
              max={95}
              value={targets.min_accuracy}
              style={slider(targets.min_accuracy, 50, 95)}
              onChange={(event) => setTargets({ ...targets, min_accuracy: Number(event.target.value) })}
            />
          </label>
        </fieldset>

        {running ? (
          <button type="button" className="button" onClick={() => controller.current?.abort()}>
            <icons.Stop /> Stop
          </button>
        ) : (
          <button type="button" className="button primary" onClick={() => void start()}>
            <icons.Play /> {session ? 'Search again' : 'Find a configuration'}
          </button>
        )}
        <p className="faint small">Up to 8 attempts. Each one runs for real, so it takes from a few seconds to a minute.</p>
      </aside>

      <div className="stage">
        {session && <Verdict session={session} best={best} />}

        <div className="visuals">
          <section className="card rise">
            <header>
              <p className="eyebrow">
                <icons.Gauge /> Speed against accuracy
              </p>
              <span className="legend">
                <i className="fits" /> fits <i /> misses
              </span>
            </header>
            <Chart
              targets={session?.targets ?? targets}
              attempts={attempts}
              selected={selected?.n ?? null}
              onSelect={setPicked}
            />
          </section>

          <section className="card rise">
            <header>
              <p className="eyebrow">
                <icons.Eye /> What the device sees
              </p>
              {selected && (
                <span className="pill mono">
                  attempt {selected.n}
                  {selected.result && ` · ${Math.round((selected.result.accuracy / 100) * selected.result.images)} right`}
                </span>
              )}
            </header>
            {samples ? (
              <Mosaic
                samples={samples}
                count={samples.labels.length}
                columns={samples.columns}
                seen={measuring ? selected.done : undefined}
                predictions={selected?.result?.predictions}
              />
            ) : (
              <p className="muted placeholder">The pictures appear once the bench image is deployed.</p>
            )}
            <p className="muted small">
              {selected?.result
                ? 'Green: the model named the picture correctly. Red: it did not. Hover a picture to see what it answered.'
                : 'Every configuration classifies these 200 pictures, one at a time, like frames from a camera.'}
            </p>
          </section>
        </div>

        <section className="card log rise">
          <header>
            <p className="eyebrow">
              <icons.Layers /> What the agent did
            </p>
            {running && (
              <span className="pill">
                <span className="dot live" /> working
              </span>
            )}
          </header>
          {session && session.entries.length > 0 ? (
            <ol className="timeline">
              {session.entries.map((entry, index) => {
                if (entry.kind === 'step') {
                  // a lookup of the agent that found only pages already read changed nothing: not worth a line
                  if (entry.step.by === 'agent' && !entry.step.new_excerpts) return null
                  return <StepRow key={index} step={entry.step} />
                }
                const attempt = attempts.find((other) => other.n === entry.n)
                return (
                  attempt && (
                    <AttemptCard
                      key={index}
                      attempt={attempt}
                      session={session}
                      selected={attempt.n === selected?.n}
                      onSelect={() => setPicked(attempt.n)}
                    />
                  )
                )
              })}
            </ol>
          ) : (
            <p className="muted empty">
              {running
                ? 'The model is reading the task…'
                : 'Nothing tried yet. Choose a device and a target, then start: every attempt will appear here with its reason and its numbers.'}
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
