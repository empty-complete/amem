import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { setupServer } from "msw/node";
import { handlers } from "./handlers";
import { handlersB } from "./handlers-b";
import { handlersC } from "./handlers-c";
import { handlersD } from "./handlers-d";
import { handlersE } from "./handlers-e";
import { handlersF } from "./handlers-f";

const pdf = async () => {
  const b = readFileSync(resolve(process.cwd(), "src/mocks/fixtures/manual.pdf"));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
};

export const server = setupServer(
  ...handlersF(async () => {
    const b = readFileSync(resolve(process.cwd(), "src/mocks/fixtures/bundle-sample.zip"));
    return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
  }),
  ...handlersE,
  ...handlersD,
  ...handlersC,
  ...handlersB(pdf),
  ...handlers,
);
