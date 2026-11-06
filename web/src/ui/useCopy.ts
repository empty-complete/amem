import { useCallback, useEffect, useRef, useState } from "react";

/** Копирование в буфер с ответом словами для aria-live; без доступа к буферу — честная ошибка. */
export function useCopy(failed: string) {
  const [message, setMessage] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = useCallback(
    async (text: string, ok: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setMessage(ok);
      } catch {
        setMessage(failed);
      }
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setMessage(""), 2400);
    },
    [failed],
  );
  return { copy, message };
}
