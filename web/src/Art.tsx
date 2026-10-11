// Drawings made of SVG. They are part of the page, so they follow its colors
// and can show real values: the device is drawn with its own cores and memory.
import { useId } from 'react'

const CORES = [
  [84, 44],
  [114, 44],
  [84, 74],
  [114, 74],
]
const PINS = [48, 62, 76, 90, 104]

/**
 * A device as a chip on a board. Lit squares are CPU cores (half a core is half lit),
 * lit cells on the right are memory, 128 MB each.
 */
export function DeviceArt({ cpu, memory, live = false }: { cpu: number; memory: number; live?: boolean }) {
  const cells = Math.round(memory / 128)
  // Every drawing names its own gradient. With one shared name they would all use the first
  // one in the page, which paints nothing while the view it sits in is hidden.
  const gradient = `core-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  return (
    <svg className={live ? 'device-art live' : 'device-art'} viewBox="0 0 220 150" aria-hidden="true">
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--violet)" />
          <stop offset="1" stopColor="var(--cyan)" />
        </linearGradient>
      </defs>

      {/* the tracks of the board: they leave the pins and run to the edges */}
      <g className="tracks">
        <path d="M70 48H40V20H8M70 62H26M70 76H40V104H8M70 90H52V130H8M70 104H60V142" />
        <path d="M150 48H164M150 62H164M150 76H164M150 90H164M150 104H164" />
        <path d="M84 30V12H40M100 30V8M114 30V16H150V4M130 30V22" />
        <path d="M84 120V140M100 120V146M114 120V132H150V146M130 120V128" />
      </g>
      <g className="vias">
        <circle cx="8" cy="20" r="3" />
        <circle cx="26" cy="62" r="3" />
        <circle cx="8" cy="104" r="3" />
        <circle cx="8" cy="130" r="3" />
        <circle cx="40" cy="12" r="3" />
        <circle cx="100" cy="8" r="3" />
      </g>

      {PINS.map((position) => (
        <g key={position} className="pins">
          <path d={`M62 ${position}h8M150 ${position}h8M${position + 36} 22v8M${position + 36} 120v8`} />
        </g>
      ))}

      <rect className="body" x="70" y="30" width="80" height="80" rx="12" />
      {CORES.map(([x, y], index) => {
        const share = Math.max(0, Math.min(1, cpu - index))
        return (
          <g key={index}>
            <rect className="core" x={x} y={y} width="22" height="22" rx="5" />
            {share > 0 && (
              <rect
                className="lit"
                x={x}
                y={y + 22 * (1 - share)}
                width="22"
                height={22 * share}
                rx="5"
                fill={`url(#${gradient})`}
                style={{ animationDelay: `${index * 0.4}s` }}
              />
            )}
          </g>
        )
      })}

      <rect className="ram" x="164" y="38" width="48" height="74" rx="8" />
      {Array.from({ length: 8 }, (_, index) => (
        <rect
          key={index}
          className={index < cells ? 'cell lit' : 'cell'}
          x={index % 2 === 0 ? 170 : 190}
          y={96 - Math.floor(index / 2) * 17}
          width="16"
          height="11"
          rx="3"
        />
      ))}
    </svg>
  )
}
