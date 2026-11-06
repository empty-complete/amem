import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { RegionState } from "../../ui/RegionState";

/** Экран, который придёт в следующих частях (B–F). */
export function Stub() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <RegionState
      state="empty"
      text={t("stub.later")}
      action={{ label: t("stub.home"), onPress: () => navigate({ to: "/" }) }}
    />
  );
}
