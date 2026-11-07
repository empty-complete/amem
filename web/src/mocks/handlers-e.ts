import { HttpResponse, http } from "msw";
import { db } from "./db";
import backups from "./fixtures/backups.json";
import baseFx from "./fixtures/base.json";
import objectsFx from "./fixtures/objects-b.json";
import session from "./fixtures/session.json";
import { problem } from "./handlers-b";

const open = () => db.reviewItems.filter((i) => i.state === "queued" || i.state === "claimed");
const ago = (iso: string) => {
  const m = Math.max(1, Math.round((Date.now() - Date.parse(iso)) / 60000));
  return m < 60 ? `${m} мин назад` : `${Math.round(m / 60)} ч назад`;
};

/** Проверка (часть E): очередь, пункт, решение (409 — уже решено), статистика, «База» и бэкапы. */
export const handlersE = [
  http.get("/api/v1/review/items", ({ request }) => {
    const u = new URL(request.url);
    const state = u.searchParams.get("state");
    const reason = u.searchParams.get("reason");
    const record = u.searchParams.get("record");
    const items = db.reviewItems
      .filter((i) => (!state ? i.state === "queued" || i.state === "claimed" : i.state === state))
      .filter((i) => !reason || i.reason === reason)
      .filter((i) => !record || i.ref === record)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json(items);
  }),
  http.get("/api/v1/review/items/:id", ({ params }) => {
    const v = db.reviewViews[String(params.id)];
    if (!v) return problem(404, "Пункта нет");
    const item = db.reviewItems.find((i) => i.id === params.id) ?? v.item;
    // запись — из хранилища: решение меняет её статус
    const record = db.views[item.ref] ?? v.record;
    return HttpResponse.json({ ...v, item, record });
  }),
  http.post("/api/v1/review/items/:id/resolve", async ({ params, request }) => {
    const { outcome, note } = (await request.json()) as { outcome: "confirmed" | "refuted" | "uncertain"; note?: string };
    const it = db.reviewItems.find((i) => i.id === params.id);
    if (!it) return problem(404, "Пункта нет");
    if (it.state === "done" || it.state === "obsolete") {
      const d = db.decisions.find((x) => x.id === it.id);
      return problem(409, "Уже решено", `${(d?.by ?? it.author ?? "кто-то").replace(/^person:/, "")}, ${ago(d?.at ?? it.closed_at ?? it.created_at)}`);
    }
    const now = new Date().toISOString();
    it.state = "done";
    (it as { closed_at: string | null }).closed_at = now;
    const status = outcome === "confirmed" ? "verified" : outcome === "refuted" ? "rejected" : "needs_review";
    const s = db.records.find((r) => r.ref === it.ref);
    if (s) s.status = status as never;
    const v = db.views[it.ref];
    if (v) {
      v.status = status as never;
      v.review_state = (outcome === "confirmed" ? "accepted" : outcome === "refuted" ? "declined" : "pending") as never;
      v.open_items = v.open_items.filter((o) => o.id !== it.id);
    }
    db.decisions.push({ id: it.id, outcome, by: session.agent, at: now });
    db.events.push({ type: "review", id: `rv-${it.id}`, at: now, ref: it.ref, label: it.label, agent: session.agent, review_state: v?.review_state ?? "accepted", ...(note ? { note } : {}) } as never);
    db.save();
    return HttpResponse.json({ verification_id: crypto.randomUUID(), status, queued: [] });
  }),
  http.get("/api/v1/review/stats", ({ request }) => {
    const days = Number(new URL(request.url).searchParams.get("days") ?? 7);
    const byReason: Record<string, { open: number; claimed: number }> = {};
    for (const i of open()) {
      const b = (byReason[i.reason] ??= { open: 0, claimed: 0 });
      b[i.state === "claimed" ? "claimed" : "open"] += 1;
    }
    const done = db.reviewItems.filter((i) => i.state === "done" && i.closed_at);
    const mins = done.map((i) => (Date.parse(i.closed_at as string) - Date.parse(i.created_at)) / 60000).sort((a, b) => a - b);
    const records: Record<string, number> = {};
    for (const r of db.records) records[r.status] = (records[r.status] ?? 0) + 1;
    const verdicts: Record<string, number> = {};
    for (const o of Object.values(objectsFx)) for (const c of o.cited_by) verdicts[c.verdict ?? "none"] = (verdicts[c.verdict ?? "none"] ?? 0) + 1;
    return HttpResponse.json({
      now: new Date().toISOString(),
      days,
      queue: { open: open().length, by_reason: byReason },
      done: { count: done.length, median_minutes: mins.length ? Math.round(mins[Math.floor(mins.length / 2)] as number) : null },
      records,
      verdicts,
      changesets: db.events.length,
      audit: db.reviewItems.filter((i) => i.reason === "audit").length,
    });
  }),
  http.get("/api/v1/base", () =>
    HttpResponse.json({
      ...baseFx,
      packs: [...baseFx.packs, ...(db.templates.some((t) => t.pack === "mine") ? [{ name: "mine", version: "1", digest: "sha256-c1:mine" }] : [])],
      review_open: open().length,
    }),
  ),
  http.get("/api/v1/backups", () => HttpResponse.json(backups)),
];
