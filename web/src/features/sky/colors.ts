import { type RefObject, useEffect, useState } from "react";

export interface SkyColors {
  sky: string;
  sky2: string;
  ink: string;
  muted: string;
  focus: string;
  font: string;
  fam: Record<"source" | "work" | "object", string>;
}

/** Цвета неба из токенов CSS — в JS ни одного литерала цвета. */
export function skyColors(el: Element): SkyColors {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    sky: v("--sky"),
    sky2: v("--sky-2"),
    ink: v("--sky-ink"),
    muted: v("--sky-muted"),
    focus: v("--focus"),
    font: v("--font") || "system-ui",
    fam: { source: v("--fam-source"), work: v("--fam-work"), object: v("--fam-object") },
  };
}

/** Перечитывает цвета при смене темы: атрибут data-theme у <html> и системная схема. */
export function useSkyColors(ref: RefObject<Element | null>) {
  const [colors, setColors] = useState<SkyColors | null>(null);
  useEffect(() => {
    const read = () => ref.current && setColors(skyColors(ref.current));
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", read);
    return () => {
      mo.disconnect();
      mq?.removeEventListener?.("change", read);
    };
  }, [ref]);
  return colors;
}

export function useReducedMotion() {
  const q = "(prefers-reduced-motion: reduce)";
  const [r, setR] = useState(() => !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    const on = () => setR(!!mq?.matches);
    mq?.addEventListener?.("change", on);
    return () => mq?.removeEventListener?.("change", on);
  }, []);
  return r;
}
