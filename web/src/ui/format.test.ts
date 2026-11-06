import { agentName, formatSize, formatValue, unitLabel } from "./format";

test("значения словами", () => {
  expect(formatValue({ value_text: "±2", unit: "%" })).toBe("±2 %");
  expect(formatValue({ amount: 60, unit: "s" })).toBe("60 с");
  expect(formatValue({ lower_bound: -40, upper_bound: 60, unit: "Cel" })).toBe("−40…60 °C");
  expect(formatValue({ value_text: "IP65" })).toBe("IP65");
  expect(formatValue({ upper_bound: 90, unit: "%" })).toBe("до 90 %");
  expect(unitLabel("hPa", "en")).toBe("hPa");
});

test("размер и агент", () => {
  expect(formatSize(40666)).toMatch(/^39,7\sКБ$/);
  expect(agentName("model:extractor")).toBe("extractor (модель)");
  expect(agentName("person:anna")).toBe("anna");
});
