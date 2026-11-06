import card from "../../mocks/fixtures/card-e3.json";
import { summarize } from "./card";

test("полоса полноты и обязательные без значения из amem.card/1", () => {
  const s = summarize(card as never);
  expect(s.parts).toEqual({ known: 2, conflict: 1, asked: 1, missing: 2, na: 1 });
  expect(s.total).toBe(7);
  expect(s.blockers).toEqual(["Рабочая температура"]);
});

test("группы — в порядке полей профиля", () => {
  expect(summarize(card as never).groups.map((g) => g.name)).toEqual(["Измерение", "Условия", "Опрос"]);
});
