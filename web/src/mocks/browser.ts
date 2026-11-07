import { setupWorker } from "msw/browser";
import bundleZipUrl from "./fixtures/bundle-sample.zip?url";
import manualPdfUrl from "./fixtures/manual.pdf?url";
import { handlers } from "./handlers";
import { handlersB } from "./handlers-b";
import { handlersC } from "./handlers-c";
import { handlersD } from "./handlers-d";
import { handlersE } from "./handlers-e";
import { handlersF } from "./handlers-f";

const pdf = async () => (await fetch(manualPdfUrl)).arrayBuffer();

export const worker = setupWorker(
  ...handlersF(async () => (await fetch(bundleZipUrl)).arrayBuffer()),
  ...handlersE,
  ...handlersD,
  ...handlersC,
  ...handlersB(pdf),
  ...handlers,
);
