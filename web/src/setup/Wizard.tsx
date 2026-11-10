import { Button } from "@heroui/react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  type AgentId,
  type Bridge,
  type Choices,
  type Defaults,
  type FolderCheck,
  type Lang,
  OCR_LANGS,
  type OcrLang,
  type Progress,
  STAGES,
  type Stage,
} from "./bridge";
import { Carousel } from "./Carousel";
import { left, size } from "./format";
import { setLang } from "./i18n";

export const STEPS = ["lang", "data", "docs", "features", "agents", "install", "done"] as const;
export type Step = (typeof STEPS)[number];

type InstallState = "idle" | "running" | "failed" | "done";

function ocrDefault(lang: Lang): OcrLang[] {
  return lang === "ru" ? ["rus", "eng"] : ["eng"];
}

function startStep(bridge: Bridge): Step {
  if (bridge.inApp) return "lang";
  const s = new URLSearchParams(window.location.search).get("step");
  return (STEPS as readonly string[]).includes(s ?? "") ? (s as Step) : "lang";
}

/** Мастер первого запуска (спецификация приложения для Windows, п. 4–5): язык → папка данных → документы →
 * возможности → подключение → установка → готово. Всё, что касается машины, — через мост (`bridge.ts`). */
export function Wizard({ bridge, defaults }: { bridge: Bridge; defaults: Defaults }) {
  const { t, i18n } = useTranslation();
  const [step, setStep] = useState<Step>(() => startStep(bridge));
  const [lang, setLangState] = useState<Lang>(defaults.lang);
  const [dataDir, setDataDir] = useState(defaults.dataDir);
  const [check, setCheck] = useState<FolderCheck | null>(null);
  const [docsDir, setDocsDir] = useState<string | null>(defaults.docsDir);
  const [ocrOn, setOcrOn] = useState(false);
  const [ocr, setOcr] = useState<OcrLang[]>(ocrDefault(defaults.lang));
  const [agents, setAgents] = useState<AgentId[]>(
    (Object.keys(defaults.agents) as AgentId[]).filter((a) => defaults.agents[a]),
  );
  const [progress, setProgress] = useState<Partial<Record<Stage, Progress>>>({});
  const [installState, setInstallState] = useState<InstallState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [shortcut, setShortcut] = useState(true);
  const [autostart, setAutostart] = useState(true);
  const [opening, setOpening] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    let live = true;
    setCheck(null);
    bridge.checkFolder(dataDir).then((c) => live && setCheck(c));
    return () => {
      live = false;
    };
  }, [bridge, dataDir]);

  // фокус — на заголовок нового шага: программа чтения экрана объявляет, где человек
  // biome-ignore lint/correctness/useExhaustiveDependencies: эффект — по смене шага, заголовок тот же ref
  useEffect(() => {
    heading.current?.focus();
  }, [step]);

  const chooseLang = (l: Lang) => {
    setLangState(l);
    setOcr(ocrDefault(l));
    void setLang(l);
  };

  const choices = useCallback(
    (): Choices => ({ lang, dataDir, docsDir, ocr: ocrOn ? ocr : [], agents }),
    [lang, dataDir, docsDir, ocrOn, ocr, agents],
  );

  const run = useCallback(async () => {
    setInstallState("running");
    setError(null);
    setProgress({});
    try {
      await bridge.install(choices(), (p) => setProgress((all) => ({ ...all, [p.stage]: p })));
      setInstallState("done");
      setStep("done");
    } catch (e) {
      setInstallState("failed");
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [bridge, choices]);

  // установка начинается при входе на шаг (и в снимках, открытых сразу на нём)
  const started = useRef(false);
  useEffect(() => {
    if (step === "install" && !started.current) {
      started.current = true;
      void run();
    }
  }, [step, run]);

  const index = STEPS.indexOf(step);
  const dataOk = !!check && check.ansiSafe && check.free >= check.need;
  const canNext =
    (step === "data" && dataOk) ||
    (step === "features" && (!ocrOn || ocr.length > 0)) ||
    !["data", "features"].includes(step);
  const next = () => setStep(STEPS[index + 1] ?? step);
  const back = () => setStep(STEPS[index - 1] ?? step);

  let body: ReactNode;
  if (step === "lang") {
    body = (
      <fieldset className="wz__choices">
        <legend className="sr-only">{t("lang.title")}</legend>
        {(["ru", "en"] as const).map((l) => (
          <label key={l} className="wz__card" data-checked={lang === l || undefined}>
            <input type="radio" name="lang" checked={lang === l} onChange={() => chooseLang(l)} />
            <span className="wz__card-title" lang={l}>
              {t(`lang.${l}`)}
            </span>
          </label>
        ))}
      </fieldset>
    );
  } else if (step === "data") {
    body = (
      <>
        <Folder
          path={dataDir}
          choose={t("data.choose")}
          onChoose={async () => {
            const p = await bridge.pickFolder(dataDir);
            if (p) setDataDir(p);
          }}
        />
        {check && (
          <p className="wz__meta" data-state={check.free < check.need ? "danger" : undefined}>
            {t(check.free < check.need ? "data.low" : "data.space", {
              free: size(check.free, t, i18n.language),
              need: size(check.need, t, i18n.language),
            })}
          </p>
        )}
        {check && !check.ansiSafe && (
          <div className="wz__note" data-state="danger" role="alert">
            <p>{t("data.ansi")}</p>
            {check.fallback && (
              <Button variant="outline" onPress={() => check.fallback && setDataDir(check.fallback)}>
                {t("data.useFallback", { path: check.fallback })}
              </Button>
            )}
          </div>
        )}
        {check?.notEmpty && (
          <p className="wz__note" data-state="warning">
            {t("data.notEmpty")}
          </p>
        )}
      </>
    );
  } else if (step === "docs") {
    body = (
      <>
        {docsDir ? (
          <Folder
            path={docsDir}
            choose={t("docs.choose")}
            onChoose={async () => {
              const p = await bridge.pickFolder(docsDir);
              if (p) setDocsDir(p);
            }}
          />
        ) : (
          <div className="wz__folder">
            <span className="wz__path muted">{t("docs.none")}</span>
            <Button
              variant="outline"
              onPress={async () => {
                const p = await bridge.pickFolder(defaults.docsDir);
                if (p) setDocsDir(p);
              }}
            >
              {t("docs.choose")}
            </Button>
          </div>
        )}
        {docsDir && (
          <Button variant="ghost" className="wz__link" onPress={() => setDocsDir(null)}>
            {t("docs.clear")}
          </Button>
        )}
      </>
    );
  } else if (step === "features") {
    body = (
      <ul className="wz__list">
        <li className="wz__row">
          <span className="wz__tick" aria-hidden="true">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="m3.5 8.5 3 3 6-7" />
            </svg>
          </span>
          <div>
            <p className="wz__row-title">{t("features.search")}</p>
            <p className="wz__meta">{t("features.searchNote")}</p>
          </div>
        </li>
        <li className="wz__row">
          <input
            id="ocr"
            type="checkbox"
            checked={ocrOn}
            onChange={(e) => setOcrOn(e.target.checked)}
            aria-describedby="ocr-note"
          />
          <div>
            <label htmlFor="ocr" className="wz__row-title">
              {t("features.ocr")}
            </label>
            <p id="ocr-note" className="wz__meta">
              {t("features.ocrNote")}
            </p>
            {ocrOn && (
              <fieldset className="wz__langs">
                <legend className="wz__meta">{t("features.ocrLangs")}</legend>
                {OCR_LANGS.map((code) => (
                  <label key={code} className="wz__pill" data-checked={ocr.includes(code) || undefined}>
                    <input
                      type="checkbox"
                      checked={ocr.includes(code)}
                      onChange={(e) =>
                        setOcr((list) =>
                          e.target.checked ? [...list, code] : list.filter((x) => x !== code),
                        )
                      }
                    />
                    {t(`features.langs.${code}`)}
                  </label>
                ))}
              </fieldset>
            )}
          </div>
        </li>
      </ul>
    );
  } else if (step === "agents") {
    body = (
      <ul className="wz__list">
        {(["claude", "codex"] as const).map((a) => (
          <li key={a} className="wz__row">
            <input
              id={`agent-${a}`}
              type="checkbox"
              checked={agents.includes(a)}
              onChange={(e) =>
                setAgents((list) => (e.target.checked ? [...list, a] : list.filter((x) => x !== a)))
              }
              aria-describedby={`agent-${a}-note`}
            />
            <div>
              <label htmlFor={`agent-${a}`} className="wz__row-title">
                {t(`agents.${a}`)}{" "}
                <span className="wz__found" data-found={defaults.agents[a] || undefined}>
                  {defaults.agents[a] ? t("agents.found") : t("agents.notFound")}
                </span>
              </label>
              <p id={`agent-${a}-note`} className="wz__meta">
                {t(`agents.${a}Note`)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    );
  } else if (step === "install") {
    body = (
      <div className="wz__install">
        <ol className="wz__stages" aria-label={t("install.title")}>
          {STAGES.map((s) => {
            const p = progress[s];
            const state = p?.state ?? "waiting";
            return (
              <li key={s} className="wz__stage" data-state={state}>
                <StageMark state={state} />
                <div>
                  <p className="wz__row-title">{t(`install.stages.${s}`)}</p>
                  <p className="wz__meta">
                    {p?.total && state === "running" ? (
                      <>
                        <progress
                          value={p.received ?? 0}
                          max={p.total}
                          aria-label={t(`install.stages.${s}`)}
                        />
                        <span className="wz__num">
                          {t("install.bytes", {
                            received: size(p.received ?? 0, t, i18n.language),
                            total: size(p.total, t, i18n.language),
                            rate: size(p.rate ?? 0, t, i18n.language),
                            left: left(p.rate ? (p.total - (p.received ?? 0)) / p.rate : 0, t),
                          })}
                        </span>
                      </>
                    ) : (
                      t(`install.state.${state}`)
                    )}
                  </p>
                  {state === "failed" && p?.message && <p className="wz__error">{p.message}</p>}
                </div>
              </li>
            );
          })}
        </ol>
        <Carousel lang={lang} />
      </div>
    );
  } else {
    body = (
      <>
        <p className="wz__lead">{t("done.lead")}</p>
        <ol className="wz__list wz__tips">
          {(["find", "write", "check"] as const).map((k, i) => {
            const [verb, rest] = t(`done.${k}`).split(" — ");
            return (
              <li key={k} className="wz__row">
                <span className="wz__num-dot" aria-hidden="true">
                  {i + 1}
                </span>
                <p className="wz__tip">
                  <span className="wz__row-title">{verb}</span>
                  {rest && <span className="wz__meta"> — {rest}</span>}
                </p>
              </li>
            );
          })}
        </ol>
        <div className="wz__checks">
          <label className="wz__check">
            <input type="checkbox" checked={shortcut} onChange={(e) => setShortcut(e.target.checked)} />
            {t("done.shortcut")}
          </label>
          <label className="wz__check">
            <input type="checkbox" checked={autostart} onChange={(e) => setAutostart(e.target.checked)} />
            {t("done.autostart")}
          </label>
        </div>
      </>
    );
  }

  const lead: Partial<Record<Step, string>> = {
    lang: t("lang.lead"),
    data: t("data.lead"),
    docs: t("docs.lead"),
    features: t("features.lead"),
    agents: t("agents.lead"),
    install: t("install.lead"),
  };
  const title: Record<Step, string> = {
    lang: t("lang.title"),
    data: t("data.title"),
    docs: t("docs.title"),
    features: t("features.title"),
    agents: t("agents.title"),
    install: installState === "failed" ? t("install.failed") : t("install.title"),
    done: t("done.title"),
  };

  return (
    <div className="wz" data-step={step}>
      {bridge.inApp && <TitleBar bridge={bridge} />}
      <div className="wz__body">
        <nav className="wz__rail" aria-label={t("steps.label")}>
          <div className="wz__brand">
            <img src="./favicon.svg" alt="" width={28} height={28} />
            <span>amemo</span>
            <span className="wz__ver">{defaults.version}</span>
          </div>
          <ol>
            {STEPS.map((s, i) => (
              <li
                key={s}
                aria-current={s === step ? "step" : undefined}
                data-state={i < index ? "done" : s === step ? "current" : "next"}
              >
                <span className="wz__num-dot" aria-hidden="true">
                  {i < index ? (
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="m3.5 8.5 3 3 6-7" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </span>
                {t(`steps.${s}`)}
              </li>
            ))}
          </ol>
        </nav>
        <main className="wz__main">
          <div className="wz__content" key={step}>
            <h1 ref={heading} tabIndex={-1}>
              {title[step]}
            </h1>
            {lead[step] && <p className="wz__lead">{lead[step]}</p>}
            {body}
            {step === "install" && installState === "failed" && error && (
              <p className="wz__error" role="alert">
                {error}
              </p>
            )}
          </div>
          <footer className="wz__foot">
            {index > 0 && step !== "install" && step !== "done" && (
              <Button variant="ghost" onPress={back}>
                {t("nav.back")}
              </Button>
            )}
            <span className="wz__spacer" />
            {step === "docs" && !docsDir && (
              <Button variant="ghost" onPress={next}>
                {t("nav.skip")}
              </Button>
            )}
            {step === "install" && installState === "failed" && (
              <Button className="wz__primary" onPress={() => void run()}>
                {t("install.retry")}
              </Button>
            )}
            {step === "done" && (
              <Button
                className="wz__primary"
                isPending={opening}
                onPress={async () => {
                  setOpening(true);
                  try {
                    await bridge.finish({ desktopShortcut: shortcut, autostart });
                  } finally {
                    setOpening(false);
                  }
                }}
              >
                {t("done.open")}
              </Button>
            )}
            {step !== "install" && step !== "done" && (
              <Button className="wz__primary" isDisabled={!canNext} onPress={next}>
                {step === "agents" ? t("nav.install") : t("nav.next")}
              </Button>
            )}
          </footer>
        </main>
      </div>
    </div>
  );
}

function Folder({ path, choose, onChoose }: { path: string; choose: string; onChoose: () => void }) {
  return (
    <div className="wz__folder">
      <span className="wz__path" title={path}>
        {path}
      </span>
      <Button variant="outline" onPress={onChoose}>
        {choose}
      </Button>
    </div>
  );
}

function StageMark({ state }: { state: Progress["state"] }) {
  return (
    <span className="wz__mark" data-state={state} aria-hidden="true">
      {state === "done" && (
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="m3.5 8.5 3 3 6-7" />
        </svg>
      )}
      {state === "failed" && (
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M8 4v5M8 11.5v.5" />
        </svg>
      )}
      {state === "skipped" && (
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 8h8" />
        </svg>
      )}
    </span>
  );
}

function TitleBar({ bridge }: { bridge: Bridge }) {
  const { t } = useTranslation();
  return (
    <header className="wz__bar" data-tauri-drag-region>
      <span className="wz__bar-title" data-tauri-drag-region>
        {t("title")}
      </span>
      <div className="wz__bar-buttons">
        <button type="button" aria-label={t("window.minimize")} onClick={() => bridge.window.minimize()}>
          <svg viewBox="0 0 10 10" aria-hidden="true">
            <path d="M1 5h8" />
          </svg>
        </button>
        <button
          type="button"
          aria-label={t("window.maximize")}
          onClick={() => bridge.window.toggleMaximize()}
        >
          <svg viewBox="0 0 10 10" aria-hidden="true">
            <rect x="1.5" y="1.5" width="7" height="7" />
          </svg>
        </button>
        <button
          type="button"
          className="wz__bar-close"
          aria-label={t("window.close")}
          onClick={() => bridge.window.close()}
        >
          <svg viewBox="0 0 10 10" aria-hidden="true">
            <path d="M2 2l6 6M8 2l-6 6" />
          </svg>
        </button>
      </div>
    </header>
  );
}
