// What the "Fit" view knows that is not drawing: the devices on offer, how the
// events of a run become the state on screen, and the arithmetic of the chart.
import type { Attempt, Device, FitEvent, FitStep, FitSummary, Pipeline, Targets, Zoo } from './api.ts'

export type DevicePreset = Device & { id: string; name: string; blurb: string }

export const DEVICES: DevicePreset[] = [
  { id: 'sensor', name: 'Sensor node', cpu: 0.5, memory_mb: 128, blurb: 'Half a core and little memory. A doorbell, a counter on a shelf.' },
  { id: 'camera', name: 'Smart camera', cpu: 1, memory_mb: 512, blurb: 'One core. A camera on a production line.' },
  { id: 'gateway', name: 'Edge gateway', cpu: 2, memory_mb: 1024, blurb: 'Two cores. A box that serves a few cameras.' },
]

/** What the agent did, in order: a run is kept by its number, because its state changes while it runs. */
export type Entry = { kind: 'step'; step: FitStep } | { kind: 'attempt'; n: number }

export type Session = {
  status: 'idle' | 'running' | 'done' | 'stopped' | 'error'
  device: Device
  targets: Targets
  entries: Entry[]
  attempts: Attempt[]
  /** How the search ended and which attempt to keep. */
  outcome?: FitSummary['outcome']
  best?: number | null
  note: string
  summary?: FitSummary
  error?: string
}

export function newSession(device: Device, targets: Targets): Session {
  return { status: 'running', device, targets, entries: [], attempts: [], note: '' }
}

/** The session after one more event from the server. */
export function apply(session: Session, event: FitEvent): Session {
  switch (event.type) {
    case 'step': {
      const { type: _, ...step } = event
      return { ...session, entries: [...session.entries, { kind: 'step', step }] }
    }
    case 'attempt': {
      const { type: _, ...attempt } = event
      const known = session.attempts.some((other) => other.n === attempt.n)
      return {
        ...session,
        attempts: known
          ? session.attempts.map((other) => (other.n === attempt.n ? attempt : other))
          : [...session.attempts, attempt],
        entries: known ? session.entries : [...session.entries, { kind: 'attempt', n: attempt.n }],
      }
    }
    case 'result':
      return { ...session, outcome: event.outcome, best: event.best, note: event.note }
    case 'done': {
      const { type: _, ...summary } = event
      return {
        ...session,
        status: 'done',
        summary,
        outcome: summary.outcome,
        best: summary.best,
        attempts: summary.attempts,
        note: summary.note,
      }
    }
    case 'error':
      return { ...session, status: 'error', error: event.message }
  }
}

export type Tone = 'ok' | 'warn' | 'bad' | 'busy'

/** A few words on how an attempt went, and how to color them. */
export function outcome(attempt: Attempt): { label: string; tone: Tone } {
  if (attempt.failure === 'out_of_memory') return { label: 'Out of memory', tone: 'bad' }
  if (attempt.failure === 'timeout') return { label: 'Ran out of time', tone: 'bad' }
  if (attempt.failure) return { label: 'Crashed', tone: 'bad' }
  if (!attempt.verdict) {
    if (attempt.state === 'running') return { label: `Measuring ${attempt.done}/${attempt.total}`, tone: 'busy' }
    return { label: attempt.state === 'queued' ? 'Waiting for a pod' : 'Starting the pod', tone: 'busy' }
  }
  if (attempt.verdict.fits) return { label: 'Fits', tone: 'ok' }
  if (!attempt.verdict.fps && !attempt.verdict.accuracy) return { label: 'Too slow, not accurate enough', tone: 'warn' }
  return { label: attempt.verdict.fps ? 'Not accurate enough' : 'Too slow', tone: 'warn' }
}

/** The configuration as the file an engineer would keep. */
export function asYaml(pipeline: Pipeline): string {
  return [
    `model: ${pipeline.model}`,
    `precision: ${pipeline.precision}`,
    `input_size: ${pipeline.input_size}`,
    `threads: ${pipeline.threads}`,
  ].join('\n')
}

/** How many configurations the zoo allows: every model, in every precision, size and number of threads. */
export function configurations(zoo: Zoo): number {
  return zoo.models.length * zoo.precisions.length * zoo.input_sizes.length * zoo.max_threads
}

export function formatCpu(cpu: number): string {
  return cpu === 1 ? '1 core' : `${cpu} cores`
}

/** The smallest "round" number (1, 1.5, 2, 3, 4, 5, 6 or 8 times a power of ten) that is not below `value`. */
export function niceCeil(value: number): number {
  const power = 10 ** Math.floor(Math.log10(value))
  const step = [1, 1.5, 2, 3, 4, 5, 6, 8, 10].find((multiple) => multiple * power >= value) ?? 10
  return step * power
}

export type Domain = { xMax: number; yMin: number; yMax: number }

/** How far the axes of the chart must reach to show the target and every measurement, with some air. */
export function chartDomain(targets: Targets, attempts: Attempt[]): Domain {
  const measured = attempts.flatMap((attempt) => (attempt.result ? [attempt.result] : []))
  const fastest = Math.max(targets.min_fps * 1.6, ...measured.map((result) => result.fps * 1.12))
  const lowest = Math.min(targets.min_accuracy - 8, ...measured.map((result) => result.accuracy - 4))
  return { xMax: niceCeil(fastest), yMin: Math.max(0, Math.floor(lowest / 10) * 10), yMax: 100 }
}

/** Evenly spaced values for the lines of an axis, ends included. */
export function ticks(from: number, to: number, count: number): number[] {
  return Array.from({ length: count + 1 }, (_, index) => from + ((to - from) * index) / count)
}
