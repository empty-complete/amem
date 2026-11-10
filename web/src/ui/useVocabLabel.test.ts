import { humanize } from "./useVocabLabel";

test("код без словаря — по-человечески", () => {
  expect(humanize("operating_conditions")).toBe("Operating conditions");
  expect(humanize("polling")).toBe("Polling");
});
