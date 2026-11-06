/** Подсветка слов запроса во фрагменте выдачи (без учёта регистра, по словам от 3 букв). */
export function Highlight({ text, query }: { text: string; query: string }) {
  const words = query
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w.length >= 3)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return <>{text}</>;
  const re = new RegExp(`(${words.join("|")})`, "gi");
  const parts = text.split(re);
  let at = 0;
  return (
    <>
      {parts.map((p, i) => {
        const key = `${at}:${p.length}`;
        at += p.length;
        return i % 2 === 1 ? <mark key={key}>{p}</mark> : <span key={key}>{p}</span>;
      })}
    </>
  );
}
