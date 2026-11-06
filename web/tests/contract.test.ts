// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { parse } from "yaml";
import base from "../src/mocks/fixtures/base.json";
import folders from "../src/mocks/fixtures/folders.json";
import records from "../src/mocks/fixtures/records.json";
import search from "../src/mocks/fixtures/search.json";
import searchOff from "../src/mocks/fixtures/search-semantic-off.json";
import session from "../src/mocks/fixtures/session.json";
import vocabClass from "../src/mocks/fixtures/vocab-entity_class.json";
import vocabKind from "../src/mocks/fixtures/vocab-kind.json";

const spec = parse(readFileSync(resolve(process.cwd(), "../docs/api/http-v1.openapi.yaml"), "utf8"));
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema({ $id: "openapi", components: spec.components });

function check(name: string, data: unknown) {
  const ok = ajv.validate({ $ref: `openapi#/components/schemas/${name}` }, data);
  expect(ajv.errorsText(ajv.errors, { dataVar: name })).toBe("No errors");
  expect(ok).toBe(true);
}

test("session.json — Session", () => check("Session", session));
test("base.json — Base", () => check("Base", base));
test("folders.json — FolderTree", () => check("FolderTree", folders));
test("records.json — RecordList", () => check("RecordList", records));
test("search.json — SearchResult", () => check("SearchResult", search));
test("search-semantic-off.json — SearchResult", () => check("SearchResult", searchOff));
test("vocab-kind.json — VocabEntry[]", () => {
  for (const v of [...vocabKind, ...vocabClass]) check("VocabEntry", v);
});
