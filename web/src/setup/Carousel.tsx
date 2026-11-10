import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Lang } from "./bridge";

/** Сюжеты README (docs/assets/readme/<язык>/demo-*.gif): новый сюжет там же попадает и в README, и сюда — если его
 * имя есть в SCENES и подпись в carousel.<имя>. */
const SCENES = ["sky", "write", "source", "review", "card"] as const;
const FILES = import.meta.glob("../../../docs/assets/readme/*/demo-*.gif", {
  query: "?url",
  import: "default",
  eager: true,
}) as Record<string, string>;
const PERIOD = 7000; // мс на сюжет

function scenes(lang: Lang) {
  return SCENES.flatMap((name) => {
    const url = FILES[`../../../docs/assets/readme/${lang}/demo-${name}.gif`];
    return url ? [{ name, url }] : [];
  });
}

function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** «Что умеет amemo» на экране установки: анимация и подпись, смена каждые 7 с; пауза — кнопкой, наведением и
 * при «уменьшить движение» (тогда сюжеты меняет только человек). */
export function Carousel({ lang }: { lang: Lang }) {
  const { t } = useTranslation();
  const list = scenes(lang);
  const [at, setAt] = useState(0);
  const [paused, setPaused] = useState(reducedMotion);
  const [hover, setHover] = useState(false);
  const running = !paused && !hover && list.length > 1;
  useEffect(() => {
    if (!running) return;
    const id = window.setTimeout(() => setAt((i) => (i + 1) % list.length), PERIOD);
    return () => window.clearTimeout(id);
  }, [running, list.length]);
  const scene = list[at % Math.max(1, list.length)];
  if (!scene) return null;
  const go = (step: number) => setAt((i) => (i + step + list.length) % list.length);
  return (
    <section
      className="car"
      aria-roledescription="carousel"
      aria-label={t("carousel.label")}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="car__frame">
        <img key={scene.url} className="car__img" src={scene.url} alt="" />
      </div>
      <p className="car__cap" aria-live={running ? "off" : "polite"}>
        {t(`carousel.${scene.name}`)}
      </p>
      <div className="car__ctl">
        <button type="button" className="car__btn" aria-label={t("carousel.prev")} onClick={() => go(-1)}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M10 3 5 8l5 5" />
          </svg>
        </button>
        <div className="car__dots">
          {list.map((s, i) => (
            <button
              key={s.name}
              type="button"
              className="car__dot"
              aria-label={t("carousel.go", { n: i + 1 })}
              aria-current={i === at ? "true" : undefined}
              onClick={() => setAt(i)}
            />
          ))}
        </div>
        <button type="button" className="car__btn" aria-label={t("carousel.next")} onClick={() => go(1)}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="m6 3 5 5-5 5" />
          </svg>
        </button>
        <button
          type="button"
          className="car__btn"
          aria-label={paused ? t("carousel.play") : t("carousel.pause")}
          onClick={() => setPaused((p) => !p)}
        >
          {paused ? (
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M5 3v10l8-5z" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M5 3v10M11 3v10" />
            </svg>
          )}
        </button>
      </div>
    </section>
  );
}
