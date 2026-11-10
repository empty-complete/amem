import { HttpResponse, http } from "msw";
import { db, newId } from "./db";
import session from "./fixtures/session.json";
import { problem } from "./handlers-b";

type Selection = {
  tags?: string[];
  kinds?: string[];
  entity_classes?: string[];
  statuses?: string[];
  since?: string | null;
  project?: string | null;
};
const exports = new Map<string, { anthology: boolean; title: string; atoms: number; entities: number }>();
const uploads = new Map<string, { name: string; damaged: boolean }>();

/** Что попадёт в подборку — по тем же условиям, что у службы (упрощённо: записи хранилища моков). */
function pick(s: Selection, anthology: boolean) {
  const statuses = anthology
    ? ["verified"]
    : s.statuses?.length
      ? s.statuses
      : ["draft", "needs_review", "auto_verified", "verified", "deprecated", "superseded"];
  return db.records.filter(
    (r) =>
      statuses.includes(r.status) &&
      (!s.tags?.length || (r.tags ?? []).some((t) => s.tags?.includes(t))) &&
      (!s.kinds?.length || r.target !== "atom" || s.kinds.includes(r.kind_or_class)) &&
      (!s.entity_classes?.length || r.target !== "entity" || s.entity_classes.includes(r.kind_or_class)) &&
      (!s.since || r.recorded_at >= s.since),
  );
}

const report = (title: string, rows: { label: string; kind: string }[]) =>
  `<!doctype html><html lang=ru><meta charset=utf-8><title>${title}</title><h1>${title}</h1><p>${rows.length} записей · проверенное и предпочтительное</p>` +
  rows.map((r) => `<article><h3>${r.label}</h3><p>${r.kind}</p></article>`).join("") +
  "</html>";

/** Подборки (часть F): экспорт и антология, скачивание и отчёт, inspect, пробный и настоящий импорт. */
export const handlersF = (zip: () => Promise<ArrayBuffer>) => [
  http.post("/api/v1/bundles/export", async ({ request }) => {
    const b = (await request.json()) as {
      selection: Selection;
      with_files?: boolean;
      with_packs?: boolean;
      anthology?: boolean;
      title?: string;
    };
    if (b.anthology && b.with_packs)
      return problem(
        400,
        "Неверный запрос",
        "with_packs: антология пакеты не копирует — у получателя нужны те же пакеты",
      );
    const rows = pick(b.selection ?? {}, !!b.anthology);
    const atoms = rows.filter((r) => r.target === "atom").length;
    if (b.anthology && !atoms) return problem(422, "Антология пуста", "В отборе нет проверенных записей");
    if (!rows.length) return problem(422, "Подборка пуста", "Под условия отбора не подошла ни одна запись");
    const id = newId("task");
    exports.set(id, {
      anthology: !!b.anthology,
      title: b.title || "Антология",
      atoms,
      entities: rows.length - atoms,
    });
    return HttpResponse.json({
      id,
      summary: {
        counts: {
          atoms,
          entities: rows.length - atoms,
          links: Math.round(atoms * 0.7),
          objects: b.with_files ? 2 : 0,
          sources: atoms,
        },
        with_files: !!b.with_files,
        with_packs: !!b.with_packs,
        packs: [
          "core",
          "meteo",
          ...(b.with_packs && db.templates.some((t) => t.pack === "mine") ? ["mine"] : []),
        ],
      },
      download: `/api/v1/bundles/${id}/download`,
      report: b.anthology ? `/api/v1/bundles/${id}/report` : null,
    });
  }),
  http.get("/api/v1/bundles/:id/download", async ({ params }) => {
    if (!exports.has(String(params.id))) return problem(404, "Подборки нет");
    return HttpResponse.arrayBuffer(await zip(), {
      headers: {
        "content-type": "application/zip",
        "content-disposition": `attachment; filename="amemo-${params.id}.zip"`,
      },
    });
  }),
  http.get("/api/v1/bundles/:id/report", ({ params }) => {
    const e = exports.get(String(params.id));
    if (!e?.anthology) return problem(404, "Отчёт есть только у антологии");
    const rows = db.records
      .filter((r) => r.status === "verified" && r.target === "atom")
      .map((r) => ({ label: r.label, kind: r.kind_or_class }));
    return new HttpResponse(report(e.title, rows), {
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }),
  http.post("/api/v1/bundles/inspect", async ({ request }) => {
    const form = await request.formData();
    const file = form.get("file") as File | null;
    if (!file) return problem(422, "Нужен файл подборки");
    if (!/\.zip$/i.test(file.name))
      return problem(422, "Это не подборка", "Нужен zip, собранный amemo (amem.bundle/1)");
    const damaged = /битый|broken/i.test(file.name);
    const upload_id = newId("task");
    uploads.set(upload_id, { name: file.name, damaged });
    return HttpResponse.json({
      upload_id,
      report: {
        format: "amem.bundle/1",
        created_at: "2026-11-08T09:00:00Z",
        base_id: "0193b000-0000-7000-8000-0000000000ff",
        agent: "person:boris",
        selection: { tags: ["зима"], statuses: ["verified"] },
        packs: [{ name: "meteo", version: "1.0.0" }],
        counts: { atoms: 5, entities: 2, links: 3, objects: 1, sources: 4 },
        ok: !damaged,
        damaged: damaged ? ["atoms.jsonl"] : [],
        unexpected: [],
      },
    });
  }),
  http.post("/api/v1/bundles/import", async ({ request }) => {
    const b = (await request.json()) as { upload_id: string; trust?: "keep" | "review"; dry_run?: boolean };
    const u = uploads.get(b.upload_id);
    if (!u) return problem(404, "Загрузки нет — выберите файл заново");
    if (u.damaged) return problem(422, "Подборка повреждена", "Часть atoms.jsonl не сходится с манифестом");
    const review = b.trust === "review";
    const res = {
      complete: true,
      counts: { new: 4, same: 2, changed: 1, entities_new: 1 },
      queued: review ? [{ reason: "imported", count: 5 }] : [{ reason: "imported", count: 1 }],
      warnings: ["Пакет meteo 1.0.0 — тот же, что в базе"],
      collisions: [],
      report: { dry_run: b.dry_run !== false },
      changeset_id: b.dry_run !== false ? null : newId("task"),
    };
    if (b.dry_run === false) {
      const now = new Date().toISOString();
      for (let i = 0; i < 4; i++) {
        const ref = newId("atm");
        db.records.unshift({
          ref,
          target: "atom",
          label: `Из подборки: наблюдение ${i + 1}`,
          kind_or_class: "fact",
          status: review ? "needs_review" : "verified",
          folder: "Ресурсы",
          about: [],
          tags: ["зима"],
          recorded_at: now,
          agent: session.agent,
        } as never);
      }
      db.events.push({
        type: "revision",
        id: newId("task"),
        at: now,
        ref: db.records[0]?.ref,
        label: "Импорт подборки",
        agent: session.agent,
        revision: 1,
      } as never);
      db.save();
    }
    return HttpResponse.json(res);
  }),
];
