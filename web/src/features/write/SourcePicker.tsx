import { Button } from "@heroui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useRef, useState } from "react";
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/errors";
import { contentUrl, q } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon } from "../../ui/icons";
import { RegionState } from "../../ui/RegionState";
import { SheetPreview } from "../source/SheetPreview";
import { fileType } from "../source/SourcePanel";
import { TextFragment } from "../source/TextFragment";
import type { DraftSource } from "./proposal";

const PdfPage = lazy(() => import("../source/PdfPage"));
type Obj = components["schemas"]["ObjectView"];

/** Загрузка файла: служба кладёт его в папку документов; тот же файл — тот же объект (200). */
async function upload(file: File): Promise<Obj> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await globalThis.fetch(`${location.origin}/api/v1/objects`, {
    method: "POST",
    body: fd,
    credentials: "same-origin",
  });
  if (!res.ok) {
    const p = (await res.json().catch(() => ({}))) as { title?: string; detail?: string };
    throw new ApiError(res.status, p.title ?? "Не удалось загрузить файл", p.detail);
  }
  return (await res.json()) as Obj;
}

/** Bbox протяжкой по картинке: доли ширины и высоты, как селектор amem. */
function BoxPick({ src, alt, onPick }: { src: string; alt: string; onPick: (b: string) => void }) {
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const rel = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  };
  return (
    <div
      className="boxpick"
      onPointerDown={(e) => {
        start.current = rel(e);
        setBox({ ...start.current, w: 0, h: 0 });
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const p = rel(e);
        const s = start.current;
        setBox({
          x: Math.min(s.x, p.x),
          y: Math.min(s.y, p.y),
          w: Math.abs(p.x - s.x),
          h: Math.abs(p.y - s.y),
        });
      }}
      onPointerUp={() => {
        start.current = null;
        if (box && box.w > 0.01 && box.h > 0.01)
          onPick([box.x, box.y, box.w, box.h].map((v) => v.toFixed(3)).join(","));
      }}
    >
      <img src={src} alt={alt} draggable={false} />
      {box && (
        <span
          className="boxpick__rect"
          style={{
            left: `${box.x * 100}%`,
            top: `${box.y * 100}%`,
            width: `${box.w * 100}%`,
            height: `${box.h * 100}%`,
          }}
        />
      )}
    </div>
  );
}

/** «+ Источник» (разд. 5.4): файл (найти или загрузить), затем место по виду файла. */
export function SourcePicker({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (s: DraftSource) => void;
}) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [obj, setObj] = useState<Obj | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [quote, setQuote] = useState("");
  const [place, setPlace] = useState<{ type: string; value: string }[]>([]);
  const list = useQuery({ ...q.objects(text), enabled: open && !obj });
  const fileInput = useRef<HTMLInputElement>(null);
  const last = obj?.versions[obj.versions.length - 1];
  const reset = () => {
    setObj(null);
    setQuote("");
    setPlace([]);
    setPage(1);
    setErr(null);
  };
  const done = () => {
    if (!obj || !last) return;
    const pdf = obj.media_type === "application/pdf";
    const selectors = pdf ? [{ type: "page", value: String(page) }] : place;
    onPick({
      object: obj.id,
      object_name: obj.original_name,
      object_version: last.n,
      media_type: obj.media_type,
      selectors,
      quote: quote.trim() || null,
    });
    reset();
    onClose();
  };
  const kind = !obj
    ? null
    : obj.media_type === "application/pdf"
      ? "pdf"
      : obj.sheets?.length
        ? "sheet"
        : obj.media_type?.startsWith("image/")
          ? "image"
          : "text";

  return (
    <ModalOverlay
      isOpen={open}
      onOpenChange={(o) => {
        if (!o) {
          reset();
          onClose();
        }
      }}
      isDismissable
      className="modal-overlay"
    >
      <Modal className="modal modal--wide">
        <Dialog className="modal__in" aria-label={t("pick.title")}>
          <Heading slot="title">{obj ? obj.original_name : t("pick.title")}</Heading>
          {err && (
            <p className="fielderr" role="alert">
              {err}
            </p>
          )}
          {!obj ? (
            <>
              <div className="pick__find">
                <input
                  className="fld"
                  type="search"
                  aria-label={t("pick.search")}
                  placeholder={t("pick.search")}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <Button variant="outline" onPress={() => fileInput.current?.click()}>
                  <Icon name="plus" />
                  {t("pick.upload")}
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  hidden
                  aria-label={t("pick.upload")}
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    try {
                      const o = await upload(f);
                      qc.invalidateQueries({ queryKey: ["objects"] });
                      setObj(o);
                    } catch (x) {
                      setErr((x as ApiError).detail ?? (x as Error).message);
                    }
                  }}
                />
              </div>
              {list.isPending ? (
                <RegionState state="loading" />
              ) : (
                <ul className="pick__list">
                  {list.data?.items.map((o) => (
                    <li key={o.id}>
                      <button type="button" className="cite" onClick={() => setObj(o)}>
                        <span className="ft" aria-hidden="true">
                          {fileType(o, i18n.language)}
                        </span>
                        <span className="cite__main">
                          <span>{o.original_name}</span>
                          <span className="muted">{o.logical_paths?.[0]}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <div className="pick__place">
              {kind === "pdf" && last && (
                <>
                  <div className="pick__row">
                    <Button
                      size="sm"
                      variant="ghost"
                      isDisabled={page <= 1}
                      onPress={() => setPage((p) => p - 1)}
                      aria-label={t("pick.prev")}
                    >
                      ←
                    </Button>
                    <span>{t("source.page", { n: page })}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      isDisabled={!!obj.pages && page >= obj.pages}
                      onPress={() => setPage((p) => p + 1)}
                      aria-label={t("pick.next")}
                    >
                      →
                    </Button>
                    <span className="muted">{t("pick.select_hint")}</span>
                  </div>
                  <Suspense fallback={<RegionState state="loading" />}>
                    <div className="pick__preview">
                      <PdfPage
                        url={contentUrl(obj.id, last.n)}
                        page={page}
                        quotes={quote ? [quote] : []}
                        onSelectText={setQuote}
                      />
                    </div>
                  </Suspense>
                </>
              )}
              {kind === "sheet" && last && (
                <>
                  <p className="muted">{t("pick.range_hint")}</p>
                  <SheetPreview
                    id={obj.id}
                    version={last.n}
                    sheets={obj.sheets ?? []}
                    cited={[]}
                    onPick={(sheet, range) =>
                      setPlace([
                        { type: "sheet", value: sheet },
                        { type: "range", value: range },
                      ])
                    }
                  />
                  <label className="pick__row">
                    {t("pick.range")}
                    <input
                      className="fld"
                      value={place.find((p) => p.type === "range")?.value ?? ""}
                      placeholder="B4:C9"
                      onChange={(e) =>
                        setPlace([
                          {
                            type: "sheet",
                            value: place.find((p) => p.type === "sheet")?.value ?? obj.sheets?.[0] ?? "",
                          },
                          { type: "range", value: e.target.value.toUpperCase() },
                        ])
                      }
                    />
                  </label>
                </>
              )}
              {kind === "image" && last && (
                <>
                  <p className="muted">{t("pick.box_hint")}</p>
                  <BoxPick
                    src={contentUrl(obj.id, last.n)}
                    alt={obj.original_name ?? ""}
                    onPick={(b) => setPlace([{ type: "bbox", value: b }])}
                  />
                </>
              )}
              {kind === "text" && last && (
                <>
                  <p className="muted">{t("pick.select_hint")}</p>
                  <div className="pick__preview">
                    <TextFragment
                      id={obj.id}
                      version={last.n}
                      quotes={quote ? [quote] : []}
                      onSelectText={(s, [a, b]) => {
                        setQuote(s);
                        setPlace([{ type: "lines", value: a === b ? String(a) : `${a}-${b}` }]);
                      }}
                    />
                  </div>
                </>
              )}
              {(kind === "pdf" || kind === "text") && (
                <label className="pick__quote">
                  {t("pick.quote")}
                  <textarea
                    className="fld"
                    rows={2}
                    value={quote}
                    onChange={(e) => setQuote(e.target.value)}
                  />
                </label>
              )}
            </div>
          )}
          <div className="editor__foot">
            {obj && (
              <Button className="pillbtn" onPress={done}>
                {t("pick.done")}
              </Button>
            )}
            {obj && (
              <Button variant="ghost" onPress={reset}>
                {t("pick.other")}
              </Button>
            )}
            <Button
              variant="ghost"
              onPress={() => {
                reset();
                onClose();
              }}
            >
              {t("edit.cancel")}
            </Button>
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
