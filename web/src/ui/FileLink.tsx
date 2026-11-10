import type { AnchorHTMLAttributes, ImgHTMLAttributes } from "react";
import { auth, openAuthed, useAuthedSrc } from "../api/auth";

/** Ссылка на файл API: без токена — обычная ссылка (cookie локальной службы); с токеном (общая служба) — по клику
 * запрос с заголовком, потом показ (PDF, картинки) или сохранение файлом (остальное — см. openAuthed). */
export function FileLink({ href, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return (
    <a
      href={href}
      {...rest}
      onClick={(e) => {
        if (!auth.token()) return;
        e.preventDefault();
        void openAuthed(href, { download: rest.download !== undefined });
      }}
    />
  );
}

/** Картинка из API: с токеном — через blob-адрес запроса с заголовком. */
export function AuthedImg({ src, alt, ...rest }: ImgHTMLAttributes<HTMLImageElement> & { src: string }) {
  const url = useAuthedSrc(src);
  return url ? <img src={url} alt={alt} {...rest} /> : null;
}
