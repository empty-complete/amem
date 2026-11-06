import { renderMarkdown } from "./markdown";

const html = async (src: string, resolve?: (l: string) => string) => {
  const host = document.createElement("div");
  host.replaceChildren(await renderMarkdown(src, resolve));
  return host.innerHTML;
};

test("HTML в тексте не исполняется и не попадает в DOM", async () => {
  const out = await html("<img src=x onerror=alert(1)> **жирно** [x](javascript:alert(1))");
  expect(out).not.toContain("<img");
  expect(out).not.toContain('href="javascript');
  expect(out).toContain("<strong>жирно</strong>");
});

test("[[ссылка]] — ссылка на запись по подписи", async () => {
  const out = await html(
    "см. [[Нужен ли обогрев В-2 зимой?]]",
    (l) => `/ui/search?q=${encodeURIComponent(l)}`,
  );
  expect(out).toMatch(/<a class="wiki" href="\/ui\/search\?q=[^"]+">Нужен ли обогрев В-2 зимой\?<\/a>/);
});

test("формулы: строчная и выключная через KaTeX", async () => {
  const out = await html("при $T = 2$ °C\n\n$$\nT_d = \\frac{b\\gamma}{a-\\gamma}\n$$\n\nдальше");
  expect(out).toContain('class="katex"');
  expect(out).toContain('class="katex-display"');
  expect(out).toContain("<p>дальше</p>");
});

test("деньги и диапазоны с $ не становятся формулой", async () => {
  expect(await html("цена 5$ и 10$")).not.toContain("katex");
});

test("цитата блоком получает класс источника", async () => {
  expect(await html("> цитата")).toContain('<blockquote class="quote">');
});
