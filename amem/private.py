"""Метка <private> (спецификация подпроекта 4, разд. 6.4): скрытое вырезается до поиска, журнала и записи.

strip(text) убирает всё между <private> и </private> вместе с метками. Незакрытая метка скрывает текст до конца:
лучше потерять хвост, чем записать то, что человек просил не сохранять. Метки — без учёта регистра, с пробелами
и переводами строк внутри угловых скобок («< private >», «</ private >»): набранная небрежно метка тоже скрывает.
Вложенная <private> не закрывается первой же </private>, поэтому скрытое внутри неё тоже не выходит наружу.
Одиночная </private> без открывающей — обычный текст.

secret_like(text) — виды известных форм секретов в тексте (ключи API, токены, PEM, пароль в строке подключения):
submit предупреждает о них (secret_like в warnings), не вырезая — страховка к забытой метке <private>.
"""
from __future__ import annotations

import re

# захватывающие квантификаторы (*+, Python 3.11+): пробелы после «<» не перебираются заново, и «<» с длинным
# хвостом пробелов или переводов строк разбирается за линейное время, а не за квадратичное
_TAG = re.compile(r"<\s*+(/?)\s*+private\s*+>", re.IGNORECASE)


def marked(text: str) -> bool:
    """Есть ли в тексте метка <private> или </private> (в любом регистре, с пробелами) — для имён полей: скрытое
    в имени поля не вырезать, не сломав тело, поэтому такое имя отвергается целиком."""
    return isinstance(text, str) and _TAG.search(text) is not None


def strip(text: str) -> str:
    """Текст без частей в <private>…</private>; остальное — как было, пробелы вокруг не сжимаются."""
    if not isinstance(text, str):
        raise TypeError(f"private.strip: нужна строка, получено {type(text).__name__}")
    kept, depth, start = [], 0, 0
    for tag in _TAG.finditer(text):
        closing = tag.group(1) == "/"
        if depth == 0:
            if closing:
                continue                      # закрывающая без открывающей — часть текста
            kept.append(text[start:tag.start()])
            depth = 1
        elif closing:
            depth -= 1
            if depth == 0:
                start = tag.end()
        else:
            depth += 1
    if depth == 0:
        kept.append(text[start:])
    return "".join(kept)


# --- следы секретов (разд. 6.6) ---
#
# <private> — явная метка, её можно забыть. secret_like находит в тексте известные формы секретов, чтобы submit
# предупредил (secret_like в warnings), а не отклонил: это страховка, а не граница безопасности. Список нарочно
# консервативный — только формы с характерной приставкой или разметкой; марки и обозначения (ВН-45, КБ-14), хэши
# (sha256:…), UUID и адреса без пароля не срабатывают. Само значение наружу не отдаётся — только вид.
SECRETS: dict[str, re.Pattern] = {
    "aws_access_key": re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "github_token": re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    "api_key": re.compile(r"(?<![A-Za-z0-9_-])sk-(?:ant-|proj-|live-)?[A-Za-z0-9_-]{20,}"),
    "slack_token": re.compile(r"(?<![A-Za-z0-9_-])xox[abprs]-[A-Za-z0-9-]{10,}"),
    "google_api_key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"),
    "stripe_key": re.compile(r"(?<![A-Za-z0-9_])[rs]k_live_[0-9A-Za-z]{20,}"),
    "amem_token": re.compile(r"(?<![A-Za-z0-9_-])amem_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    "jwt": re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{16,}"),
    # строка подключения с паролем: схема://пользователь:пароль@хост
    "url_password": re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{1,20}://"
                               r"[^\s:/@<>\"']+:[^\s/@<>\"']+@[^\s/@]"),
    # пароль присвоением: password=…, пароль: …; значение проверяет _password_value
    "password": re.compile(r"(?i)(?<![\w-])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|пароль)"
                           r"[\"']?\s*[:=]\s*[\"']?(?P<value>[^\s\"'<>,;]{6,})"),
}
# значение после password=/пароль: — не секрет, если это заглушка (***, xxx, ${…}, <…>, %(…)s), путь (/…, ~/…, ./…),
# обращение к окружению или переменной (os.environ, getenv, process.env, ENV[…]) или обычное слово: без цифр
# и знаков пароля («обязателен», «настраивается», «стеклопакет»)
_PLACEHOLDER = re.compile(r"[*xх.•_-]+|[$%{<].*", re.IGNORECASE)
_CODE_REF = re.compile(r"environ|getenv|process\.env|env\[|secrets?\.|settings\.|config\.|\(", re.IGNORECASE)
_PASSWORD_MARK = re.compile(r"[0-9!@#^&*+=?|]")


def _password_value(value: str) -> bool:
    if _PLACEHOLDER.fullmatch(value) or value.startswith(("/", "~", "./", "../")) or _CODE_REF.search(value):
        return False
    return _PASSWORD_MARK.search(value) is not None


def secret_like(text: str) -> list[str]:
    """Виды секретов, похожих на найденные в тексте (по порядку SECRETS, без повторов); пусто — ничего похожего."""
    if not isinstance(text, str):
        raise TypeError(f"private.secret_like: нужна строка, получено {type(text).__name__}")
    found = []
    for name, pattern in SECRETS.items():
        if name == "password":
            hit = any(_password_value(m["value"]) for m in pattern.finditer(text))
        else:
            hit = pattern.search(text) is not None
        if hit:
            found.append(name)
    return found
