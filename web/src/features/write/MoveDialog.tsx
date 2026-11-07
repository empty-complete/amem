import { Button } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Heading, Modal, ModalOverlay, Radio, RadioGroup } from "react-aria-components";
import { useTranslation } from "react-i18next";
import { q } from "../../api/queries";
import type { components } from "../../api/schema";
import { useMoveRecord } from "./move";

type Folder = components["schemas"]["Folder"];
const flat = (fs: Folder[], depth = 0): { path: string; name: string; depth: number }[] =>
  fs.flatMap((f) => [{ path: f.path, name: f.name, depth }, ...flat(f.children, depth + 1)]);

/** «Переместить в папку» — то же, что перетаскивание, но из меню записи. */
export function MoveDialog({
  recordRef,
  current,
  open,
  onClose,
}: {
  recordRef: string;
  current: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const tree = useQuery({ ...q.folders(), enabled: open });
  const move = useMoveRecord();
  const [to, setTo] = useState<string>(current ?? "-");
  const items = flat(tree.data?.folders ?? []);
  return (
    <ModalOverlay isOpen={open} onOpenChange={(o) => !o && onClose()} isDismissable className="modal-overlay">
      <Modal className="modal">
        <Dialog className="modal__in" aria-label={t("folders.move_title")}>
          <Heading slot="title">{t("folders.move_title")}</Heading>
          <RadioGroup value={to} onChange={setTo} aria-label={t("folders.move_title")} className="movelist">
            {items.map((f) => (
              <Radio
                key={f.path}
                value={f.path}
                className="moveopt"
                style={{ paddingLeft: `calc(${f.depth} * 1rem + var(--s-xs))` }}
              >
                {f.name}
              </Radio>
            ))}
            <Radio value="-" className="moveopt">
              {t("folders.unfiled")}
            </Radio>
          </RadioGroup>
          <div className="editor__foot">
            <Button
              className="pillbtn"
              isDisabled={to === (current ?? "-")}
              onPress={() => {
                const name =
                  to === "-" ? t("folders.unfiled") : (items.find((x) => x.path === to)?.name ?? to);
                move(recordRef, to === "-" ? null : to, t("folders.moved", { to: name }));
                onClose();
              }}
            >
              {t("folders.move_to")}
            </Button>
            <Button variant="ghost" onPress={onClose}>
              {t("edit.cancel")}
            </Button>
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
