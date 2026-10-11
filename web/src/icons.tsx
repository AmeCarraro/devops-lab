// The icons of the page, drawn here as SVG: no icon font and no download.
// They take the color and the size of the text around them.
import type { ReactNode, SVGProps } from 'react'

type Props = SVGProps<SVGSVGElement>

function Icon({ children, ...props }: Props & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

/** The mark of the page: a chip with a lens in it. */
export function Logo(props: Props) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id="logo-fill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b6cff" />
          <stop offset="1" stopColor="#38d6f5" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="24" height="24" rx="7" fill="url(#logo-fill)" />
      <path
        d="M11 1.5v3M16 1.5v3M21 1.5v3M11 27.5v3M16 27.5v3M21 27.5v3M1.5 11h3M1.5 16h3M1.5 21h3M27.5 11h3M27.5 16h3M27.5 21h3"
        stroke="url(#logo-fill)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="16" cy="16" r="5.2" fill="none" stroke="#fff" strokeWidth="2.2" />
      <circle cx="16" cy="16" r="1.6" fill="#fff" />
    </svg>
  )
}

export const Chip = (props: Props) => (
  <Icon {...props}>
    <rect x="6" y="6" width="12" height="12" rx="2.5" />
    <rect x="9.75" y="9.75" width="4.5" height="4.5" rx="1" />
    <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
  </Icon>
)

export const Spark = (props: Props) => (
  <Icon {...props}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
    <path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" />
  </Icon>
)

export const Search = (props: Props) => (
  <Icon {...props}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Icon>
)

export const Book = (props: Props) => (
  <Icon {...props}>
    <path d="M5 4.5h10a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z" />
    <path d="M5 17a3 3 0 0 1 3-3h10M9 8.5h5" />
  </Icon>
)

export const Home = (props: Props) => (
  <Icon {...props}>
    <rect x="3.5" y="3.5" width="7" height="9" rx="2" />
    <rect x="13.5" y="3.5" width="7" height="5" rx="2" />
    <rect x="13.5" y="11.5" width="7" height="9" rx="2" />
    <rect x="3.5" y="15.5" width="7" height="5" rx="2" />
  </Icon>
)

export const Target = (props: Props) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="0.8" fill="currentColor" />
  </Icon>
)

export const Bolt = (props: Props) => (
  <Icon {...props}>
    <path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z" />
  </Icon>
)

export const Memory = (props: Props) => (
  <Icon {...props}>
    <rect x="3" y="7" width="18" height="10" rx="2" />
    <path d="M7 11v2M11 11v2M15 11v2M6 17v2.5M10 17v2.5M14 17v2.5M18 17v2.5" />
  </Icon>
)

export const Shield = (props: Props) => (
  <Icon {...props}>
    <path d="M12 3l7.5 2.8v5.4c0 4.6-3 8.3-7.5 9.8-4.5-1.5-7.5-5.2-7.5-9.8V5.8z" />
    <path d="M9 12l2.2 2.2L15.2 10" />
  </Icon>
)

export const Gauge = (props: Props) => (
  <Icon {...props}>
    <path d="M4.5 17a8.5 8.5 0 1 1 15 0" />
    <path d="M12 13.5l4-4.5" />
    <circle cx="12" cy="13.5" r="1.2" fill="currentColor" />
  </Icon>
)

export const Check = (props: Props) => (
  <Icon {...props}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Icon>
)

export const Cross = (props: Props) => (
  <Icon {...props}>
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </Icon>
)

export const Arrow = (props: Props) => (
  <Icon {...props}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
)

export const Play = (props: Props) => (
  <Icon {...props}>
    <path d="M8 5.5v13l10.5-6.5z" fill="currentColor" />
  </Icon>
)

export const Stop = (props: Props) => (
  <Icon {...props}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" />
  </Icon>
)

export const Send = (props: Props) => (
  <Icon {...props}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Icon>
)

export const Sun = (props: Props) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" />
  </Icon>
)

export const Moon = (props: Props) => (
  <Icon {...props}>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
  </Icon>
)

export const Layers = (props: Props) => (
  <Icon {...props}>
    <path d="M12 3.5l9 4.8-9 4.8-9-4.8z" />
    <path d="M3 12.5l9 4.8 9-4.8M3 16.7l9 4.8 9-4.8" />
  </Icon>
)

export const Eye = (props: Props) => (
  <Icon {...props}>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="2.8" />
  </Icon>
)
