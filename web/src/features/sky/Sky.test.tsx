import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { forwardRef, useImperativeHandle } from "react";
import { renderWithApp } from "../../test/render";
import { skyBus } from "./bus";
import type { Sky as SkyModel } from "./model";
import { Sky } from "./Sky";

vi.mock("./SkyCanvas", () => ({
  default: forwardRef(function Fake(
    p: {
      sky: SkyModel;
      dim: Set<string>;
      selected: string | null;
      onSelect: (id: string | null) => void;
      onOpen: (id: string) => void;
    },
    ref,
  ) {
    useImperativeHandle(ref, () => ({
      add: () => {},
      fit: () => {},
      focus: () => {},
      screen: () => null,
      // звёзды по кругу: у соседей разные направления
      positions: () =>
        new Map(p.sky.nodes.map((n, i) => [n.id, { x: Math.cos(i) * 100, y: Math.sin(i) * 100 }])),
    }));
    return (
      <div>
        {p.sky.nodes.map((n) => (
          <button
            key={n.id}
            type="button"
            data-dim={p.dim.has(n.id) || undefined}
            aria-pressed={p.selected === n.id}
            onClick={() => p.onSelect(n.id)}
            onDoubleClick={() => p.onOpen(n.id)}
          >
            звезда {n.label}
          </button>
        ))}
      </div>
    );
  }),
}));

const E3 = "ent:0193b7c2-5e1a-7d40-9f2e-000000000003";
const A3 = "atm:0193b7c2-5e1a-7d40-9f2e-00000000000b";

test("выбор звезды показывает панель; «Открыть» ведёт на запись", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<Sky centerRef={E3} height={440} />, `/entity/${E3}`);
  await user.click(await screen.findByRole("button", { name: "звезда Погрешность влажности В-2: ±2 %" }));
  const card = screen.getByRole("region", { name: "Выбранная звезда" });
  expect(card).toHaveTextContent("Погрешность влажности В-2: ±2 %");
  expect(card).toHaveTextContent("Ждёт проверки");
  expect(
    await within(card).findByText(/только в диапазоне от 10 до 90/, {}, { timeout: 4000 }),
  ).toBeInTheDocument();
  await user.click(within(card).getByRole("link", { name: "Открыть" }));
  expect(decodeURIComponent(router.state.location.pathname)).toBe(`/atom/${A3}`);
});

test("подпись неба говорит, сколько звёзд и как ходить", async () => {
  await renderWithApp(<Sky centerRef={E3} height={440} />, `/entity/${E3}`);
  expect(await screen.findByRole("application", { name: /Небо: 19 звёзд, 21 связей/ })).toBeInTheDocument();
});

test("глубина 1 уменьшает окрестность", async () => {
  const user = userEvent.setup();
  await renderWithApp(<Sky centerRef={E3} height={440} />, `/entity/${E3}`);
  await screen.findByRole("application", { name: /19 звёзд/ });
  await user.click(screen.getByRole("radio", { name: "Глубина 1" }));
  expect(await screen.findByRole("application", { name: /Небо: \d звёзд/ })).toBeInTheDocument();
});

test("предел — честная строка", async () => {
  await renderWithApp(<Sky project="big" height={440} />, "/");
  expect(
    await screen.findByText(
      "Показано 300 звёзд из 420: объекты и самые связанные записи. Ищите или откройте объект.",
    ),
  ).toBeInTheDocument();
});

test("клавиши: стрелка выбирает, Enter открывает, Esc снимает; aria-live говорит, что выбрано", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<Sky centerRef={A3} height={340} />, `/atom/${A3}`);
  const sky = await screen.findByRole("application");
  await screen.findByRole("button", { name: /звезда/, pressed: false }).catch(() => null);
  sky.focus();
  await user.keyboard("{ArrowRight}");
  await waitFor(() =>
    expect(
      screen.getByText(/Выбрано: .*«Погрешность влажности В-2: ±2 %», ждёт решения/),
    ).toBeInTheDocument(),
  );
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("region", { name: "Выбранная звезда" })).not.toBeInTheDocument();
  await user.keyboard("{ArrowRight}{Enter}");
  expect(decodeURIComponent(router.state.location.pathname)).toBe(`/atom/${A3}`);
});

test("фильтр приглушает, а не убирает", async () => {
  await renderWithApp(
    <Sky height={440} filter={{ families: new Set(["object"]), pendingOnly: false }} />,
    "/",
  );
  const a3 = await screen.findByRole("button", { name: "звезда Погрешность влажности В-2: ±2 %" });
  expect(a3).toHaveAttribute("data-dim", "true");
  expect(screen.getByRole("button", { name: "звезда Датчик влажности В-2" })).not.toHaveAttribute("data-dim");
});

test("событие «запись создана» добавляет звезду и выбирает её", async () => {
  await renderWithApp(<Sky centerRef={E3} height={440} />, `/entity/${E3}`);
  await screen.findByRole("application", { name: /19 звёзд/ });
  skyBus.emit({
    star: {
      id: "atm:new",
      label: "Новая заметка",
      kind: "note",
      family: "work",
      status: "draft",
      pending: false,
      object: false,
      degree: 1,
      depth: 1,
      r: 2.6,
    },
    links: [{ source: "atm:new", target: E3, rel: "about" }],
  });
  await waitFor(() => expect(screen.getByText(/Выбрано: .*«Новая заметка»/)).toBeInTheDocument());
});

test("пусто — словами", async () => {
  await renderWithApp(<Sky project="empty" height={440} />, "/");
  expect(await screen.findByText("В окрестности пока ничего нет.")).toBeInTheDocument();
});
