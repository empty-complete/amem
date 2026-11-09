import { HttpResponse, http } from "msw";
import { normalize } from "../features/source/quote";
import { db, newId } from "./db";
import session from "./fixtures/session.json";
import textManual from "./fixtures/text-manual.json";
import vocabKind from "./fixtures/vocab-kind.json";
import vocabProperty from "./fixtures/vocab-property.json";
import { problem } from "./handlers-b";

type L = { ru: string; en?: string };
type Sel = { type: string; value?: unknown; label?: string };
type Src = { object?: string; object_version?: number; selectors?: Sel[]; quote?: string | null };
type Value = { property?: string; amount?: number; value_text?: string; unit?: string; value_state?: string };
type Payload = {
  ref?: string;
  kind?: string;
  entity_class?: string;
  label?: L;
  summary_plain?: L;
  body?: L;
  about?: string[];
  tags?: string[];
  basis?: string;
  content?: { values?: Value[] };
  sources?: Src[];
  scope?: { folder?: string };
};
type Proposal = { target: "atom" | "entity"; payload: Payload; record_id?: string | null };
type LinkP = { src: string; dst: string; rel: string };
type Issue = { code: string; severity: "violation"; message: string; path: string; ref: string };

/** Счётчик запросов записи — e2e проверяет, что «Отменить» ничего не отправил. */
export const writeLog: string[] = [];

const MANUAL = "0193b7c2-5e1a-7d40-9f2e-0000000000a1";
const manualText = normalize(textManual.pages.join("\n"));
const labelOf = (ref: string) =>
  db.records.find((r) => r.ref === ref)?.label ??
  (db.views[ref]?.payload as Payload | undefined)?.label?.ru ??
  ref;
const familyOf = (kind: string, target: string) =>
  target === "entity"
    ? "object"
    : ["fact", "parameter", "term", "requirement", "sensor_reading"].includes(kind)
      ? "source"
      : "work";

function check(proposals: Proposal[]): Issue[] {
  const out: Issue[] = [];
  proposals.forEach((p, i) => {
    const ref = `proposals[${i}]`;
    if (!p.payload.label?.ru?.trim())
      out.push({
        code: "required",
        severity: "violation",
        message: "Нужен заголовок",
        path: "label.ru",
        ref,
      });
    // папка — не часть ревизии: служба отклоняет scope.folder по схеме v1, перенос — POST /records/{ref}/folder
    if ((p.payload.scope as Record<string, unknown> | undefined)?.folder !== undefined)
      out.push({
        code: "schema",
        severity: "violation",
        message: "Не по схеме: Extra inputs are not permitted",
        path: "scope.folder",
        ref,
      });
    // как шаблон ядра has_label: у каждого атома есть пояснение «простыми словами»
    if (p.target === "atom" && !p.payload.summary_plain?.ru?.trim())
      out.push({
        code: "required",
        severity: "violation",
        message: "Нет пояснения «простыми словами».",
        path: "summary_plain",
        ref,
      });
    const tpl = db.templates.find((t) => t.code === (p.payload.kind ?? p.payload.entity_class));
    for (const f of tpl?.form ?? []) {
      if (!f.required) continue;
      const v = f.path.startsWith("content.values")
        ? p.payload.content?.values?.[0]
        : (p.payload as Record<string, unknown>)[f.path];
      const empty =
        v == null ||
        (Array.isArray(v) && !v.length) ||
        (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
      if (empty)
        out.push({
          code: "required",
          severity: "violation",
          message: `Нужно: ${f.label.ru.toLowerCase()}`,
          path: f.path,
          ref,
        });
    }
    (p.payload.sources ?? []).forEach((s, j) => {
      if (s.object === MANUAL && s.quote && !manualText.includes(normalize(s.quote))) {
        const words = normalize(s.quote).split(" ").slice(0, 2).join(" ");
        const at = manualText.indexOf(words);
        const near = at >= 0 ? textManual.pages.join(" ").slice(at, at + 80) : "";
        out.push({
          code: "quote_not_found",
          severity: "violation",
          message: near ? `Цитаты на странице нет. Ближайшее в файле: «${near}»` : "Цитаты в файле нет",
          path: `sources[${j}].quote`,
          ref,
        });
      }
    });
  });
  return out;
}

function sourceViews(p: Payload) {
  return (p.sources ?? []).map((s) => {
    const o = s.object ? db.objects[s.object] : undefined;
    return {
      object: s.object ?? "",
      object_name: o?.original_name,
      object_kind: o?.kind ?? "file",
      media_type: o?.media_type ?? undefined,
      object_version: s.object_version ?? 1,
      selectors: s.selectors ?? [],
      quote: s.quote ?? undefined,
      role: "primary",
      verdict: s.quote ? "ok" : "by_locator",
    };
  });
}

/** Карточка объекта образца отвечает на записанное: поле стало известно, вопрос открыт. */
function touchCard(p: Payload, ref: string) {
  const card = db.card;
  if (!p.about?.includes(card.entity.ref)) return;
  const v = p.content?.values?.[0];
  const f = v?.property ? card.fields.find((x) => x.property === v.property) : undefined;
  if (!f || !v) return;
  const field = f as Record<string, unknown>;
  if (v.value_state === "unknown") {
    field.state = "asked";
    field.ask = p.label?.ru ?? "";
  } else {
    field.state = "known";
    field.value = { amount: v.amount, value_text: v.value_text, unit: v.unit };
    field.basis = p.basis ?? "author";
    field.by = "person";
  }
  field.atoms = [...((field.atoms as string[]) ?? []), ref];
}

function write(proposals: Proposal[], links: LinkP[]) {
  const now = new Date().toISOString();
  const temp = new Map<string, string>();
  const records = proposals.map((p) => {
    const kind = p.payload.kind ?? p.payload.entity_class ?? "note";
    const label = p.payload.label?.ru ?? "";
    if (p.record_id) {
      const v = db.views[p.record_id];
      if (!v) throw new Error(`нет записи ${p.record_id}`);
      v.payload = p.payload as never;
      v.revision += 1;
      v.recorded_at = now;
      v.status = "verified"; // запись человека по 3c — сразу проверена
      v.sources = sourceViews(p.payload) as never;
      const s = db.records.find((r) => r.ref === p.record_id);
      if (s) Object.assign(s, { label, recorded_at: now, status: "verified" });
      db.events.push({
        type: "revision",
        id: newId("task"),
        at: now,
        ref: p.record_id,
        label,
        agent: session.agent,
        revision: v.revision,
      } as never);
      return {
        label,
        target: p.target,
        record_id: p.record_id,
        revision_id: newId("task"),
        created: false,
        status: "verified",
        review_state: "none",
      };
    }
    const ref = newId(p.target === "entity" ? "ent" : "atm");
    if (p.payload.ref) temp.set(String(p.payload.ref), ref);
    const about = (p.payload.about ?? []).map((r) => ({ ref: r, label: labelOf(r) }));
    const folder = p.payload.scope?.folder ?? null;
    db.views[ref] = {
      ref,
      target: p.target,
      revision: 1,
      payload: p.payload,
      status: "verified",
      review_state: "none",
      recorded_at: now,
      agent: session.agent,
      folder,
      about,
      ancestors: [],
      sources: sourceViews(p.payload),
      open_items: [],
      usefulness: null,
    } as never;
    db.records.unshift({
      ref,
      target: p.target,
      label,
      kind_or_class: kind,
      status: "verified",
      folder,
      about,
      tags: p.payload.tags ?? [],
      recorded_at: now,
      agent: session.agent,
    } as never);
    db.graph.nodes.push({
      ref,
      label,
      kind_or_class: kind,
      family: familyOf(kind, p.target),
      status: "verified",
      pending: false,
      degree: about.length,
    } as never);
    for (const a of about)
      db.graph.edges.push({ src: ref, dst: a.ref, rel: "about", confidence: null } as never);
    db.events.push({
      type: "revision",
      id: newId("task"),
      at: now,
      ref,
      label,
      agent: session.agent,
      revision: 1,
    } as never);
    touchCard(p.payload, ref);
    return {
      label,
      target: p.target,
      record_id: ref,
      revision_id: newId("task"),
      created: true,
      status: "verified",
      review_state: "none",
    };
  });
  for (const l of links) {
    const src = temp.get(l.src) ?? l.src;
    const dst = temp.get(l.dst) ?? l.dst;
    db.graph.edges.push({ src, dst, rel: l.rel, confidence: null } as never);
  }
  return records;
}

/** Запись человека (часть D): /submit с правилами уровней 1–2 образца, шаблоны, объекты, задачи, папки. */
export const handlersD = [
  // поиск для выбора объекта или записи в правке: по подписи и кодам среди записей хранилища моков
  http.get("/api/v1/search", ({ request }) => {
    const u = new URL(request.url);
    const target = u.searchParams.get("target");
    if (!target) return; // обычный поиск — образец части A
    const raw = (u.searchParams.get("q") ?? "").toLowerCase();
    const q = raw === "*" ? "" : raw;
    const items = db.records
      .filter((r) => r.target === target && (!q || r.label.toLowerCase().includes(q)))
      .slice(0, Number(u.searchParams.get("limit") ?? 8))
      .map((r, i) => ({
        ref: r.ref,
        revision: 1,
        label: r.label,
        snippet: r.label,
        status: r.status,
        review_state: "none",
        kind: r.target === "atom" ? r.kind_or_class : undefined,
        entity_class: r.target === "entity" ? r.kind_or_class : undefined,
        about: r.about ?? [],
        score: 1 - i / 100,
        matches: [{ channel: "label", rank: i + 1 }],
      }));
    return HttpResponse.json({
      recipe: "exact_fact",
      semantic: "used",
      candidate_count: items.length,
      items,
      retrieval_id: null,
    });
  }),
  http.post("/api/v1/submit", async ({ request }) => {
    const body = (await request.json()) as { proposals: Proposal[]; links?: LinkP[] };
    writeLog.push("submit");
    db.submits += 1;
    // record_id — UUID без приставки: находим запись по atm:/ent:
    for (const p of body.proposals)
      if (p.record_id && !p.record_id.includes(":"))
        p.record_id = `${p.target === "entity" ? "ent" : "atm"}:${p.record_id}`;
    for (const p of body.proposals) {
      if (p.record_id && db.views[p.record_id]?.agent !== session.agent)
        return problem(403, "Чужие записи не правятся", "Поставьте её на проверку или запишите своё рядом");
    }
    const issues = check(body.proposals);
    if (issues.length)
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Проверка отклонила запись",
          status: 422,
          code: "check_rejected",
          issues,
        },
        { status: 422, headers: { "content-type": "application/problem+json" } },
      );
    const records = write(body.proposals, body.links ?? []);
    db.save();
    return HttpResponse.json({
      changeset_id: newId("task"),
      complete: true,
      records,
      queued: [],
      report: {},
    });
  }),

  http.get("/api/v1/templates", ({ request }) => {
    const target = new URL(request.url).searchParams.get("target");
    const count = (code: string) => db.records.filter((r) => r.kind_or_class === code).length;
    return HttpResponse.json(
      db.templates
        .filter((t) => !target || t.target === target)
        .map((t) => ({ ...t, records: count(t.code) })),
    );
  }),
  http.put("/api/v1/packs/mine/templates/:code", async ({ params, request }) => {
    const code = String(params.code);
    const d = (await request.json()) as {
      label: L;
      target: "atom" | "entity";
      family: string;
      form: { key: string; label: L; type: string }[];
      body: string;
      widgets: string[];
    };
    const clash = db.templates.find((t) => t.code === code && !t.editable);
    if (clash) return problem(409, `Код «${code}» уже занят видом пакета ${clash.pack}`);
    const issues: Issue[] = [];
    if (!d.label?.ru?.trim())
      issues.push({
        code: "required",
        severity: "violation",
        message: "Нужно имя вида",
        path: "label.ru",
        ref: code,
      });
    d.form.forEach((f, i) => {
      if (!f.label?.ru?.trim())
        issues.push({
          code: "required",
          severity: "violation",
          message: "Нужно имя свойства",
          path: `form[${i}].label.ru`,
          ref: code,
        });
    });
    if (issues.length)
      return HttpResponse.json(
        { type: "about:blank", title: "Шаблон не прошёл проверку", status: 422, issues },
        { status: 422, headers: { "content-type": "application/problem+json" } },
      );
    const view = {
      code,
      pack: "mine",
      applies_to: code,
      description: null,
      editable: true,
      records: 0,
      ...d,
    };
    db.templates = [...db.templates.filter((t) => t.code !== code), view as never];
    db.save();
    return HttpResponse.json(view);
  }),
  http.delete("/api/v1/packs/mine/templates/:code", ({ params }) => {
    const n = db.records.filter((r) => r.kind_or_class === params.code).length;
    if (n) return problem(409, `Есть записи этого вида: ${n}`, "Сначала смените им вид");
    db.templates = db.templates.filter((t) => t.code !== params.code);
    db.save();
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/vocab/kind", () =>
    HttpResponse.json([
      ...vocabKind,
      ...db.templates
        .filter((t) => t.pack !== "core" && t.target === "atom")
        .map((t) => ({ code: t.code, label: t.label, pack: t.pack, broader: null })),
    ]),
  ),
  http.get("/api/v1/vocab/property", () => HttpResponse.json(vocabProperty)),
  http.get("/api/v1/vocab/tag", () =>
    HttpResponse.json(
      [...new Set(db.records.flatMap((r) => r.tags ?? []))].map((t) => ({
        code: t,
        label: { ru: t, en: t },
        pack: "core",
        broader: null,
      })),
    ),
  ),

  http.get("/api/v1/objects", ({ request }) => {
    const q = (new URL(request.url).searchParams.get("q") ?? "").toLowerCase();
    const items = Object.values(db.objects).filter(
      (o) =>
        !q ||
        o.original_name.toLowerCase().includes(q) ||
        o.logical_paths.some((p) => p.toLowerCase().includes(q)),
    );
    return HttpResponse.json({ items, next_cursor: null });
  }),
  http.post("/api/v1/objects", async ({ request }) => {
    const form = await request.formData();
    const file = form.get("file") as File | null;
    if (!file) return problem(422, "Нужен файл");
    const same = Object.values(db.objects).find((o) => o.original_name === file.name);
    if (same) return HttpResponse.json(same, { status: 200 });
    const id = newId("obj");
    const path = String(form.get("path") ?? `~/Документы/Загрузки/${file.name}`);
    const o = {
      id,
      kind: "file",
      original_name: file.name,
      media_type: file.type || null,
      url: null,
      logical_paths: [path],
      status: "skipped",
      pages: null,
      sheets: null,
      versions: [
        {
          n: 1,
          digest: `sha256:${id.slice(-6)}`,
          size: file.size,
          recorded_at: new Date().toISOString(),
          cited_by: 0,
        },
      ],
      cited_by: [],
    };
    db.objects[id] = o as never;
    db.save();
    return HttpResponse.json(o, { status: 201 });
  }),

  http.get("/api/v1/tasks", ({ request }) => {
    const u = new URL(request.url);
    const state = u.searchParams.get("state");
    const object = u.searchParams.get("object");
    return HttpResponse.json(
      db.tasks.filter((t) => (!state || t.state === state) && (!object || t.object === object)),
    );
  }),
  http.post("/api/v1/tasks", async ({ request }) => {
    const b = (await request.json()) as { object: string; version: number; note?: string };
    const t = {
      id: newId("task"),
      kind: "parse" as const,
      object: b.object,
      version: b.version,
      note: b.note ?? null,
      state: "open" as const,
      created_by: session.agent,
      claimed_by: null,
      claimed_until: null,
    };
    db.tasks.push(t);
    db.save();
    return HttpResponse.json({ task_id: t.id }, { status: 202 });
  }),

  http.post("/api/v1/folders", async ({ request }) => {
    const { path } = (await request.json()) as { path: string };
    const clean = path
      .trim()
      .replace(/\/+/g, "/")
      .replace(/^\/|\/$/g, "");
    if (!clean || clean.split("/").some((s) => !s.trim() || s.length > 80))
      return problem(422, "Имя папки — от 1 до 80 знаков, без пустых частей пути");
    if (db.folders.includes(clean)) return problem(409, "Такая папка уже есть");
    db.folders.push(clean);
    db.save();
    return HttpResponse.json(
      { path: clean, name: clean.split("/").pop(), count: 0, children: [] },
      { status: 201 },
    );
  }),
  http.patch("/api/v1/folders/*", async ({ request, params }) => {
    const from = decodeURIComponent(String(params[0]));
    const { path: to } = (await request.json()) as { path: string };
    if (!db.folders.includes(from)) return problem(404, "Папки нет");
    if (db.folders.includes(to)) return problem(409, "Такая папка уже есть");
    const move = (p: string) => (p === from ? to : p.startsWith(`${from}/`) ? to + p.slice(from.length) : p);
    const folders = db.folders.filter((p) => move(p) !== p).length;
    db.folders = db.folders.map(move);
    let records = 0;
    for (const r of db.records)
      if (r.folder && move(r.folder) !== r.folder) {
        r.folder = move(r.folder);
        records += 1;
      }
    db.save();
    return HttpResponse.json({ from, to, folders, records });
  }),
  http.delete("/api/v1/folders/*", ({ params }) => {
    const p = decodeURIComponent(String(params[0]));
    const busy =
      db.records.some((r) => r.folder === p || r.folder?.startsWith(`${p}/`)) ||
      db.folders.some((f) => f.startsWith(`${p}/`));
    if (busy) return problem(409, "В папке есть записи или вложенные папки");
    db.folders = db.folders.filter((f) => f !== p);
    db.save();
    return new HttpResponse(null, { status: 204 });
  }),
  http.patch("/api/v1/records/:ref/folder", async ({ params, request }) => {
    const { folder } = (await request.json()) as { folder: string | null };
    const r = db.records.find((x) => x.ref === params.ref);
    if (!r) return problem(404, `Записи ${params.ref} нет`);
    writeLog.push("folder");
    r.folder = folder;
    const v = db.views[String(params.ref)];
    if (v) v.folder = folder;
    db.events.push({
      type: "folder",
      id: newId("task"),
      at: new Date().toISOString(),
      ref: r.ref,
      label: r.label,
      agent: session.agent,
    } as never);
    db.save();
    return HttpResponse.json(r);
  }),
  http.post("/api/v1/review/enqueue", async () =>
    HttpResponse.json({ item_id: "7a1c2b3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d" }),
  ),
];
