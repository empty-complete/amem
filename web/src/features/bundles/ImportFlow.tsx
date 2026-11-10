import { Button } from "@heroui/react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../api/auth";
import { api } from "../../api/client";
import { type ApiError, problemFromResponse } from "../../api/errors";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";

type Imported = components["schemas"]["Imported"];
type Inspect = {
  upload_id: string;
  report: {
    base_id?: string;
    agent?: string;
    created_at?: string;
    counts?: Record<string, number>;
    packs?: { name: string; version: string }[];
    ok?: boolean;
    damaged?: string[];
  };
};

/** Импорт (разд. 5.10): файл → проверка (inspect) → пробный импорт с отчётом → «Влить в базу». */
export function ImportFlow() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const [ins, setIns] = useState<Inspect | null>(null);
  const [trust, setTrust] = useState<"keep" | "review">("keep");
  const [dry, setDry] = useState<Imported | null>(null);
  const [done, setDone] = useState<Imported | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => {
    const a = e as ApiError;
    setErr(a.detail ? `${a.title}: ${a.detail}` : (a.title ?? String(e)));
  };
  // новый файл — новая проверка; поле файла очищаем, только когда человек выбирает «Другой файл»
  const reset = (clearFile = true) => {
    setIns(null);
    setDry(null);
    setDone(null);
    setErr(null);
    if (clearFile && file.current) file.current.value = "";
  };

  const inspect = async (f: File) => {
    reset(false);
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await apiFetch(`${location.origin}/api/v1/bundles/inspect`, { method: "POST", body: fd });
      if (!res.ok) throw await problemFromResponse(res);
      setIns((await res.json()) as Inspect);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const run = async (dryRun: boolean) => {
    if (!ins) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.POST("/bundles/import", {
        body: { upload_id: ins.upload_id, trust, dry_run: dryRun },
      });
      if (dryRun) setDry(r.data ?? null);
      else {
        setDone(r.data ?? null);
        for (const k of ["records", "folders", "review-items", "review-stats", "base", "changes", "graph"])
          qc.invalidateQueries({ queryKey: [k] });
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const c = (d: Imported | null) => (d?.counts ?? {}) as Record<string, number>;
  const queuedN = (d: Imported | null) =>
    (d?.queued ?? []).reduce((n, x) => n + Number((x as { count?: number }).count ?? 1), 0);
  const rep = ins?.report;

  return (
    <div className="bimport">
      <ol className="steps" aria-label={t("bundles.tab_import")}>
        {(["step1", "step2", "step3", "step4"] as const).map((s, i) => (
          <li
            key={s}
            aria-current={(done ? 3 : dry ? 3 : ins ? 1 : 0) === i ? "step" : undefined}
            data-done={(done ? 4 : dry ? 3 : ins ? 2 : 0) > i || undefined}
          >
            {t(`bundles.${s}`)}
          </li>
        ))}
      </ol>
      <label className="fl">
        {t("bundles.pick_file")}
        <input
          ref={file}
          className="fld"
          type="file"
          accept=".zip,application/zip"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void inspect(f);
          }}
        />
      </label>
      {err && (
        <p className="fielderr" role="alert">
          {err}
        </p>
      )}
      {rep && (
        <section className="bcard" aria-label={t("bundles.in_bundle")}>
          <h2>{t("bundles.in_bundle")}</h2>
          <p className="muted">
            {t("bundles.from", {
              base: rep.base_id?.slice(-6) ?? "",
              agent: (rep.agent ?? "").replace(/^person:/, ""),
              when: rep.created_at ? new Date(rep.created_at).toLocaleString(i18n.language) : "",
            })}
          </p>
          <p>
            {t("bundles.counts", {
              atoms: rep.counts?.atoms ?? 0,
              entities: rep.counts?.entities ?? 0,
              links: rep.counts?.links ?? 0,
              objects: rep.counts?.objects ?? 0,
            })}
          </p>
          <p className="status" data-tone={rep.ok ? "ok" : "bad"}>
            <Icon name={rep.ok ? "check" : "cross"} />
            {rep.ok ? t("bundles.ok") : t("bundles.damaged", { list: (rep.damaged ?? []).join(", ") })}
          </p>
          {!done && (
            <fieldset className="fl">
              <legend>{t("bundles.trust")}</legend>
              {(["keep", "review"] as const).map((v) => (
                <label key={v} className="chk">
                  <input type="radio" name="trust" checked={trust === v} onChange={() => setTrust(v)} />
                  {t(`bundles.trust_${v}`)}
                </label>
              ))}
            </fieldset>
          )}
          {!dry && !done && (
            <div className="editor__foot">
              <Button className="pillbtn" isDisabled={busy || !rep.ok} onPress={() => run(true)}>
                {t("bundles.dry")}
              </Button>
              <span className="muted">{t("bundles.dry_hint")}</span>
            </div>
          )}
        </section>
      )}
      {dry && !done && (
        <section className="bcard" aria-label={t("bundles.dry")}>
          <h2>{t("bundles.dry")}</h2>
          <p>
            {t("bundles.dry_result", {
              new: c(dry).new ?? 0,
              same: c(dry).same ?? 0,
              changed: c(dry).changed ?? 0,
            })}
          </p>
          <p>{t("bundles.queued", { n: queuedN(dry) })}</p>
          {!!dry.warnings?.length && (
            <>
              <h3>{t("bundles.warnings")}</h3>
              <ul className="issues">
                {dry.warnings.map((w) => (
                  <li key={String(w)}>
                    <span className="status" data-tone="wait">
                      <Icon name="warn" />
                    </span>
                    {typeof w === "string" ? w : JSON.stringify(w)}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted">
            {dry.collisions?.length
              ? `${t("bundles.collisions")}: ${dry.collisions.length}`
              : t("bundles.no_collisions")}
          </p>
          <div className="editor__foot">
            <Button className="pillbtn" isDisabled={busy} onPress={() => run(false)}>
              {t("bundles.import")}
            </Button>
            <Button variant="ghost" onPress={() => reset()}>
              {t("bundles.other_file")}
            </Button>
          </div>
        </section>
      )}
      {done && (
        <section className="bcard bdone" aria-label={t("bundles.step4")}>
          <h2>
            <Icon name="check" /> {t("bundles.imported", { new: c(done).new ?? 0 })}
          </h2>
          <p>{t("bundles.queued", { n: queuedN(done) })}</p>
          <div className="editor__foot">
            <Link className="pillbtn" to="/review" search={{ reason: "imported" } as never}>
              {t("bundles.to_review")}
            </Link>
            <Button variant="ghost" onPress={() => reset()}>
              {t("bundles.other_file")}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
