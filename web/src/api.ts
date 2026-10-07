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

/** Asks a question and yields the events of the run. Aborting `signal` stops the run on the server too. */
export async function* askStream(question: string, signal: AbortSignal): AsyncGenerator<AgentEvent> {
  const response = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`The server answered ${response.status}`)
  }
  yield* jsonLines<AgentEvent>(chunksOf(response.body))
}

export async function fetchInfo(): Promise<Info> {
  const response = await fetch('/api/info')
  if (!response.ok) throw new Error(`The server answered ${response.status}`)
  return (await response.json()) as Info
}
