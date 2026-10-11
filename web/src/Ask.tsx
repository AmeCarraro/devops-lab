import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { askStream } from './api.ts'
import type { Step, Summary } from './api.ts'
import * as icons from './icons.tsx'
import { splitBlocks, splitInline } from './markdown.ts'

/** One question and everything the agent did for it. */
type Run = {
  id: number
  question: string
  status: 'running' | 'done' | 'stopped' | 'error'
  steps: Step[]
  sources: string[]
  answer: string
  summary?: Summary
  error?: string
}

/** A question that comes from another view; `n` tells two identical ones apart. */
export type Seed = { n: number; text: string }

const EXAMPLES = [
  'How do I stop the local cluster?',
  'Come cambio il modello di chat?',
  'What keeps a run inside the sandbox?',
  'Is the project already running on AWS?',
]

const ENDINGS: Record<Summary['finished_by'], string> = {
  finish: 'The model decided it had everything',
  answer: 'The model started answering by itself',
  max_steps: 'The model used all its steps',
}

function describeStep(step: Step): { what: string; detail: string; result: string } {
  const argument = (name: string) => String(step.arguments[name] ?? '')
  if (step.tool === 'finish') {
    if (step.refused === 'missing') {
      return { what: 'Tried to stop', detail: argument('missing'), result: 'sent back: something is missing' }
    }
    if (step.refused) return { what: 'Tried to stop', detail: '', result: 'sent back: one search is not enough' }
    return { what: 'Stopped searching', detail: '', result: 'nothing missing' }
  }
  const what =
    step.tool === 'search_docs' ? 'Searched by meaning' : step.tool === 'search_by_name' ? 'Opened by name' : step.tool
  const detail = argument(step.tool === 'search_by_name' ? 'name' : 'query')
  if (step.refused) return { what, detail, result: 'skipped: already done' }
  const count = step.new_excerpts ?? 0
  return { what, detail, result: count === 0 ? 'nothing new' : `${count} new excerpt${count === 1 ? '' : 's'}` }
}

function Answer({ run }: { run: Run }) {
  return splitBlocks(run.answer).map((block, index) =>
    block.kind === 'code' ? (
      <pre key={index}>
        <code>{block.text}</code>
      </pre>
    ) : (
      <p key={index}>
        {splitInline(block.text).map((piece, position) => {
          switch (piece.kind) {
            case 'code':
              return <code key={position}>{piece.text}</code>
            case 'bold':
              return <strong key={position}>{piece.text}</strong>
            case 'cite': {
              // a number the model made up, with no source behind it, stays plain text
              const source = run.sources[piece.number - 1]
              if (!source) return `[${piece.number}]`
              return (
                <a key={position} className="cite" href={`#run-${run.id}-source-${piece.number}`} title={source}>
                  {piece.number}
                </a>
              )
            }
            case 'plain':
              return piece.text
          }
        })}
      </p>
    ),
  )
}

function RunCard({ run }: { run: Run }) {
  return (
    <article className="card run rise">
      <h2 className="question">{run.question}</h2>

      <ol className="trace" aria-label="What the model did">
        {run.steps.map((step, index) => {
          const { what, detail, result } = describeStep(step)
          return (
            <li key={index} className={step.refused ? 'refused' : undefined}>
              <span className="trace-icon">{step.tool === 'finish' ? <icons.Check /> : <icons.Search />}</span>
              <span className="what">{what}</span>
              {detail && <q>{detail}</q>}
              <span className="result">{result}</span>
            </li>
          )
        })}
        {run.status === 'running' && !run.answer && (
          <li className="working">
            <span className="trace-icon">
              <icons.Spark />
            </span>
            <span className="what">Thinking…</span>
          </li>
        )}
      </ol>

      {run.answer && (
        <div className={run.status === 'running' ? 'answer writing' : 'answer'} aria-live="polite">
          <Answer run={run} />
        </div>
      )}
      {run.status === 'error' && (
        <p className="notice error" role="alert">
          {run.error}
        </p>
      )}
      {run.status === 'stopped' && <p className="notice">Stopped.</p>}

      {run.sources.length > 0 && (
        <section className="sources">
          <h3 className="eyebrow">Sections it read</h3>
          <ol>
            {run.sources.map((source, index) => (
              <li key={source} id={`run-${run.id}-source-${index + 1}`}>
                <span className="mono">{index + 1}</span>
                <code>{source}</code>
              </li>
            ))}
          </ol>
        </section>
      )}

      {run.summary && (
        <p className="ending">
          {ENDINGS[run.summary.finished_by]} · {run.summary.seconds.toFixed(1)} s · {run.summary.model}
        </p>
      )}
    </article>
  )
}

export default function Ask({ active, seed }: { active: boolean; seed: Seed | null }) {
  const [runs, setRuns] = useState<Run[]>([])
  const [question, setQuestion] = useState('')
  const controller = useRef<AbortController | null>(null)
  const nextId = useRef(1)
  const seeded = useRef(0)
  const bottom = useRef<HTMLDivElement>(null)
  const running = runs.at(-1)?.status === 'running'

  useEffect(() => {
    if (active) bottom.current?.scrollIntoView({ block: 'end' })
  }, [runs, active])

  function patch(id: number, change: (run: Run) => Partial<Run>) {
    setRuns((all) => all.map((run) => (run.id === id ? { ...run, ...change(run) } : run)))
  }

  async function ask(text: string) {
    const id = nextId.current++
    const abort = new AbortController()
    controller.current = abort
    setRuns((all) => [...all, { id, question: text, status: 'running', steps: [], sources: [], answer: '' }])

    let finished = false
    try {
      for await (const event of askStream(text, abort.signal)) {
        switch (event.type) {
          case 'step':
            patch(id, (run) => ({ steps: [...run.steps, event] }))
            break
          case 'sources':
            patch(id, () => ({ sources: event.sources }))
            break
          case 'answer':
            patch(id, (run) => ({ answer: run.answer + event.text }))
            break
          case 'done':
            finished = true
            patch(id, () => ({ status: 'done', summary: event, answer: event.answer, sources: event.sources }))
            break
          case 'error':
            finished = true
            patch(id, () => ({ status: 'error', error: event.message }))
            break
        }
      }
      if (!finished) {
        patch(id, () => ({ status: 'error', error: 'The connection closed before the answer was complete.' }))
      }
    } catch (error) {
      // aborting the request is how Stop works, so that is not a failure
      patch(id, () =>
        abort.signal.aborted
          ? { status: 'stopped' }
          : { status: 'error', error: error instanceof Error ? error.message : String(error) },
      )
    }
  }

  // a question chosen in another view is asked once, when it arrives
  useEffect(() => {
    if (seed && seed.n !== seeded.current) {
      seeded.current = seed.n
      void ask(seed.text)
    }
  })

  function submit(event: { preventDefault(): void }) {
    event.preventDefault()
    const text = question.trim()
    if (!text || running) return
    setQuestion('')
    void ask(text)
  }

  function sendOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <div className="ask">
      <div className="runs">
        {runs.length === 0 && (
          <section className="ask-empty rise">
            <span className="ask-mark">
              <icons.Book />
            </span>
            <h1>
              Ask the <span className="grad">documentation.</span>
            </h1>
            <p className="lead">
              A small model running on this machine searches the project documentation, one step at a time, and answers
              with the sections it read. Any language works.
            </p>
            <ul className="examples">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button type="button" onClick={() => void ask(example)}>
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {runs.map((run) => (
          <RunCard key={run.id} run={run} />
        ))}
      </div>

      <form className="composer" onSubmit={submit}>
        <textarea
          aria-label="Your question"
          placeholder="Ask about the project"
          rows={1}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={sendOnEnter}
        />
        {running ? (
          <button type="button" className="round stop" aria-label="Stop" onClick={() => controller.current?.abort()}>
            <icons.Stop />
          </button>
        ) : (
          <button type="submit" className="round" aria-label="Ask" disabled={!question.trim()}>
            <icons.Send />
          </button>
        )}
      </form>
      {/* after the form, so that scrolling to it reaches the real end of the page */}
      <div ref={bottom} />
    </div>
  )
}
