import { expect, test } from 'vitest'
import { gigabytes, isDesktop, shortName } from './desktop.ts'

test('outside the desktop app the page knows it has no native side', () => {
  expect(isDesktop).toBe(false)
})

test('the name of the card is shortened to its model', () => {
  expect(shortName('NVIDIA GeForce RTX 3050 Ti Laptop GPU')).toBe('RTX 3050 Ti')
  expect(shortName('NVIDIA RTX A2000')).toBe('RTX A2000')
})

test('memory is shown in gigabytes with one decimal', () => {
  expect(gigabytes(3025)).toBe('3.0')
  expect(gigabytes(4096)).toBe('4.0')
})
