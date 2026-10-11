import { expect, test } from 'vitest'
import type { Attempt, FitEvent } from './api.ts'
import { apply, asYaml, chartDomain, configurations, newSession, niceCeil, outcome, ticks } from './fit.ts'

const DEVICE = { cpu: 1, memory_mb: 512 }
const TARGETS = { min_fps: 30, min_accuracy: 85 }

function attempt(change: Partial<Attempt> = {}): Attempt {
  return {
    n: 1,
    pipeline: { model: 'resnet50', precision: 'int8', input_size: 224, threads: 1 },
    reason: 'accurate, and int8 makes it fast',
    state: 'queued',
    done: 0,
    total: 0,
    result: null,
    failure: '',
    message: '',
    verdict: null,
    ...change,
  }
}

const measured = (fps: number, accuracy: number) => ({
  fps,
  accuracy,
  latency_ms: 10,
  latency_p95_ms: 12,
  memory_mb: 120,
  model_mb: 26,
  images: 200,
  predictions: [],
})

function play(events: FitEvent[]) {
  return events.reduce(apply, newSession(DEVICE, TARGETS))
}

test('an attempt is listed once, however many times its state changes', () => {
  const session = play([
    { type: 'attempt', ...attempt() },
    { type: 'attempt', ...attempt({ state: 'running', done: 40, total: 200 }) },
    { type: 'attempt', ...attempt({ state: 'running', done: 120, total: 200 }) },
  ])

  expect(session.entries).toEqual([{ kind: 'attempt', n: 1 }])
  expect(session.attempts).toHaveLength(1)
  expect(session.attempts[0].done).toBe(120)
})

test('looks at the documentation and attempts keep the order they happened in', () => {
  const session = play([
    { type: 'step', tool: 'search_docs', arguments: { query: 'fastest model' }, new_excerpts: 2 },
    { type: 'attempt', ...attempt() },
    { type: 'step', tool: 'run_pipeline', arguments: {}, refused: 'repeated' },
    { type: 'attempt', ...attempt({ n: 2 }) },
  ])

  expect(session.entries.map((entry) => (entry.kind === 'step' ? entry.step.tool : entry.n))).toEqual([
    'search_docs',
    1,
    'run_pipeline',
    2,
  ])
})

test('the result arrives with its words, before the final event', () => {
  const running = play([
    { type: 'attempt', ...attempt() },
    { type: 'result', outcome: 'fits', best: 1, note: 'Use resnet50.' },
  ])

  expect(running.status).toBe('running')
  expect(running.outcome).toBe('fits')
  expect(running.best).toBe(1)
  expect(running.note).toBe('Use resnet50.')
})

test('the final event replaces what was collected on the way', () => {
  const final = attempt({ state: 'done', result: measured(40, 87), verdict: { fits: true, fps: true, accuracy: true } })
  const session = play([
    { type: 'attempt', ...attempt() },
    { type: 'done', outcome: 'fits', best: 1, attempts: [final], note: 'Use attempt 1.', steps: 3, model: 'm', seconds: 20 },
  ])

  expect(session.status).toBe('done')
  expect(session.attempts[0].result?.fps).toBe(40)
  expect(session.note).toBe('Use attempt 1.')
})

test('an error ends the session and keeps what was measured', () => {
  const session = play([{ type: 'attempt', ...attempt() }, { type: 'error', message: 'sandbox down' }])

  expect(session.status).toBe('error')
  expect(session.error).toBe('sandbox down')
  expect(session.attempts).toHaveLength(1)
})

test('an attempt is described by how it went', () => {
  expect(outcome(attempt()).label).toBe('Waiting for a pod')
  expect(outcome(attempt({ state: 'starting' })).label).toBe('Starting the pod')
  expect(outcome(attempt({ state: 'running', done: 40, total: 200 }))).toEqual({ label: 'Measuring 40/200', tone: 'busy' })
  expect(outcome(attempt({ state: 'failed', failure: 'out_of_memory' }))).toEqual({ label: 'Out of memory', tone: 'bad' })
  expect(outcome(attempt({ verdict: { fits: true, fps: true, accuracy: true } }))).toEqual({ label: 'Fits', tone: 'ok' })
  expect(outcome(attempt({ verdict: { fits: false, fps: false, accuracy: true } })).label).toBe('Too slow')
  expect(outcome(attempt({ verdict: { fits: false, fps: true, accuracy: false } })).label).toBe('Not accurate enough')
})

test('a configuration is written as the file one would keep', () => {
  expect(asYaml(attempt().pipeline)).toBe('model: resnet50\nprecision: int8\ninput_size: 224\nthreads: 1')
})

test('the size of the search space is the product of the choices', () => {
  expect(configurations({ models: ['a', 'b', 'c', 'd', 'e'], precisions: ['fp32', 'int8'], input_sizes: [1, 2, 3, 4], max_threads: 4 })).toBe(160)
})

test('axis ends are round numbers', () => {
  expect([1, 13, 48, 50, 51, 208, 320].map(niceCeil)).toEqual([1, 15, 50, 50, 60, 300, 400])
})

test('the chart always shows the target, and stretches to hold every measurement', () => {
  expect(chartDomain(TARGETS, [])).toEqual({ xMax: 50, yMin: 70, yMax: 100 })

  const far = [attempt({ result: measured(286, 1.5) }), attempt({ n: 2, result: measured(58, 87.5) })]
  expect(chartDomain(TARGETS, far)).toEqual({ xMax: 400, yMin: 0, yMax: 100 })
})

test('ticks are evenly spaced and include both ends', () => {
  expect(ticks(0, 50, 5)).toEqual([0, 10, 20, 30, 40, 50])
})
