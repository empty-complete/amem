import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../test/render";
import type { Sky } from "../sky/model";
import { HomeSky } from "./HomeSky";

vi.mock("../sky/SkyCanvas", async () => {
  const { forwardRef } = await import("react");
  return {
    default: forwardRef(function Fake(p: { sky: Sky; dim: Set<string>; onSelect: (id: string) => void }) {
      return (
        <div>
          {p.sky.nodes.map((n) => (
            <button
              key={n.id}
              type="button"
              data-dim={p.dim.has(n.id) || undefined}
              onClick={() => p.onSelect(n.id)}
            >
              звезда {n.label}
            </button>
          ))}
        </div>
      );
    }),
  };
});

test("итог словами, фильтры приглушают, карточка выбранной звезды", async () => {
  const user = userEvent.setup();
  const { router } = await renderWithApp(<HomeSky pending={false} />, "/");
  expect(await screen.findByText("23 записи о 8 объектах, 3 ждут решения")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "звезда Датчик влажности В-2" }));
  const card = screen.getByRole("region", { name: "Выбранная звезда" });
  expect(card).toHaveTextContent("Датчик влажности В-2");
  await user.click(within(card).getByRole("button", { name: "Окрестность" }));
  expect((router.state.location.search as { center?: string }).center).toBe(
    "ent:0193b7c2-5e1a-7d40-9f2e-000000000003",
  );
});

test("фильтр «Объекты» из адреса приглушает записи", async () => {
  await renderWithApp(<HomeSky families="object" pending={false} />, "/?f=object");
  expect(
    await screen.findByRole("button", { name: "звезда Погрешность влажности В-2: ±2 %" }),
  ).toHaveAttribute("data-dim", "true");
  expect(screen.getByRole("button", { name: "Объекты" })).toHaveAttribute("aria-pressed", "true");
});

test("пустая база — строка и «Записать заметку»", async () => {
  await renderWithApp(<HomeSky pending={false} project="empty" />, "/");
  expect(await screen.findByText(/В базе пока ничего нет/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Записать заметку" })).toBeInTheDocument();
});
