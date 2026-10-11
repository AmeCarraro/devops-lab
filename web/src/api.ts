// The contract with the agent (app/main.py), written as types: the compiler then
// checks that the page handles every kind of event the server can send.

/** One tool call of the research loop. */
export type Step = {
  tool: string
  arguments: Record<string, unknown>
  /** How many excerpts the call added; absent when the call was not executed. */
  new_excerpts?: number
  /** Why the agent turned the call down, if it did. */
  refused?: 'too_early' | 'missing' | 'repeated'
}

export type Summary = {
  answer: string
  sources: string[]
  steps: Step[]
  finished_by: 'finish' | 'answer' | 'max_steps'
  model: string
  seconds: number
}

/** The events of POST /api/ask/stream, one JSON object per line. */
export type AgentEvent =
  | ({ type: 'step' } & Step)
  | { type: 'sources'; sources: string[] }
  | { type: 'answer'; text: string }
  | ({ type: 'done' } & Summary)
  | { type: 'error'; message: string }

export type Info = { version: string; pod: string; model: string }

/** One configuration of the vision pipeline: what the agent chooses and the sandbox runs. */
export type Pipeline = {
  model: string
  precision: 'fp32' | 'int8'
  input_size: number
  threads: number
}

/** The device the pipeline must fit in: the limits of the pod that runs it. */
export type Device = { cpu: number; memory_mb: number }

export type Targets = { min_fps: number; min_accuracy: number }

/** What a run measured. `predictions` is the class the model answered for every picture. */
export type Measurement = {
  fps: number
  accuracy: number
  latency_ms: number
  latency_p95_ms: number
  memory_mb: number
  model_mb: number
  images: number
  predictions: number[]
}

/** One configuration tried on the device. The same attempt is sent again every time its state changes. */
export type Attempt = {
  n: number
  pipeline: Pipeline
  reason: string
  state: 'queued' | 'starting' | 'running' | 'done' | 'failed'
  /** Pictures measured so far, out of `total`. */
  done: number
  total: number
  result: Measurement | null
  failure: '' | 'out_of_memory' | 'timeout' | 'error'
  message: string
  /** Which targets the measurement meets; null until there is one. */
  verdict: { fits: boolean; fps: boolean; accuracy: boolean } | null
}

export type FitSummary = {
  /** `fits`: an attempt met every target. `closest`: none did, `best` is the nearest. `none`: nothing could be measured. */
  outcome: 'fits' | 'closest' | 'none'
  best: number | null
  attempts: Attempt[]
  /** The result in words, written by the agent from the measurements. */
  note: string
  steps: number
  model: string
  seconds: number
}

/** The events of POST /api/fit/stream, one JSON object per line. */
export type FitEvent =
  | ({ type: 'step' } & FitStep)
  | ({ type: 'attempt' } & Attempt)
  | { type: 'result'; outcome: FitSummary['outcome']; best: number | null; note: string }
  | ({ type: 'done' } & FitSummary)
  | { type: 'error'; message: string }

/** A step of the fit loop that is not a run: a look at the documentation, or a call the agent turned down. */
export type FitStep = {
  tool: string
  arguments: Record<string, unknown>
  /** Present when the agent made the lookup for the model, absent when the model asked for it. */
  by?: 'agent'
  new_excerpts?: number
  refused?: 'repeated' | 'invalid' | 'no_call'
  message?: string
}

/** What a pipeline can be made of: the choices the sandbox accepts. */
export type Zoo = { models: string[]; precisions: string[]; input_sizes: number[]; max_threads: number }

/** The pictures the pipelines are measured on: one sprite, and for every picture the class it shows. */
export type Samples = {
  tile: number
  columns: number
  labels: number[]
  classes: string[]
}

// In the browser the page and the API share one address, so paths are enough.
// The desktop app is not served by the cluster and needs the full address (web/.env.desktop).
const BASE: string = import.meta.env.VITE_API_BASE ?? ''

export const SPRITE = `${BASE}/samples/sprite.jpg`

/**
 * Turns a stream of bytes into the JSON values it carries, one per line.
 * A chunk can end in the middle of a line, or even of a character, so the
 * unfinished tail is kept and completed by the next chunk.
 */
export async function* jsonLines<T>(chunks: AsyncIterable<Uint8Array>): AsyncGenerator<T> {
  const decoder = new TextDecoder()
  let pending = ''
  for await (const chunk of chunks) {
    pending += decoder.decode(chunk, { stream: true })
    const lines = pending.split('\n')
    pending = lines.pop() ?? ''
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line) as T
    }
  }
  pending += decoder.decode()
  if (pending.trim()) yield JSON.parse(pending) as T
}

async function* chunksOf(body: ReadableStream<Uint8Array>): AsyncGenerator<Uint8Array> {
  const reader = body.getReader()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) return
      yield value
    }
  } finally {
    reader.releaseLock()
  }
}

async function* stream<T>(path: string, body: unknown, signal: AbortSignal): AsyncGenerator<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`The server answered ${response.status}`)
  }
  yield* jsonLines<T>(chunksOf(response.body))
}

/** Asks a question and yields the events of the run. Aborting `signal` stops the run on the server too. */
export function askStream(question: string, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  return stream<AgentEvent>('/api/ask/stream', { question }, signal)
}

/** Asks the agent to fit a pipeline to a device and yields what it tries. Aborting `signal` stops it. */
export function fitStream(device: Device, targets: Targets, signal: AbortSignal): AsyncGenerator<FitEvent> {
  return stream<FitEvent>('/api/fit/stream', { device, targets }, signal)
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`)
  if (!response.ok) throw new Error(`The server answered ${response.status}`)
  return (await response.json()) as T
}

export const fetchInfo = () => get<Info>('/api/info')

export const fetchZoo = () => get<Zoo>('/api/zoo')

export const fetchSamples = () => get<Samples>('/samples/samples.json')
