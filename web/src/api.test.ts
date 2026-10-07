import { expect, test } from 'vitest'
import { jsonLines } from './api.ts'

const encoder = new TextEncoder()

/** Feeds the given byte chunks to jsonLines and collects what comes out. */
async function parse(chunks: Uint8Array[]): Promise<unknown[]> {
  async function* source() {
    yield* chunks
  }
  const values: unknown[] = []
  for await (const value of jsonLines<unknown>(source())) values.push(value)
  return values
}

test('one chunk can carry several lines', async () => {
  const values = await parse([encoder.encode('{"a":1}\n{"a":2}\n')])
  expect(values).toEqual([{ a: 1 }, { a: 2 }])
})

test('a line cut between two chunks is put back together', async () => {
  const values = await parse([encoder.encode('{"type":"ans'), encoder.encode('wer","text":"hi"}\n')])
  expect(values).toEqual([{ type: 'answer', text: 'hi' }])
})

test('a character cut between two chunks is put back together', async () => {
  const bytes = encoder.encode('{"text":"è"}\n')
  const cut = bytes.indexOf(0xc3) + 1 // in the middle of the two bytes of "è"
  const values = await parse([bytes.slice(0, cut), bytes.slice(cut)])
  expect(values).toEqual([{ text: 'è' }])
})

test('a last line without a newline is not lost', async () => {
  const values = await parse([encoder.encode('{"a":1}\n{"a":2}')])
  expect(values).toEqual([{ a: 1 }, { a: 2 }])
})

test('empty lines are skipped', async () => {
  const values = await parse([encoder.encode('\n{"a":1}\n\n')])
  expect(values).toEqual([{ a: 1 }])
})
