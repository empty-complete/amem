import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useOpenedVersion, useUpdates } from "./updates";

/** Служба перезапустилась на новой версии, а страница открыта со старой — предложить перезагрузить. */
export function ReloadBanner() {
  const { t } = useTranslation();
  const s = useUpdates().data;
  const opened = useOpenedVersion();
  if (!s || !opened || s.current === opened) return null;
  return (
    <div className="updbanner" role="status">
      <span>{t("updates.reload_text", { v: s.current })}</span>
      <Button size="sm" className="pillbtn" onPress={() => window.location.reload()}>
        {t("updates.reload")}
      </Button>
    </div>
  );
}
