import type { Attempt, Targets } from './api.ts'
import { chartDomain, ticks } from './fit.ts'

const WIDTH = 560
const HEIGHT = 340
const LEFT = 46
const RIGHT = 18
const TOP = 30
const BOTTOM = 40

type Props = {
  targets: Targets
  attempts: Attempt[]
  selected: number | null
  onSelect: (n: number) => void
}

/**
 * Every measured attempt as a point: speed to the right, accuracy upwards.
 * The lit corner is the target, and a configuration fits when its point is inside it.
 * The line joins the attempts in the order the agent made them.
 */
export default function Chart({ targets, attempts, selected, onSelect }: Props) {
  const domain = chartDomain(targets, attempts)
  const x = (fps: number) => LEFT + (Math.min(fps, domain.xMax) / domain.xMax) * (WIDTH - LEFT - RIGHT)
  const y = (accuracy: number) =>
    TOP + ((domain.yMax - Math.max(accuracy, domain.yMin)) / (domain.yMax - domain.yMin)) * (HEIGHT - TOP - BOTTOM)
  const measured = attempts.filter((attempt) => attempt.result)
  const path = measured.map((attempt) => `${x(attempt.result!.fps)},${y(attempt.result!.accuracy)}`).join(' ')

  return (
    <svg className="chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Speed and accuracy of every attempt">
      <defs>
        <linearGradient id="zone" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="var(--ok)" stopOpacity="0.05" />
          <stop offset="1" stopColor="var(--ok)" stopOpacity="0.3" />
        </linearGradient>
        <linearGradient id="trail" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="var(--violet)" />
          <stop offset="1" stopColor="var(--cyan)" />
        </linearGradient>
      </defs>

      {ticks(domain.yMin, domain.yMax, 4).map((value) => (
        <g key={`y${value}`}>
          <line className="grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(value)} y2={y(value)} />
          <text className="tick" x={LEFT - 9} y={y(value) + 4} textAnchor="end">
            {Math.round(value)}
          </text>
        </g>
      ))}
      {ticks(0, domain.xMax, 5).map((value) => (
        <g key={`x${value}`}>
          <line className="grid" x1={x(value)} x2={x(value)} y1={TOP} y2={HEIGHT - BOTTOM} />
          <text className="tick" x={x(value)} y={HEIGHT - BOTTOM + 17} textAnchor="middle">
            {Math.round(value)}
          </text>
        </g>
      ))}
      <text className="axis" x={WIDTH - RIGHT} y={HEIGHT - 5} textAnchor="end">
        images per second →
      </text>
      <text className="axis" x={4} y={12} textAnchor="start">
        ↑ accuracy %
      </text>

      {/* the target: fast enough is to the right of the vertical line, accurate enough above the horizontal one */}
      <rect
        className="zone"
        x={x(targets.min_fps)}
        y={TOP}
        width={WIDTH - RIGHT - x(targets.min_fps)}
        height={y(targets.min_accuracy) - TOP}
        fill="url(#zone)"
      />
      <line className="limit" x1={x(targets.min_fps)} x2={x(targets.min_fps)} y1={TOP} y2={HEIGHT - BOTTOM} />
      <line className="limit" x1={LEFT} x2={WIDTH - RIGHT} y1={y(targets.min_accuracy)} y2={y(targets.min_accuracy)} />
      <text className="zone-label" x={WIDTH - RIGHT - 10} y={TOP + 20} textAnchor="end">
        target
      </text>

      {measured.length > 1 && <polyline className="trail" points={path} stroke="url(#trail)" />}

      {measured.map((attempt) => {
        const fits = attempt.verdict?.fits
        return (
          <g
            key={attempt.n}
            className={`point ${fits ? 'fits' : 'misses'} ${attempt.n === selected ? 'selected' : ''}`}
            transform={`translate(${x(attempt.result!.fps)} ${y(attempt.result!.accuracy)})`}
            onClick={() => onSelect(attempt.n)}
          >
            <title>
              {`Attempt ${attempt.n}: ${attempt.result!.fps} images/s, ${attempt.result!.accuracy}% accurate`}
            </title>
            {fits && <circle className="halo" r="20" />}
            <circle className="body" r="12" />
            <text y="4" textAnchor="middle">
              {attempt.n}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
