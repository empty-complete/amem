// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { parse } from "yaml";
import base from "../src/mocks/fixtures/base.json";
import card from "../src/mocks/fixtures/card-e3.json";
import changes from "../src/mocks/fixtures/changes.json";
import folders from "../src/mocks/fixtures/folders.json";
import history from "../src/mocks/fixtures/history-a3.json";
import links from "../src/mocks/fixtures/links-a3.json";
import objects from "../src/mocks/fixtures/objects-b.json";
import records from "../src/mocks/fixtures/records.json";
import recordsB from "../src/mocks/fixtures/records-b.json";
import search from "../src/mocks/fixtures/search.json";
import searchOff from "../src/mocks/fixtures/search-semantic-off.json";
import session from "../src/mocks/fixtures/session.json";
import similar from "../src/mocks/fixtures/similar-a3.json";
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

test("records-b.json — RecordView", () => {
  for (const v of Object.values(recordsB)) check("RecordView", v);
});
test("card-e3.json — Card", () => check("Card", card));
test("objects-b.json — ObjectView", () => {
  for (const o of Object.values(objects)) check("ObjectView", o);
});
test("changes.json, history-a3.json — ChangesResult", () => {
  check("ChangesResult", changes);
  check("ChangesResult", history);
});
test("links-a3.json — LinkView[]", () => {
  for (const l of links) check("LinkView", l);
});
test("similar-a3.json — SearchResult", () => check("SearchResult", similar));
