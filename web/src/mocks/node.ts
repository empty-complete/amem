import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { setupServer } from "msw/node";
import { handlers } from "./handlers";
import { handlersB } from "./handlers-b";
import { handlersC } from "./handlers-c";

const pdf = async () => {
  const b = readFileSync(resolve(process.cwd(), "src/mocks/fixtures/manual.pdf"));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
};

export const server = setupServer(...handlersC, ...handlersB(pdf), ...handlers);
