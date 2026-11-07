import type { Star } from "./model";

/** Событие «запись создана»: часть D пишет, окна неба слушают и зажигают звезду. */
export interface RecordCreated {
  star: Star;
  links: { source: string; target: string; rel: string }[];
}

const target = new EventTarget();

export const skyBus = {
  emit(detail: RecordCreated) {
    target.dispatchEvent(new CustomEvent("record-created", { detail }));
  },
  /** Снять временную звезду: запись отменена, отклонена или пришла настоящая. */
  retract(id: string) {
    target.dispatchEvent(new CustomEvent("record-retracted", { detail: id }));
  },
  onRetract(fn: (id: string) => void) {
    const h = (e: Event) => fn((e as CustomEvent<string>).detail);
    target.addEventListener("record-retracted", h);
    return () => target.removeEventListener("record-retracted", h);
  },
  on(fn: (d: RecordCreated) => void) {
    const h = (e: Event) => fn((e as CustomEvent<RecordCreated>).detail);
    target.addEventListener("record-created", h);
    return () => target.removeEventListener("record-created", h);
  },
};
