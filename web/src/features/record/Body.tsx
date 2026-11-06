import { useRouter } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { renderMarkdown } from "./markdown";

export type WikiTarget =
  | { to: "/atom/$ref" | "/entity/$ref"; params: { ref: string } }
  | { to: "/search"; search: { q: string } };

/** Тело записи. Markdown рендерится в очищенный DOM-фрагмент и вставляется через ref; [[ссылки]] ведут роутером. */
export function Body({ text, target }: { text: string; target: (label: string) => WikiTarget }) {
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const targetRef = useRef(target);
  targetRef.current = target;

  useEffect(() => {
    let live = true;
    renderMarkdown(text, (label) => router.buildLocation(target(label) as never).href).then((frag) => {
      if (live) ref.current?.replaceChildren(frag);
    });
    return () => {
      live = false;
    };
  }, [text, router, target]);

  const onClick = (e: React.MouseEvent) => {
    const a = (e.target as HTMLElement).closest("a.wiki");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    router.navigate(targetRef.current(a.textContent ?? "") as never);
  };

  // biome-ignore lint/a11y/noStaticElementInteractions: клик ловится делегированием от настоящих ссылок <a> внутри тела
  // biome-ignore lint/a11y/useKeyWithClickEvents: ссылки внутри — обычные <a href>, клавиатура работает по ним
  return <div ref={ref} className="prose" onClick={onClick} />;
}
