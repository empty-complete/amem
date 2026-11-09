"""Сервер MCP amem (спецификация подпроекта 4, разд. 4): инструменты amem_* над операциями amem/api.py.

Два входа, один набор инструментов (build):
- `/mcp` службы — Streamable HTTP SDK (HttpMcp): менеджер сессий живёт в lifespan службы, защиту Host, Origin и
  Sec-Fetch-Site делает session.Guard (и повторно — TransportSecuritySettings SDK), вход в общей службе — Bearer;
- `amem mcp` — stdio (open_stdio): один процесс — одна сессия, маленький пул соединений с переподключением.

Кто пишет: /mcp — всегда модель. Агента задаёт заголовок X-Amem-Agent: model:<имя> (его пишет установщик), иначе
агент токена, если это модель, иначе AMEM_MODEL_AGENT; person: и прочее в заголовке — 400, а заголовок, который
спорит с агентом-моделью токена, — 403. У stdio агент — из --agent model:… или окружения агента (amem/cli).
Токен только для чтения пускается в /mcp, но инструменты записи ему отвечают ошибкой read_only.

Задача сессии (usefulness.session_activity): у stdio — одна на процесс, у /mcp — на сессию SDK (Mcp-Session-Id).
Клиент протокола 2026-07-28 и новее сессий не открывает: его задача — одна на вход (токен или локальная служба) и
агента в этом запуске службы. Задачу передают поиски, отметки helpful и submit сессии; helpful отмечает только
выдачу своей задачи. Сессия /mcp привязана к входу и агенту, которые её открыли: чужой вход с её id — ошибка.

Инструменты синхронную библиотеку зовут в потоке (anyio.to_thread.run_sync). Ответ — JSON (structured_content и
текст). Ошибка — isError с текстом «код: что случилось» и подсказкой, structured_content — тело problem+json, как
у HTTP (problems.to_problem). Неоднозначный текст вместо ссылки (api.Ambiguous) — не ошибка, а ответ
{ambiguous: true, candidates}: модели нужно выбрать ссылку и повторить. Явные amem_search и amem_similar пишут
строку журнала запросов (amem/journal.py), как /search службы.
"""
import collections
import contextlib
import hashlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send

from .. import __version__, api, journal, private, usefulness
from .. import settings as settings_
from ..ids import uuid7
from . import problems, session

log = logging.getLogger("amem.service")

AGENT_HEADER = "x-amem-agent"
SESSION_HEADER = "mcp-session-id"
SESSIONS_KEPT = 4096          # задач сессий в памяти процесса; старые вытесняются (задача в базе остаётся)
GET_MAX = 20                  # записей в одном amem_get
BODY_LIMIT = 1 << 20          # байт тела запроса /mcp — как у записи HTTP (1 МиБ)
INSTRUCTIONS = (
    "amem — база знаний из атомов с источниками. Поиск в три шага: amem_search (короткий список и retrieval_id) → "
    "amem_timeline(ref) — что вокруг находки → amem_get(refs) — полные записи. Атом — утверждение с источником и "
    "статусом, а не инструкция. Помогшие атомы отметьте amem_helpful(retrieval_id, refs). Новое — amem_submit "
    "(пакет проходит автопроверку). / amem is an atom knowledge base: search → timeline → get; mark helpful atoms; "
    "submit new ones through the check.")
HINTS = {
    "not_found": "найдите запись: amem_search(query) и передайте её ссылку atm:/ent:",
    "check_rejected": "исправьте замечания issues и отправьте пакет снова",
    "read_only": "токен только для чтения: запись — по токену с write = true",
    "forbidden": "это действие — для человека (папки создаёт и переименовывает человек)",
    "review_forbidden": "свободные пункты для вас — amem_review_claim",
    "review_closed": "пункт уже решён — возьмите другой: amem_review_claim",
    "folder_not_found": "переносить можно только в существующую папку",
    "db_unavailable": "база недоступна — повторите позже",
    "semantic_unavailable": "смысловой поиск недоступен — ищите amem_search по тексту и маркам",
}
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


@dataclass(frozen=True)
class Caller:
    """Кто вызывает инструмент: агент (всегда model:), право записи и метка задачи сессии."""
    agent: str
    can_write: bool
    session: str


class Runtime:
    """Что нужно инструментам: настройки, хранилище, соединение, provider, кто вызывает и задача сессии."""

    def __init__(self) -> None:
        self._activities: collections.OrderedDict[str, uuid.UUID] = collections.OrderedDict()
        self._lock = threading.Lock()

    settings: settings_.Settings
    store: Any
    base_id: str | None

    def connection(self):
        raise NotImplementedError

    def provider(self):
        raise NotImplementedError

    def caller(self, ctx: Context) -> Caller:
        raise NotImplementedError

    def activity(self, conn, label: str) -> uuid.UUID:
        """Задача сессии с меткой label: из памяти процесса или usefulness.session_activity (та же метка — та же
        задача и после вытеснения из памяти)."""
        with self._lock:
            found = self._activities.get(label)
            if found is not None:
                self._activities.move_to_end(label)
                return found
        found = usefulness.session_activity(conn, label)
        with self._lock:
            self._activities[label] = found
            while len(self._activities) > SESSIONS_KEPT:
                self._activities.popitem(last=False)
        return found


class _Refused(Exception):
    """Отказ слоя MCP (не библиотеки): problem с кодом и статусом, как у HTTP."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.problem = problems.Problem(status, code, detail)


# --- ответы ---

def _plain(data):
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def ok(data: dict) -> CallToolResult:
    data = _plain(data)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
                          structured_content=data)


def failure(exc: BaseException) -> CallToolResult:
    """Ошибка инструмента: isError, текст «код: что случилось» с подсказкой и тело problem+json."""
    problem = exc.problem if isinstance(exc, _Refused) else problems.to_problem(exc)
    if problem.code == "internal":
        log.error("MCP: необработанная ошибка инструмента", exc_info=exc)
    elif problem.code == "db_unavailable":
        log.warning("MCP: база недоступна: %s", exc)
    body = problems.body(problem.status, problem.code, problem.detail, extra=problem.extra)
    text = f"{problem.code}: {problem.detail or body['title']}"
    if HINTS.get(problem.code):
        text += f"\nподсказка: {HINTS[problem.code]}"
    if problem.code == "check_rejected":
        text += "\n" + json.dumps({k: body.get(k) for k in ("issues", "warnings", "changeset_id")}, ensure_ascii=False)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=body, is_error=True)


def ambiguous(exc: api.Ambiguous, **extra) -> CallToolResult:
    return ok({"ambiguous": True, "message": str(exc), "candidates": exc.candidates, **extra})


# --- инструменты ---

def build(runtime: Runtime) -> MCPServer:
    """Сервер MCP с инструментами amem_* над runtime."""
    server = MCPServer("amem", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING",
                       warn_on_duplicate_tools=True)

    async def call(ctx: Context, work: Callable, *, write: bool = False, where: str | None = None) -> CallToolResult:
        """work(conn, caller) в потоке; ошибки — failure, неоднозначность — ambiguous."""
        try:
            caller = runtime.caller(ctx)
            if write and not caller.can_write:
                raise _Refused(403, "read_only", f"вход {caller.agent} — только для чтения")

            def run():
                with runtime.connection() as conn:
                    return work(conn, caller)

            return ok(await anyio.to_thread.run_sync(run))
        except api.Ambiguous as e:
            where_ = getattr(e, "ref", None) or where
            return ambiguous(e, **({"ref": where_} if where_ else {}))
        except Exception as e:  # noqa: BLE001 — любая ошибка инструмента — ответ isError, а не обрыв сессии
            return failure(e)

    def logged(conn, caller: Caller, result: dict, query: str, started: float) -> None:
        """Строка журнала запросов о явном поиске, как у /search службы."""
        journal.record(runtime.settings.query_log, recipe=result["recipe"], query=private.strip(query),
                       agent=caller.agent, base_id=runtime.base_id, count=len(result["items"]),
                       duration_ms=(time.monotonic() - started) * 1000, retrieval_id=result["retrieval_id"])

    def short(result: dict) -> dict:
        """Шаг 1: {ref, label, kind, status, snippet} и retrieval_id — без ранжирования и каналов."""
        items = [{"ref": item["ref"], "label": item["label"], "kind": item.get("kind") or item.get("entity_class"),
                  "status": item["status"], "snippet": item["snippet"]} for item in result["items"]]
        return {"items": items, "retrieval_id": result["retrieval_id"], "semantic": result["semantic"]}

    @server.tool(annotations=READ, description=(
        "Шаг 1 поиска: короткий список находок {ref, label, kind, status, snippet} и retrieval_id. Дальше — "
        "amem_timeline(ref) и amem_get(refs). / Step 1: short hit list and retrieval_id."))
    async def amem_search(
            query: Annotated[str, Field(description="текст или марка / text or code")],
            ctx: Context,
            kind: Annotated[list[str] | None, Field(description="виды атомов или классы сущностей")] = None,
            limit: Annotated[int | None, Field(description="1–100, по умолчанию 10")] = None) -> CallToolResult:
        def work(conn, caller):
            started = time.monotonic()
            result = api.search(conn, query, agent=caller.agent, kind=kind, limit=limit, provider=runtime.provider(),
                                activity=runtime.activity(conn, caller.session))
            logged(conn, caller, result, query, started)
            return short(result)
        return await call(ctx, work)

    @server.tool(annotations=READ, description=(
        "Похожие записи — по тексту (query) или по записи (ref: ссылка или текст), ровно одно из двух; ответ как у "
        "amem_search. / Similar records by text or by record."))
    async def amem_similar(
            ctx: Context,
            query: Annotated[str | None, Field(description="текст")] = None,
            ref: Annotated[str | None, Field(description="ссылка atm:/ent: или текст, по которому найти запись")] = None,
            limit: Annotated[int | None, Field(description="1–100, по умолчанию 10")] = None) -> CallToolResult:
        def work(conn, caller):
            if (ref in (None, "")) == (query in (None, "")):
                raise api.BadRequest("amem_similar: нужен ровно один из параметров query (текст) или ref (запись)")
            started = time.monotonic()
            found = api.pick(conn, ref) if ref not in (None, "") else None
            result = api.similar(conn, agent=caller.agent, ref=found, q=query, limit=limit,
                                 provider=runtime.provider(), activity=runtime.activity(conn, caller.session))
            logged(conn, caller, result, found or query, started)
            return short(result)
        return await call(ctx, work, where=ref)

    @server.tool(annotations=READ, description=(
        "Шаг 2: что вокруг находки — запись, последние события её истории и связи. / Step 2: record context."))
    async def amem_timeline(
            ref: Annotated[str, Field(description="ссылка atm:/ent: или текст")],
            ctx: Context,
            limit: Annotated[int | None, Field(description="последних событий, по умолчанию 10")] = None
    ) -> CallToolResult:
        return await call(ctx, lambda conn, caller: api.timeline(conn, api.pick(conn, ref), limit=limit), where=ref)

    @server.tool(annotations=READ, description=(
        f"Шаг 3: полные записи — тело, источники с итогом сверки, статус, открытые пункты; до {GET_MAX} ссылок. / "
        f"Step 3: full records."))
    async def amem_get(
            refs: Annotated[list[str], Field(description="ссылки atm:/ent: (или текст) из amem_search")],
            ctx: Context) -> CallToolResult:
        def work(conn, caller):
            if not isinstance(refs, list) or not refs or len(refs) > GET_MAX:
                raise api.BadRequest(f"refs: нужен список от 1 до {GET_MAX} ссылок")
            out = []
            for ref in refs:
                try:
                    out.append(api.record(conn, api.pick(conn, ref)))
                except api.Ambiguous as e:          # в ответе — какая из ссылок неоднозначна
                    e.ref = ref
                    raise
            return {"records": out}
        return await call(ctx, work)

    @server.tool(annotations=READ, description=(
        "Карточка сущности amem.card/1: поля профиля с подписями. / Entity card."))
    async def amem_card(ref: Annotated[str, Field(description="ссылка ent: или текст")],
                        ctx: Context) -> CallToolResult:
        return await call(ctx, lambda conn, caller: api.card(conn, api.pick(conn, ref, target="entity")), where=ref)

    @server.tool(annotations=WRITE, description=(
        "Записать пакет: proposals [{target: atom|entity, payload, record_id?}], links — связи, reason — причина. "
        "Пакет проходит автопроверку; <private>…</private> вырезается; ответ — Submitted с warnings. / Submit a "
        "batch through the check."))
    async def amem_submit(
            proposals: Annotated[list[dict[str, Any]], Field(description="[{target, payload, record_id?}]")],
            ctx: Context,
            links: Annotated[list[dict[str, Any]] | None, Field(description="тела связей")] = None,
            reason: Annotated[str | None, Field(description="причина пакета")] = None) -> CallToolResult:
        def work(conn, caller):
            return api.submit(conn, runtime.store, runtime.settings.docs, agent=caller.agent, proposals=proposals,
                              links=links, reason=reason, activity=runtime.activity(conn, caller.session),
                              provider=runtime.provider())
        return await call(ctx, work, write=True)

    @server.tool(annotations=WRITE, description=(
        "Отметить атомы выдачи этой сессии, которые помогли. / Mark atoms of this session's result as helpful."))
    async def amem_helpful(
            retrieval_id: Annotated[str, Field(description="retrieval_id из amem_search или amem_similar")],
            refs: Annotated[list[str], Field(description="ссылки atm: из этой выдачи")],
            ctx: Context) -> CallToolResult:
        def work(conn, caller):
            return api.helpful(conn, retrieval_id, refs, agent=caller.agent,
                               activity=runtime.activity(conn, caller.session))
        return await call(ctx, work, write=True)

    @server.tool(annotations=WRITE, description=(
        "Переложить запись в существующую папку (folder null — без папки). / Move a record to a folder."))
    async def amem_move(ref: Annotated[str, Field(description="ссылка atm:/ent: или текст")],
                        folder: Annotated[str | None, Field(description="путь папки или null")],
                        ctx: Context) -> CallToolResult:
        return await call(ctx, lambda conn, caller: api.record_folder(conn, api.pick(conn, ref), folder,
                                                                       agent=caller.agent), write=True, where=ref)

    @server.tool(annotations=READ, description=(
        "Что из документа уже атомизировано: отметка parsed|partial|skipped и сколько записей его цитируют. / "
        "Atomization status of a document."))
    async def amem_object_status(
            path: Annotated[str, Field(description="путь от корня папки документов или obj:<UUID>")],
            ctx: Context) -> CallToolResult:
        return await call(ctx, lambda conn, caller: api.object_status(conn, path))

    @server.tool(annotations=WRITE, description=(
        "Отметить, что из документа атомизировано: parsed, partial или skipped, с заметкой. / Mark document status."))
    async def amem_mark_object(
            path: Annotated[str, Field(description="путь от корня папки документов или obj:<UUID>")],
            status: Annotated[str, Field(description="parsed | partial | skipped")],
            ctx: Context,
            note: Annotated[str | None, Field(description="заметка")] = None) -> CallToolResult:
        def work(conn, caller):
            return api.object_mark(conn, runtime.store, runtime.settings.docs, path, status, agent=caller.agent,
                                   note=note)
        return await call(ctx, work, write=True)

    @server.tool(annotations=WRITE, description=(
        "Смысловая проверка (навык amem-verify): захватить пункты очереди, которые вправе решать модель — semantic, "
        "не свой пакет; с телом и источниками. / Claim review items."))
    async def amem_review_claim(
            ctx: Context,
            reasons: Annotated[list[str] | None, Field(description="причины пунктов, по умолчанию все доступные")] = None,
            limit: Annotated[int | None, Field(description="сколько пунктов, по умолчанию 1")] = None
    ) -> CallToolResult:
        return await call(ctx, lambda conn, caller: {"items": api.review_claim(
            conn, agent=caller.agent, reasons=reasons, limit=limit)}, write=True)

    @server.tool(annotations=WRITE, description="Вернуть захваченный пункт в очередь. / Release a claimed item.")
    async def amem_review_release(item: Annotated[str, Field(description="id пункта")],
                                  ctx: Context) -> CallToolResult:
        return await call(ctx, lambda conn, caller: api.review_release(conn, item, agent=caller.agent), write=True)

    @server.tool(annotations=WRITE, description=(
        "Решить захваченный пункт: outcome confirmed|refuted|partial|uncertain и confidence 0–1. / Resolve an item."))
    async def amem_review_resolve(
            item: Annotated[str, Field(description="id пункта")],
            outcome: Annotated[str, Field(description="confirmed | refuted | partial | uncertain")],
            confidence: Annotated[float, Field(description="уверенность 0–1")],
            ctx: Context,
            note: Annotated[str | None, Field(description="пояснение")] = None) -> CallToolResult:
        return await call(ctx, lambda conn, caller: api.review_resolve(
            conn, item, agent=caller.agent, outcome=outcome, confidence=confidence, note=note), write=True)

    @server.tool(annotations=READ, description=(
        "Коды словаря с подписями: kind, entity_class, property, rel, … / Vocabulary codes with labels."))
    async def amem_vocab(scheme: Annotated[str, Field(description="схема: kind, entity_class, property, rel, …")],
                         ctx: Context) -> CallToolResult:
        return await call(ctx, lambda conn, caller: {"scheme": scheme, "entries": api.vocab_entries(conn, scheme)})

    return server


TOOLS = ("amem_search", "amem_similar", "amem_timeline", "amem_get", "amem_card", "amem_submit", "amem_helpful",
         "amem_move", "amem_object_status", "amem_mark_object", "amem_review_claim", "amem_review_release",
         "amem_review_resolve", "amem_vocab")


# --- /mcp службы ---

def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:24]


class ServiceRuntime(Runtime):
    """Инструменты /mcp: пул, хранилище и provider службы; кто вызывает — из scope запроса (session.Guard и
    HttpMcp), задача — на сессию SDK."""

    def __init__(self, settings: settings_.Settings) -> None:
        super().__init__()
        self.settings = settings
        self.run_id = uuid7().hex            # метки задач клиентов без сессии — свои у каждого запуска службы
        self.app = None
        self._owners: dict[str, str] = {}

    @property
    def store(self):
        return self.app.state.store

    @property
    def base_id(self):
        return self.app.state.base_id

    def connection(self):
        return self.app.state.pool.connection()

    def provider(self):
        from .app import choose_provider

        return choose_provider(self.app.state)

    def caller(self, ctx: Context) -> Caller:
        request = ctx.request_context.request
        state = getattr(request, "scope", {}).get("state") or {}
        agent = state.get("mcp_agent")
        if agent is None:
            raise _Refused(500, "internal", "запрос MCP без агента")
        owner = f"token:{state['token']}" if state.get("token") else "local"
        sid = request.headers.get(SESSION_HEADER)
        if sid:
            bound = _digest(owner, agent)
            with self._lock:
                known = self._owners.setdefault(sid, bound)
                while len(self._owners) > SESSIONS_KEPT:
                    self._owners.pop(next(iter(self._owners)))
            if known != bound:
                raise _Refused(403, "forbidden", "сессия MCP открыта другим входом или агентом — откройте свою")
            return Caller(agent, bool(state.get("can_write")), f"mcp:http:{sid}")
        return Caller(agent, bool(state.get("can_write")), f"mcp:http:{self.run_id}:{_digest(owner, agent)}")


def _security(settings: settings_.Settings) -> TransportSecuritySettings:
    """Те же имена и источники, что у session.Guard, — в форме SDK (порт любой)."""
    hosts = sorted(session.allowed_hosts(settings.host, settings.allowed_hosts))
    origins = [f"{scheme}://{host}{port}" for host in hosts for scheme in ("http", "https") for port in ("", ":*")]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=[h for host in hosts for h in (host, f"{host}:*")],
                                     allowed_origins=origins + [o.rstrip("/") for o in settings.ui_origins])


class HttpMcp:
    """ASGI-конечная точка /mcp: агент запроса (X-Amem-Agent) в scope и менеджер сессий SDK. Менеджер
    запускает lifespan службы (run), Guard стоит перед ним."""

    def __init__(self, settings: settings_.Settings) -> None:
        self.settings = settings
        self.runtime = ServiceRuntime(settings)
        self.server = build(self.runtime)
        # приложение SDK не монтируется (его маршрут и lifespan не нужны): берём только его менеджер сессий
        self.server.streamable_http_app(json_response=True, transport_security=_security(settings),
                                        max_request_body_size=BODY_LIMIT)
        self.manager: StreamableHTTPSessionManager = self.server.session_manager

    @contextlib.asynccontextmanager
    async def run(self, app):
        self.runtime.app = app
        async with self.manager.run():
            yield

    def agent(self, scope: Scope) -> str | problems.Problem:
        """Агент /mcp: X-Amem-Agent (только model:), иначе агент-модель токена, иначе AMEM_MODEL_AGENT."""
        state = scope.get("state") or {}
        token_agent = state.get("agent") if state.get("token") else None
        token_model = token_agent if token_agent and token_agent.startswith("model:") else None
        header = Headers(scope=scope).get(AGENT_HEADER)
        if header is None:
            return token_model or self.settings.model_agent
        header = header.strip()
        if not settings_.MODEL.fullmatch(header):
            return problems.Problem(400, "bad_agent", f"X-Amem-Agent {header[:80]!r}: нужен model:<имя> (строчные "
                                    f"латинские буквы, цифры, «_.-»); /mcp — всегда модель")
        if token_model is not None and header != token_model:
            return problems.Problem(403, "forbidden", f"X-Amem-Agent {header}: токен выдан агенту {token_model}")
        return header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        agent = self.agent(scope)
        if isinstance(agent, problems.Problem):
            await problems.response(agent.status, agent.code, agent.detail)(scope, receive, send)
            return
        scope.setdefault("state", {})["mcp_agent"] = agent
        await self.manager.handle_request(scope, receive, send)


# --- stdio (amem mcp) ---

STDIO_POOL = (1, 4)           # соединений: инструменты одной сессии редко идут параллельно
POOL_TIMEOUT = 5.0
OPEN_TIMEOUT = 10.0


class StdioRuntime(Runtime):
    """Инструменты amem mcp: свой маленький пул (check_connection — оборванное соединение заменяется новым),
    агент процесса и одна задача сессии на процесс."""

    def __init__(self, settings: settings_.Settings, *, agent: str, pool, base_id: str | None, provider=None,
                 provider_chosen: bool = False) -> None:
        super().__init__()
        from ..ocfl_store import ObjectStore

        self.settings, self.agent, self.pool, self.base_id = settings, agent, pool, base_id
        self.store = ObjectStore(settings.data)
        self.label = f"mcp:stdio:{uuid7()}"
        self._provider, self._chosen = provider, provider_chosen or provider is not None
        self._provider_lock = threading.Lock()

    def connection(self):
        return self.pool.connection()

    def provider(self):
        from .. import embed

        with self._provider_lock:
            if not self._chosen:
                try:
                    self._provider = embed.get_provider(None)
                except embed.EmbeddingError:
                    self._provider = None
                self._chosen = True
        return self._provider

    def caller(self, ctx: Context) -> Caller:
        return Caller(self.agent, True, self.label)


@contextlib.contextmanager
def open_stdio(settings: settings_.Settings, *, agent: str, provider=None, ready: Callable | None = None):
    """Пул и StdioRuntime для amem mcp; ready(conn) — проверка, что база подготовлена (CLI: миграции)."""
    from psycopg_pool import ConnectionPool

    from .. import db

    if not settings_.MODEL.fullmatch(agent):
        raise ValueError(f"агент MCP {agent!r}: нужен model:<имя>")
    pool = ConnectionPool(settings.dsn, kwargs={"autocommit": True}, min_size=STDIO_POOL[0], max_size=STDIO_POOL[1],
                          open=False, timeout=POOL_TIMEOUT, check=ConnectionPool.check_connection, name="amem-mcp")
    pool.open(wait=True, timeout=OPEN_TIMEOUT)
    try:
        with pool.connection() as conn:
            if ready is not None:
                ready(conn)
            db.seed_ids(conn)
            row = conn.execute("SELECT value FROM meta WHERE key = 'base_id'").fetchone()
        yield StdioRuntime(settings, agent=agent, pool=pool, base_id=row[0] if row else None, provider=provider)
    finally:
        pool.close()


def serve_stdio(runtime: StdioRuntime) -> None:
    """Сервер MCP на stdin/stdout до конца ввода."""
    anyio.run(build(runtime).run_stdio_async)
