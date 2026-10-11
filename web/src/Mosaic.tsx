import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { SPRITE } from './api.ts'
import type { Samples } from './api.ts'

type Props = {
  samples: Samples
  /** How many pictures to show, from the first one. */
  count: number
  columns: number
  /** While a run measures: how many pictures the pipeline has seen. The others stay dim. */
  seen?: number
  /** After a run: the class the model answered for every picture, to mark right and wrong. */
  predictions?: number[]
  /** With no run to show: move a frame from picture to picture and name what is in it. */
  ambient?: boolean
}

/**
 * The pictures the pipelines are measured on. They come as one sprite, a single
 * image that holds them all, and every tile shows its own piece of it.
 */
export default function Mosaic({ samples, count, columns, seen, predictions, ambient }: Props) {
  const [focus, setFocus] = useState(0)
  const shown = Math.min(count, samples.labels.length)
  const rows = Math.ceil(samples.labels.length / samples.columns)

  useEffect(() => {
    if (!ambient) return
    const timer = setInterval(() => setFocus(Math.floor(Math.random() * shown)), 1500)
    return () => clearInterval(timer)
  }, [ambient, shown])

  const frame = {
    '--columns': columns,
    '--sprite': `url("${SPRITE}")`,
    '--sprite-size': `${samples.columns * 100}% ${rows * 100}%`,
  } as CSSProperties

  return (
    <div className={ambient ? 'mosaic ambient' : 'mosaic'} style={frame}>
      {Array.from({ length: shown }, (_, index) => {
        const label = samples.classes[samples.labels[index]]
        const predicted = predictions?.[index]
        const right = predicted === samples.labels[index]
        const classes = ['tile']
        if (seen !== undefined && index >= seen) classes.push('unseen')
        if (predicted !== undefined) classes.push(right ? 'right' : 'wrong')
        if (ambient && index === focus) classes.push('focus')
        const column = index % samples.columns
        const row = Math.floor(index / samples.columns)
        return (
          <span
            key={index}
            className={classes.join(' ')}
            title={predicted === undefined || right ? label : `${label} · the model said: ${samples.classes[predicted]}`}
            style={{
              backgroundPosition: `${(column / (samples.columns - 1)) * 100}% ${(row / Math.max(1, rows - 1)) * 100}%`,
              // tiles light up one after the other inside each batch of ten the server reports
              transitionDelay: `${(index % 10) * 45}ms`,
            }}
          >
            {ambient && index === focus && <em>{label}</em>}
          </span>
        )
      })}
    </div>
  )
}
