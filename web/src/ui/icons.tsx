import type { SVGProps } from "react";

const paths = {
  search: (
    <>
      <circle cx="7" cy="7" r="4.6" />
      <path d="M10.4 10.4 14 14" />
    </>
  ),
  plus: <path d="M8 3.2v9.6M3.2 8h9.6" />,
  menu: <path d="M2.6 4.4h10.8M2.6 8h10.8M2.6 11.6h10.8" />,
  theme: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M8 2.4v11.2A5.6 5.6 0 0 0 8 2.4Z" fill="currentColor" />
    </>
  ),
  user: (
    <>
      <circle cx="8" cy="5.8" r="2.6" />
      <path d="M3 14c.8-2.4 2.7-3.6 5-3.6s4.2 1.2 5 3.6" />
    </>
  ),
  folder: <path d="M2 4.5a1 1 0 0 1 1-1h3.4l1.4 1.5H13a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1Z" />,
  stack: (
    <>
      <path d="M8 2 14 5 8 8 2 5Z" />
      <path d="m2 8 6 3 6-3" />
      <path d="m2 11 6 3 6-3" />
    </>
  ),
  tag: (
    <>
      <path d="M2.5 2.5h5l6 6-5 5-6-6Z" />
      <circle cx="5.5" cy="5.5" r="1" />
    </>
  ),
  chev: <path d="M6 3.8 10.2 8 6 12.2" />,
  down: <path d="M3.8 6 8 10.2 12.2 6" />,
  check: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="m5.4 8.2 1.8 1.8 3.4-3.6" />
    </>
  ),
  clock: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.8V8l2.2 1.4" />
    </>
  ),
  cross: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="m5.9 5.9 4.2 4.2M10.1 5.9l-4.2 4.2" />
    </>
  ),
  dash: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M5.5 8h5" />
    </>
  ),
  warn: (
    <>
      <path d="M8 2.2 14.2 13H1.8Z" />
      <path d="M8 6.4v3" />
      <path d="M8 11.3v.1" />
    </>
  ),
  archive: (
    <>
      <rect x="2" y="3" width="12" height="3.5" rx="1" />
      <path d="M3 6.5v6.5h10V6.5M6.5 9.5h3" />
    </>
  ),
  inbox: (
    <>
      <path d="M2 9.5 3.8 3.5h8.4L14 9.5v3H2Z" />
      <path d="M2 9.5h3.4l.8 1.5h3.6l.8-1.5H14" />
    </>
  ),
  history: (
    <>
      <path d="M2.6 8a5.4 5.4 0 1 0 1.6-3.8" />
      <path d="M2.4 2.6v2.4h2.4" />
      <path d="M8 5.2V8l2 1.2" />
    </>
  ),
  pencil: <path d="m10.6 2.6 2.8 2.8L6 12.8l-3.4.6.6-3.4Z" />,
  code: <path d="M5.6 4.4 2 8l3.6 3.6M10.4 4.4 14 8l-3.6 3.6" />,
  more: (
    <>
      <circle cx="3.6" cy="8" r=".6" fill="currentColor" />
      <circle cx="8" cy="8" r=".6" fill="currentColor" />
      <circle cx="12.4" cy="8" r=".6" fill="currentColor" />
    </>
  ),
  file: (
    <>
      <path d="M4 2h5l3 3v9H4Z" />
      <path d="M9 2v3h3" />
    </>
  ),
  link: (
    <>
      <path d="M6.6 9.4a2.6 2.6 0 0 0 3.7 0l2.2-2.2a2.6 2.6 0 0 0-3.7-3.7l-.9.9" />
      <path d="M9.4 6.6a2.6 2.6 0 0 0-3.7 0L3.5 8.8a2.6 2.6 0 0 0 3.7 3.7l.9-.9" />
    </>
  ),
  copy: (
    <>
      <rect x="5.4" y="5.4" width="8" height="8" rx="1.4" />
      <path d="M10.6 5.4V3.6a1 1 0 0 0-1-1H3.6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h1.8" />
    </>
  ),
  external: <path d="M9 3h4v4M13 3 7.4 8.6M11 9.6V13H3V5h3.4" />,
  hash: <path d="M5.6 2.4 4.4 13.6M11.6 2.4l-1.2 11.2M2.6 5.8h11M2 10.2h11" />,
  calendar: (
    <>
      <rect x="2.4" y="3.4" width="11.2" height="10" rx="1.4" />
      <path d="M2.4 6.6h11.2M5.4 2v2.6M10.6 2v2.6" />
    </>
  ),
  ruler: <path d="m2.4 10.6 8.2-8.2 3 3-8.2 8.2Zm2.6-2.6 1.4 1.4M7 6l1.4 1.4M9 4l1.4 1.4" />,
  shield: <path d="M8 2 3 4v4c0 3 2.2 5 5 6 2.8-1 5-3 5-6V4Z" />,
} as const;

export type IconName = keyof typeof paths;

/** Значок из одного набора, 16 px, всегда рядом с текстом или с подписью-подсказкой. */
export function Icon({
  name,
  size = 16,
  ...rest
}: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ flexShrink: 0 }}
      {...rest}
    >
      {paths[name]}
    </svg>
  );
}
