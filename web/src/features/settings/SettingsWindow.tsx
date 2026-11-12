// Окно настроек поверх рабочей области, как в Obsidian: открывается кнопкой внизу панели папок и Ctrl+,.
import { Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { Icon } from "../../ui/icons";
import { SettingsView } from "./SettingsView";
import { settingsWindow, useSettingsWindow } from "./store";

export default function SettingsWindow() {
  const { t } = useTranslation();
  const section = useSettingsWindow();
  return (
    <ModalOverlay
      isOpen={section != null}
      onOpenChange={(o) => !o && settingsWindow.close()}
      isDismissable
      className="modal-overlay"
    >
      <Modal className="modal setwin">
        <Dialog className="setwin__in" aria-labelledby="setwin-title">
          <div className="setwin__bar">
            <Heading slot="title" id="setwin-title" className="setwin__title">
              {t("settings.title")}
            </Heading>
            <button
              type="button"
              className="iconbtn"
              aria-label={t("window.close")}
              onClick={() => settingsWindow.close()}
            >
              <Icon name="cross" />
            </button>
          </div>
          {section != null && <SettingsView initial={section} />}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
