import { setupWorker } from "msw/browser";
import manualPdfUrl from "./fixtures/manual.pdf?url";
import { handlers } from "./handlers";
import { handlersB } from "./handlers-b";

const pdf = async () => (await fetch(manualPdfUrl)).arrayBuffer();

export const worker = setupWorker(...handlersB(pdf), ...handlers);
