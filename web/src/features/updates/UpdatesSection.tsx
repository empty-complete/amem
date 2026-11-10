import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/errors";
import { q } from "../../api/queries";
import { RelativeTime } from "../../ui/RelativeTime";
import { canInstall, useUpdateActions, useUpdates } from "./updates";
import "./updates.css";

/** «Настройки → Версия и обновления»: текущая версия, итог проверки, доступная версия, переключатель. */
export function UpdatesSection() {
  const { t } = useTranslation();
  const u = useUpdates();
  const session = useQuery(q.session());
  const act = useUpdateActions();
  const s = u.data;
  if (!s) return null; // служба без /updates: версия — в строке «Версия amemo» ниже
  const write = session.data?.can_write !== false;
  const busy = s.state === "checking" || s.state === "installing" || s.state === "restarting";
  const err = act.toggle.error ?? act.check.error ?? act.install.error;
  return (
    <section className="upd" aria-labelledby="upd-title">
      <h2 id="upd-title">{t("updates.title")}</h2>
      <p className="upd__now">
        <span className="upd__ver">amemo {s.current}</span>
        {s.channel === "pre" && <span className="muted"> · {t("updates.pre")}</span>}
      </p>
      <p className="muted upd__checked">
        {s.checked_at ? (
          <>
            {t("updates.checked")} <RelativeTime at={s.checked_at} />
            {s.latest ? "" : ` · ${t("updates.none")}`}
          </>
        ) : (
          t("updates.never")
        )}
      </p>
      {s.latest && (
        <div className="upd__avail" data-state={s.state}>
          <p>
            {s.latest.url ? (
              <a href={s.latest.url} target="_blank" rel="noopener noreferrer">
                {t("updates.available", { v: s.latest.version })}
              </a>
            ) : (
              t("updates.available", { v: s.latest.version })
            )}
          </p>
          {canInstall(s) && s.state === "available" && write && (
            <Button
              className="pillbtn"
              isPending={act.install.isPending}
              onPress={() => act.install.mutate()}
            >
              {t("updates.install")}
            </Button>
          )}
        </div>
      )}
      {s.message && (
        <p className="upd__msg" role="status" data-state={s.state}>
          {s.message}
        </p>
      )}
      <label className="chk upd__auto">
        <input
          type="checkbox"
          role="switch"
          aria-checked={s.auto}
          checked={s.auto}
          disabled={!write || act.toggle.isPending}
          onChange={(e) => act.toggle.mutate(e.target.checked)}
        />
        {t("updates.auto")}
      </label>
      {!canInstall(s) && <p className="muted">{t(`updates.manual_${s.install}`)}</p>}
      <div>
        <Button
          variant="outline"
          isDisabled={busy}
          isPending={act.check.isPending}
          onPress={() => act.check.mutate()}
        >
          {t("updates.check")}
        </Button>
      </div>
      {err && (
        <p className="fielderr" role="alert">
          {errorText(err, t("region.offline"))}
        </p>
      )}
    </section>
  );
}
