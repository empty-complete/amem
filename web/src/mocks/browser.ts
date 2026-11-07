import { setupWorker } from "msw/browser";
import manualPdfUrl from "./fixtures/manual.pdf?url";
import { handlers } from "./handlers";
import { handlersB } from "./handlers-b";
import { handlersC } from "./handlers-c";
import { handlersD } from "./handlers-d";

const pdf = async () => (await fetch(manualPdfUrl)).arrayBuffer();

export const worker = setupWorker(...handlersD, ...handlersC, ...handlersB(pdf), ...handlers);
