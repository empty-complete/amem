import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Lang } from "./bridge";

/** Сюжеты README (docs/assets/readme/<язык>/demo-*.gif): новый сюжет там же попадает и в README, и сюда — если его
 * имя есть в SCENES и подпись в carousel.<имя>. В сборке приложения — их пережатые WebP (tools/carousel.py,
 * media/<язык>/demo-*.webp, `__CAROUSEL__` — web/vite.setup.config.ts): ветка с GIF отбрасывается при сборке, и в
 * установщик GIF не попадают. */
const SCENES = ["sky", "write", "source", "review", "card"] as const;
type Loader = () => Promise<string>;
const FILES: Record<string, Loader> =
  __CAROUSEL__ === "webp"
    ? (import.meta.glob("./media/*/demo-*.webp", { query: "?url", import: "default" }) as Record<
        string,
        Loader
      >)
    : (import.meta.glob("../../../docs/assets/readme/*/demo-*.gif", {
        query: "?url",
        import: "default",
      }) as Record<string, Loader>);
const PERIOD = 7000; // мс на сюжет

function loader(lang: Lang, name: string): Loader | undefined {
  return __CAROUSEL__ === "webp"
    ? FILES[`./media/${lang}/demo-${name}.webp`]
    : FILES[`../../../docs/assets/readme/${lang}/demo-${name}.gif`];
}

/** Адреса анимаций языка — по мере загрузки модулей. */
function useScenes(lang: Lang) {
  const [list, setList] = useState<{ name: string; url: string }[]>([]);
  useEffect(() => {
    let live = true;
    const found = SCENES.flatMap((name) => {
      const load = loader(lang, name);
      return load ? [load().then((url) => ({ name, url }))] : [];
    });
    void Promise.all(found).then((all) => live && setList(all));
    return () => {
      live = false;
    };
  }, [lang]);
  return list;
}

function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** «Что умеет amemo» на экране установки: анимация и подпись, смена каждые 7 с; пауза — кнопкой, наведением и
 * при «уменьшить движение» (тогда сюжеты меняет только человек). */
export function Carousel({ lang }: { lang: Lang }) {
  const { t } = useTranslation();
  const list = useScenes(lang);
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
