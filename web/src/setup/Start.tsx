import { Button } from "@heroui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { type Bridge, type Defaults, PAUSED } from "./bridge";
import { TitleBar } from "./Wizard";

type State = "starting" | "failed" | "paused";

/** Экран запуска (мастер уже пройден): пока приложение поднимает PostgreSQL и службу, затем окно само переходит в
 * веб-интерфейс amemo. Ошибка — текст и «Повторить»; пауза из значка в области уведомлений — «Продолжить». */
export function Start({ bridge, defaults }: { bridge: Bridge; defaults: Defaults }) {
  const { t } = useTranslation();
  const [state, setState] = useState<State>("starting");
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  const run = useCallback(
    async (resume: boolean) => {
      setState("starting");
      setError(null);
      try {
        await bridge.start(resume);
      } catch (e) {
        const text = e instanceof Error ? e.message : String(e);
        if (text === PAUSED) {
          setState("paused");
        } else {
          setState("failed");
          setError(text);
        }
      }
    },
    [bridge],
  );

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void run(false);
  }, [run]);

  // фокус — на заголовок нового состояния: программа чтения экрана объявляет ошибку или паузу
  useEffect(() => {
    if (state !== "starting") heading.current?.focus();
  }, [state]);

  return (
    <div className="wz st" data-state={state}>
      {bridge.inApp && <TitleBar bridge={bridge} title="amemo" />}
      <main className="st__main" aria-busy={state === "starting"}>
        <div className="st__card">
          <div className="wz__brand st__brand">
            <img src="./favicon.svg" alt="" width={36} height={36} />
            <span>amemo</span>
            <span className="wz__ver">{defaults.version}</span>
          </div>
          <h1 ref={heading} tabIndex={-1}>
            {t(`start.${state}.title`)}
          </h1>
          <p className="wz__lead">{t(`start.${state}.lead`)}</p>
          {state === "starting" && (
            <span className="wz__mark st__spin" data-state="running" aria-hidden="true" />
          )}
          {state === "failed" && error && (
            <p className="wz__error st__error" role="alert">
              {error}
            </p>
          )}
          {state !== "starting" && (
            <div className="st__actions">
              <Button className="wz__primary" onPress={() => void run(state === "paused")}>
                {state === "paused" ? t("start.resume") : t("start.retry")}
              </Button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
