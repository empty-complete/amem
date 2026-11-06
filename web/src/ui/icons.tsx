import type { SVGProps } from "react";

const paths = {
  search: (
    <>
      <circle cx="7" cy="7" r="4.6" />
      <path d="M10.4 10.4 14 14" />
    </>
  ),
  plus: <path d="M8 3.2v9.6M3.2 8h9.6" />,
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
