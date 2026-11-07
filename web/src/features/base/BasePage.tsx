import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { formatDate, formatSize } from "../../ui/format";
import { RegionState } from "../../ui/RegionState";
import "./base.css";

type Stats = {
  days?: number;
  queue?: { open?: number; by_reason?: Record<string, { open: number; claimed: number }> };
  done?: { count?: number; median_minutes?: number | null };
  records?: Record<string, number>;
  verdicts?: Record<string, number>;
};

/** «База» (разд. 5.10): только чтение — статусы, очередь, сверка, пакеты, бэкапы. Таблицы, без графиков. */
export function BasePage() {
  const { t, i18n } = useTranslation();
  const base = useQuery(q.base());
  const stats = useQuery(q.reviewStats(7));
  const backups = useQuery(q.backups());
  if (base.isPending || stats.isPending) return <RegionState state="loading" />;
  if (base.isError)
    return (
      <RegionState
        state="error"
        message={errorText(base.error, t("region.offline"))}
        retry={() => base.refetch()}
      />
    );
  const s = (stats.data ?? {}) as Stats;
  const days = s.days ?? 7;
  const num = (n: number) => n.toLocaleString(i18n.language);
  return (
    <section className="basepage" aria-labelledby="base-title">
      <div className="page-head">
        <h1 id="base-title">{base.data.name ?? t("basepage.title")}</h1>
      </div>
      <div className="basegrid">
        <table>
          <caption>{t("basepage.records")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("basepage.status")}</th>
              <th scope="col" className="n">
                {t("basepage.count")}
              </th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(s.records ?? {}).map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{t(`status.${k}`, { defaultValue: k })}</th>
                <td className="n">{num(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <table>
          <caption>{t("basepage.queue")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("review.reason")}</th>
              <th scope="col" className="n">
                {t("basepage.waiting")}
              </th>
              <th scope="col" className="n">
                {t("basepage.claimed")}
              </th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(s.queue?.by_reason ?? {}).map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{t(`review.r.${k}`, { defaultValue: k })}</th>
                <td className="n">{num(v.open)}</td>
                <td className="n">{num(v.claimed)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3} className="muted">
                {s.done?.median_minutes != null
                  ? t("basepage.median", {
                      n: days,
                      m: t("basepage.minutes", { count: s.done.median_minutes }),
                    })
                  : t("basepage.no_median", { n: days })}{" "}
                <Link to="/review">{t("basepage.to_review")}</Link>
              </td>
            </tr>
          </tfoot>
        </table>

        <table>
          <caption>{t("basepage.verdicts")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("basepage.verdict")}</th>
              <th scope="col" className="n">
                {t("basepage.count")}
              </th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(s.verdicts ?? {}).map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{t(`source.verdict.${k}`, { defaultValue: k })}</th>
                <td className="n">{num(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <table>
          <caption>{t("basepage.packs")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("basepage.pack")}</th>
              <th scope="col">{t("basepage.version")}</th>
              <th scope="col">{t("basepage.digest")}</th>
            </tr>
          </thead>
          <tbody>
            {base.data.packs.map((p) => (
              <tr key={p.name}>
                <th scope="row">{p.name === "mine" ? t("basepage.mine") : p.name}</th>
                <td>{p.version}</td>
                <td className="mono">{p.digest ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <table>
          <caption>{t("basepage.backups")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("basepage.file")}</th>
              <th scope="col">{t("basepage.when")}</th>
              <th scope="col" className="n">
                {t("basepage.size")}
              </th>
            </tr>
          </thead>
          <tbody>
            {(backups.data ?? []).map((b) => (
              <tr key={b.name}>
                <th scope="row" className="mono">
                  {b.name}
                </th>
                <td>{formatDate(b.created_at, i18n.language, true)}</td>
                <td className="n">{formatSize(b.size, i18n.language)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="basemeta">
        <dt>{t("basepage.id")}</dt>
        <dd className="mono">{base.data.base_id}</dd>
        <dt>{t("basepage.amem")}</dt>
        <dd>{base.data.amem_version}</dd>
      </dl>
    </section>
  );
}
