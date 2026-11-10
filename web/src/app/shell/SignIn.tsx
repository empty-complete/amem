import { Button } from "@heroui/react";
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { auth, useAuthNeeded } from "../../api/auth";

/** Вход в общую службу: служба ответила 401 — нужен токен владельца (amemo token create). Поверх интерфейса,
 * пока не войдёте; после входа запросы повторяются. */
export function SignIn() {
  const { t } = useTranslation();
  const needed = useAuthNeeded();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [remember, setRemember] = useState(false);
  // токен уже был и служба снова ответила 401 — значит, не подошёл (отозван или опечатка)
  const [rejected, setRejected] = useState(false);
  useEffect(() => {
    if (needed) input.current?.focus();
  }, [needed]);
  if (!needed) return null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setRejected(true);
    auth.set(value, remember);
    setValue("");
    void qc.invalidateQueries();
  };
  return (
    <div className="signin" role="dialog" aria-modal="true" aria-labelledby="signin-title">
      <form className="signin__box" onSubmit={submit}>
        <h1 id="signin-title" className="title">
          {t("signin.title")}
        </h1>
        <p className="muted">{t("signin.why")}</p>
        {rejected && (
          <p className="fielderr" role="alert">
            {t("signin.rejected")}
          </p>
        )}
        <label className="fl">
          <span>{t("signin.token")}</span>
          <input
            ref={input}
            className="fld"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label className="chk">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          {t("signin.remember")}
        </label>
        <Button type="submit" className="pillbtn" isDisabled={!value.trim()}>
          {t("signin.enter")}
        </Button>
      </form>
    </div>
  );
}
