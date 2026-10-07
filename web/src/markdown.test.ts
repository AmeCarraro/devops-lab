import { expect, test } from 'vitest'
import { splitBlocks, splitInline } from './markdown.ts'

test('a fenced block becomes code, without its language tag', () => {
  const blocks = splitBlocks('Run this:\n\n```powershell\ndocker compose stop\n```\n\nThen wait.')
  expect(blocks).toEqual([
    { kind: 'text', text: 'Run this:' },
    { kind: 'code', text: 'docker compose stop' },
    { kind: 'text', text: 'Then wait.' },
  ])
})

test('a fence the model has not closed yet is already shown as code', () => {
  expect(splitBlocks('Run:\n```\ndocker comp')).toEqual([
    { kind: 'text', text: 'Run:' },
    { kind: 'code', text: 'docker comp' },
  ])
})

test('inline code, bold and citations are recognised', () => {
  expect(splitInline('Use `kubectl` on **demo** [2].')).toEqual([
    { kind: 'plain', text: 'Use ' },
    { kind: 'code', text: 'kubectl' },
    { kind: 'plain', text: ' on ' },
    { kind: 'bold', text: 'demo' },
    { kind: 'plain', text: ' ' },
    { kind: 'cite', number: 2 },
    { kind: 'plain', text: '.' },
  ])
})

test('text that only looks like markup stays plain', () => {
  expect(splitInline('a [x] b ` c')).toEqual([{ kind: 'plain', text: 'a [x] b ` c' }])
})
