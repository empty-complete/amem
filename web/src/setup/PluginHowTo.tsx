import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

/** Куда нажимать в приложении Claude, чтобы загрузить плагин amemo: схема окна Claude (не снимок — дизайн Claude
 * меняется, а путь Customize → Plugins → Add → Upload plugin остаётся) по шагам, подсвечен элемент шага. Подписи
 * элементов — как в интерфейсе Claude (английские), пояснения — на языке мастера. Смена шага — каждые 2,2 с; при
 * «уменьшить движение» шаги переключает человек. */

const FRAMES = 5;
const PERIOD = 2200;

function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function PluginHowTo({ file }: { file: string }) {
  const { t } = useTranslation();
  const [at, setAt] = useState(0);
  const [auto] = useState(() => !reducedMotion());
  useEffect(() => {
    if (!auto) return;
    const id = window.setInterval(() => setAt((i) => (i + 1) % FRAMES), PERIOD);
    return () => window.clearInterval(id);
  }, [auto]);
  const hot = (frame: number) => (at === frame ? "" : undefined);

  return (
    <figure className="how" aria-label={t("plugin.howto.label")}>
      <div className="how__win" aria-hidden="true">
        <div className="how__bar">
          <span className="how__dots">
            <i />
            <i />
            <i />
          </span>
          Claude
        </div>
        <div className="how__body">
          <nav className="how__side">
            <span>New chat</span>
            <span>Projects</span>
            <span data-hot={hot(0)} data-on={at >= 1 || undefined}>
              Customize
            </span>
          </nav>
          <div className="how__main">
            {at === 0 && <div className="how__empty" />}
            {at >= 1 && (
              <>
                <div className="how__tabs">
                  <span>Skills</span>
                  <span>Connectors</span>
                  <span data-hot={hot(1)} data-on={at >= 2 || undefined}>
                    Plugins
                  </span>
                </div>
                {at >= 2 && (
                  <div className="how__plugins">
                    <span className="how__add" data-hot={hot(2)}>
                      + Add
                    </span>
                    {at >= 3 && (
                      <div className="how__menu">
                        <span>Add marketplace</span>
                        <span data-hot={hot(3)}>Upload plugin</span>
                      </div>
                    )}
                    <div className="how__row" />
                    <div className="how__row" />
                  </div>
                )}
              </>
            )}
            {at === 4 && (
              <div className="how__dialog">
                <div className="how__dialog-title">Open</div>
                <div className="how__file">Downloads</div>
                <div className="how__file how__file--sel">{file}</div>
                <span className="how__open" data-hot="">
                  Open
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
      <figcaption className="how__cap">
        <span className="wz__num-dot" aria-hidden="true">
          {at + 1}
        </span>
        <span aria-live={auto ? "off" : "polite"}>{t(`plugin.howto.${at}`, { file })}</span>
      </figcaption>
      <div className="how__steps">
        {Array.from({ length: FRAMES }, (_, i) => (
          <button
            // biome-ignore lint/suspicious/noArrayIndexKey: шаги — постоянный список
            key={i}
            type="button"
            className="car__dot"
            aria-label={t("plugin.howto.go", { n: i + 1 })}
            aria-current={i === at ? "true" : undefined}
            onClick={() => setAt(i)}
          />
        ))}
      </div>
    </figure>
  );
}
