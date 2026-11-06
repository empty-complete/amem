import { ToggleButton, ToggleButtonGroup } from "@heroui/react";
import { Link } from "@tanstack/react-router";
import type { TFunction } from "i18next";
import { lazy, Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { contentUrl } from "../../api/queries";
import type { components } from "../../api/schema";
import { Icon, type IconName } from "../../ui/icons";
import { RegionState } from "../../ui/RegionState";
import { TextFragment } from "./TextFragment";
import "./source.css";

const PdfPage = lazy(() => import("./PdfPage"));

type Source = components["schemas"]["SourceView"];
type Selector = { type: string; value?: unknown; label?: string };
type Verdict = NonNullable<Source["verdict"]> | "none";

const VERDICT: Record<Verdict, [IconName, "ok" | "wait" | "bad" | "quiet"]> = {
  ok: ["check", "ok"],
  moved: ["check", "ok"],
  fuzzy: ["warn", "wait"],
  by_locator: ["warn", "wait"],
  unresolved: ["cross", "bad"],
  not_found: ["cross", "bad"],
  no_file: ["cross", "bad"],
  no_text: ["dash", "quiet"],
  external: ["dash", "quiet"],
  error: ["cross", "bad"],
  none: ["dash", "quiet"],
};

const sel = (s: Source, type: string) =>
  (s.selectors as unknown as Selector[] | undefined)?.find((x) => x.type === type);

/** Тип файла коротко: PDF, XLSX, MD, САЙТ, ПИСЬМО. */
export function fileType(
  s: { media_type?: string | null; object_kind?: string; object_name?: string; original_name?: string },
  lang = "ru",
) {
  if (s.object_kind === "web") return lang.startsWith("en") ? "WEB" : "САЙТ";
  if (s.object_kind === "message") return lang.startsWith("en") ? "MAIL" : "ПИСЬМО";
  const name = s.object_name ?? s.original_name ?? "";
  const ext = name.includes(".") ? name.split(".").pop() : "";
  if (ext) return ext.toUpperCase().slice(0, 4);
  return (s.media_type ?? "").split("/").pop()?.toUpperCase().slice(0, 4) ?? "";
}

/** Место в файле словами: «страница 12», «лист В-2, B4:C9». */
export function placeText(selectors: unknown[] | undefined, t: TFunction) {
  const parts: string[] = [];
  for (const s of (selectors ?? []) as Selector[]) {
    if (s.type === "page") parts.push(t("source.page", { n: s.label ?? s.value }));
    else if (s.type === "sheet") parts.push(t("source.sheet", { name: s.value }));
    else if (s.type === "range") parts.push(String(s.value));
    else if (s.label || s.value) parts.push(String(s.label ?? s.value));
  }
  return parts.join(", ");
}

export function VerdictText({ verdict }: { verdict: Source["verdict"] | null | undefined }) {
  const { t } = useTranslation();
  const v: Verdict = verdict ?? "none";
  const [icon, tone] = VERDICT[v];
  return (
    <span className="status" data-tone={tone}>
      <Icon name={icon} />
      {t(`source.verdict.${v}`)}
    </span>
  );
}

function Viewer({ s }: { s: Source }) {
  const { t } = useTranslation();
  const page = Number(sel(s, "page")?.value ?? 0) || undefined;
  const quotes = useMemo(() => (s.quote ? [s.quote] : []), [s.quote]);
  if (s.object_kind === "web" || s.object_kind === "message" || s.verdict === "no_file") {
    return s.quote ? (
      <blockquote className="quote">{s.quote}</blockquote>
    ) : (
      <p className="muted">{t("source.no_preview")}</p>
    );
  }
  if (s.media_type === "application/pdf") {
    return (
      <Suspense fallback={<RegionState state="loading" />}>
        <PdfPage url={contentUrl(s.object, s.object_version)} page={page ?? 1} quotes={quotes} />
      </Suspense>
    );
  }
  if (sel(s, "range") || sel(s, "sheet")) {
    return <p className="muted">{t("source.no_preview")}</p>;
  }
  return <TextFragment id={s.object} version={s.object_version} page={page} quotes={quotes} />;
}

/** Панель источника справа от записи: что за файл, где цитата, нашлась ли — и сама страница. */
export function SourcePanel({
  sources,
  basis,
  active,
  onActive,
}: {
  sources: Source[];
  basis?: string | null;
  active: number;
  onActive: (i: number) => void;
}) {
  const { t, i18n } = useTranslation();
  if (!sources.length) {
    return (
      <aside className="srcpanel" aria-label={t("source.panel")}>
        <p className="muted">
          {basis ? t("record.basis_line", { what: t(`record.basis.${basis}`) }) : t("source.none")}
        </p>
      </aside>
    );
  }
  const s = sources[Math.min(active, sources.length - 1)] as Source;
  const place = placeText(s.selectors, t);
  return (
    <aside className="srcpanel" aria-label={t("source.panel")}>
      <header className="srcpanel__head">
        {sources.length > 1 && (
          <ToggleButtonGroup
            size="sm"
            selectionMode="single"
            disallowEmptySelection
            selectedKeys={new Set([String(active)])}
            onSelectionChange={(keys) => {
              const k = [...keys][0];
              if (k != null) onActive(Number(k));
            }}
            aria-label={t("source.panel")}
          >
            {sources.map((x, i) => (
              <ToggleButton
                key={`${x.object}-${JSON.stringify(x.selectors)}`}
                id={String(i)}
                aria-label={t("source.which", { n: i + 1 })}
              >
                {i > 0 && <ToggleButtonGroup.Separator />}
                {i + 1}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        )}
        <div className="srcpanel__file">
          <span className="ft" aria-hidden="true">
            {fileType(s, i18n.language)}
          </span>
          <span className="srcpanel__name">
            <strong>{s.object_name ?? s.object}</strong>
            <span className="muted">
              {[place, t("source.version", { n: s.object_version })].filter(Boolean).join(" · ")}
            </span>
          </span>
        </div>
        <VerdictText verdict={s.verdict} />
      </header>
      <div className="srcpanel__view">
        <Viewer key={`${s.object}-${active}`} s={s} />
      </div>
      <footer className="srcpanel__foot">
        <Link to="/object/$id" params={{ id: s.object }} className="navlink">
          <Icon name="file" />
          {t("source.open_page")}
        </Link>
        {s.object_kind !== "web" && s.object_kind !== "message" && (
          <a
            className="navlink"
            href={contentUrl(s.object, s.object_version)}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="external" />
            {t("source.open_file")}
          </a>
        )}
      </footer>
    </aside>
  );
}
