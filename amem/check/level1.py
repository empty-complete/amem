"""Уровень 1 автопроверки — схема и шаблон (спецификация подпроекта 3, разд. 1.1, шаги 1–3, и разд. 3).

По порядку:
1. разбор — тело проверяет Pydantic в строгом режиме JSON (AtomPayload, EntityPayload, LinkPayload); каждая ошибка —
   отдельное замечание schema; тело, которое не разобралось, дальше не проверяется (Prepared.ok = False);
2. ссылки — @имена пачки, ключи и UUID записей базы: вид и код цели; у правки — статус записи;
3. коды словаря (kind, entity_class, rel, тип селектора с цепочкой refined_by), правила полей шаблонов, жёсткие
   правила величин (разд. 3.3), правила основания basis и уверенности confidence по агенту (спецификация 3c,
   разд. 2.1–2.2), концы связей (pairs) и правила связей шаблонов (allowed, required).

Правило поля со skip_if_set не применяется, если поле по этому пути у тела непусто (has_source: при basis источник
не обязателен).

Связи для правил шаблонов считаются вместе: связи пачки, поля тела, через которые выражается вид связи (via_field
понятия: about, derived_from), и — для required — действующие связи записи в базе. Симметричная связь исходит
из обоих концов. Уже записанные связи на allowed не перепроверяются: пакет отвечает за то, что предлагает.

База только читается, без блокировок: словари и шаблоны меняются редко, а статус правки, прочитанный здесь,
submit перечитывает под блокировкой в транзакции записи (разд. 1.1). Объекты источников (obj:) проверяет уровень 2.
Место замечания — метка записи (@имя, items[i], links[i]) и путь поля через «: »: «@a1: sources[0].selectors».
"""
from __future__ import annotations

import functools
import json
import re
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from .. import canon, model_v1, packs
from ..records import PREFIX, TARGET, RecordError, as_uuid
from . import templates, units
from .report import Report
from .templates import Rules

LEVEL = 1
MODELS = {"atom": model_v1.AtomPayload, "entity": model_v1.EntityPayload}
CODE_FIELD = {"atom": "kind", "entity": "entity_class"}       # схема понятий кода записи и столбец её таблицы
RETIRED = frozenset({"deprecated", "superseded"})
# величины и уточнения тела — у каждой проверяются жёсткие правила разд. 3.3
VALUES = {"atom": ("content.values[]", "content.values[].qualifiers[]", "qualifiers[]"), "entity": (),
          "link": ("qualifiers[]",)}
NAME = re.compile(r"@[a-z0-9_]+")
UUID7 = re.compile(canon.UUID7)
WHAT = {"atom": "атом", "entity": "сущность"}


@dataclass
class Prepared:
    label: str                     # @имя или items[i]
    target: str
    payload: dict                  # входное тело; уровень 2 заменит его разобранным
    record_id: uuid.UUID | None
    code: str | None               # kind / entity_class
    status: str | None             # статус существующей записи при чтении (не под блокировкой)
    rules: Rules | None
    ok: bool                       # тело разобралось — дальше идти можно


@dataclass
class Batch:
    items: list[Prepared]
    links: list[dict]
    refs: dict[str, tuple[str, str | None]]      # @имя → (target, код)
    templates: tuple[str, ...]                   # все применённые code@version


@dataclass(frozen=True)
class _Node:
    """Конец ссылки: вид и код записи; тождество — номер записи пачки или id записи базы."""
    target: str
    code: str | None
    identity: tuple


@dataclass(frozen=True)
class _Slot:
    """Место правила поля: правило и его шаблон, метка записи, точный путь, значение, тип поля по схеме."""
    rule: dict
    origin: str | None
    label: str
    where: str
    value: object
    range: str | None


@dataclass
class _Link:
    where: str
    rel: str
    src: _Node
    dst: _Node
    symmetric: bool


def check(conn, proposals: Sequence, links: Sequence[dict], report: Report, *, agent: str | None = None) -> Batch:
    """Уровень 1 над пачкой: замечания — в report, разобранная пачка — уровням 2–4. В базу ничего не пишет.

    proposals — check.Proposal (target, payload, record_id), links — тела связей LinkPayload. agent — кто пишет
    (model:…, person:…): от него зависят правила basis author и confidence; без agent они не применяются."""
    run = _Level1(conn, report, agent)
    for i, proposal in enumerate(proposals):
        run.prepare(i, proposal)
    for item in run.items:
        if item.ok:
            run.check_item(item)
    planned = [run.check_link(i, payload) for i, payload in enumerate(links)]
    run.link_rules([link for link in planned if link is not None])
    refs = {name: (run.items[i].target, run.items[i].code) for name, i in run.names.items()}
    return Batch(items=run.items, links=list(links), refs=refs, templates=tuple(run.applied))


class _Level1:
    def __init__(self, conn, report: Report, agent: str | None = None):
        self.conn, self.report, self.agent = conn, report, agent
        self.vocab: dict[str, dict[str, dict]] = {"kind": {}, "entity_class": {}, "rel": {}, "selector_type": {}}
        for scheme, code, data in conn.execute("SELECT scheme, code, data FROM concept WHERE scheme = ANY(%s)",
                                               (list(self.vocab),)).fetchall():
            self.vocab[scheme][code] = data
        self.active = templates.active(conn)
        self.items: list[Prepared] = []
        self.names: dict[str, int] = {}                     # @имя → номер записи пачки
        self.ids: dict[tuple[str, uuid.UUID], int] = {}     # (вид, id) правки → номер записи пачки
        self.found: dict[str, _Node | None] = {}            # ссылка на запись базы → её конец, на время пачки
        self.unresolved: set[str] = set()                   # места, где ссылка уже дала ref_unknown
        self.merged: dict[tuple[str, str], Rules] = {}
        self.applied: dict[str, None] = {}                  # code@version шаблонов записей и связей пачки по порядку
        # поля тела, через которые выражается вид связи: вид → поле (about, derived_from)
        self.via = {rel: data["via_field"] for rel, data in self.vocab["rel"].items() if data.get("via_field")}

    def add(self, severity: str, code: str, where: str, message: str, **details) -> None:
        self.report.add(LEVEL, severity, code, where, message, **details)

    def schema(self, where: str, loc: list, msg: str) -> None:
        self.add("violation", "schema", where, f"Не по схеме: {msg}", loc=loc, msg=msg)

    def rules(self, target: str, code: str, *, applied: bool = True) -> Rules:
        if (target, code) not in self.merged:
            self.merged[(target, code)] = templates.rules_for(self.active, target, code)
        rules = self.merged[(target, code)]
        if applied:
            self.applied.update(dict.fromkeys(rules.templates))
        return rules

    # --- разбор и ссылки ---

    def prepare(self, i: int, proposal) -> None:
        target, payload = proposal.target, proposal.payload
        ref = payload.get("ref") if isinstance(payload, dict) else None
        named = isinstance(ref, str) and NAME.fullmatch(ref) is not None
        label = ref if named and ref not in self.names else f"items[{i}]"
        item = Prepared(label, target, payload, None, None, None, None, False)
        self.items.append(item)
        if target not in MODELS:
            self.schema(f"{label}: target", [], f"неизвестный вид записи {target!r}: нужен atom или entity")
            return
        if named:
            if ref in self.names:
                self.schema(f"{label}: ref", ["ref"], f"{ref} уже есть в пачке: у каждой записи своё @имя")
            else:
                self.names[ref] = i
        code = payload.get(CODE_FIELD[target]) if isinstance(payload, dict) else None
        item.code = code if isinstance(code, str) else None
        if proposal.record_id is not None:
            self.existing(i, item, proposal.record_id)
        item.ok = self.parse(MODELS[target], payload, label)
        if item.ok:
            item.rules = self.rules(target, item.code)

    def existing(self, i: int, item: Prepared, record_id) -> None:
        """Правка: запись должна быть в базе; статус выведенной из оборота записи правку запрещает."""
        try:
            item.record_id = as_uuid(record_id, "record_id")
        except RecordError as e:
            self.schema(f"{item.label}: record_id", ["record_id"], str(e))
            return
        t = item.target
        row = self.conn.execute(f"SELECT status FROM {t} WHERE id = %s", (item.record_id,)).fetchone()
        if row is None:
            ref = f"{PREFIX[t]}:{item.record_id}"
            self.add("violation", "ref_unknown", f"{item.label}: record_id", f"{ref}: такой записи нет", ref=ref)
            return
        item.status = row[0]
        first = self.ids.get((t, item.record_id))
        if first is not None:                  # две ревизии одной записи в пачке: какая из них текущая — неясно
            self.schema(f"{item.label}: record_id", ["record_id"],
                        f"запись уже правится в этой пачке: {self.items[first].label}")
            return
        self.ids[(t, item.record_id)] = i
        if item.status in RETIRED:
            self.add("violation", "retired_record", item.label,
                     f"Запись выведена из оборота (статус {item.status}): сначала верните ей статус",
                     status=item.status)

    def parse(self, model, payload, label: str) -> bool:
        try:
            text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as e:
            self.schema(label, [], f"тело — не JSON: {e}")
            return False
        try:
            model.model_validate_json(text, strict=True)
        except ValidationError as e:
            for err in e.errors():
                loc = _path(err["loc"])
                self.schema(f"{label}: {loc}" if loc else label, list(err["loc"]), err["msg"])
            return False
        return True

    def node(self, ref) -> _Node | None:
        """@имя пачки, ключ или UUID → конец ссылки; нет такой записи — None."""
        if not isinstance(ref, str):
            return None
        if ref.startswith("@"):
            i = self.names.get(ref)
            return None if i is None else _Node(self.items[i].target, self.items[i].code, ("item", i))
        if ref not in self.found:
            self.found[ref] = self._lookup(ref)
        return self.found[ref]

    def _lookup(self, ref: str) -> _Node | None:
        prefix, _, rest = ref.partition(":")
        target = TARGET.get(prefix)
        if target is None:
            return None
        by = "id" if UUID7.fullmatch(rest) else "key"
        row = self.conn.execute(f"SELECT id, {CODE_FIELD[target]} FROM {target} WHERE {by} = %s", (rest,)).fetchone()
        return None if row is None else self._db_node(target, row[0], row[1])

    def _db_node(self, target: str, record_id: uuid.UUID, code: str | None) -> _Node:
        """Запись базы, которую правит эта же пачка, — это запись пачки: её код — из нового тела."""
        i = self.ids.get((target, record_id))
        if i is not None:
            return _Node(target, self.items[i].code, ("item", i))
        return _Node(target, code, ("db", target, record_id))

    def resolve(self, ref: str, where: str, expected: str | None = None) -> _Node | None:
        """Конец ссылки или ref_unknown: записи нет или она другого вида, чем ждёт поле."""
        node = self.node(ref)
        if node is not None and (expected is None or node.target == expected):
            return node
        if node is not None:
            problem = f"это {WHAT[node.target]}, а здесь нужна ссылка на {WHAT[expected]}"
        elif ref.startswith("@"):
            problem = "в пачке нет записи с таким ref"
        elif UUID7.fullmatch(ref.partition(":")[2]):
            problem = "такой записи нет"
        else:
            problem = f"нет записи с ключом {ref.partition(':')[2]}"
        self.add("violation", "ref_unknown", where, f"{ref}: {problem}", ref=ref)
        self.unresolved.add(where)
        return None

    # --- записи ---

    def check_item(self, item: Prepared) -> None:
        body, label, target = item.payload, item.label, item.target
        scheme = CODE_FIELD[target]
        if item.code not in self.vocab[scheme]:
            self.add("violation", "unknown_code", f"{label}: {scheme}",
                     f"{scheme} {item.code!r} — кода нет в загруженных пакетах", scheme=scheme, value=item.code)
        for where, selector in canon.values_at(body, "sources[].selectors[]"):
            self.selector_codes(label, where, selector)
        for path, prefix in canon.REF_FIELDS[target].items():
            if prefix != "obj":
                for where, ref in canon.values_at(body, path):
                    self.resolve(ref, f"{label}: {where}", TARGET[prefix])
        self.field_rules(label, target, body, item.rules)
        self.hard_rules(label, target, body)
        if target == "atom":
            self.basis_rules(label, body)

    def selector_codes(self, label: str, where: str, selector) -> None:
        while isinstance(selector, dict):
            code = selector.get("type")
            if code not in self.vocab["selector_type"]:
                self.add("violation", "unknown_code", f"{label}: {where}.type",
                         f"тип селектора {code!r} — кода нет в загруженных пакетах", scheme="selector_type", value=code)
            selector, where = selector.get("refined_by"), f"{where}.refined_by"

    def field_rules(self, label: str, target: str, body: dict, rules: Rules) -> None:
        """Правила полей FieldRule — по каждому месту пути; важность — из правила, по умолчанию violation."""
        for path, rule in rules.fields.items():
            if rule.get("skip_if_set") and _is_set(body, rule["skip_if_set"]):
                continue
            range_ = _field(path, target).get("range")
            for where, value in _slots(body, path):
                slot = _Slot(rule, rules.field_origins.get(path), label, where, value, range_)
                if self._rule_required(slot):
                    continue                   # пустое поле: остальные виды правила нового о нём не скажут
                self._rule_min_count(slot)
                self._rule_selector_types(slot)
                self._rule_entity_classes(slot)
                self._rule_ucum(slot)

    def _rule_required(self, slot: _Slot) -> bool:
        if not slot.rule.get("required") or not _empty(slot.value, slot.range):
            return False
        self._broken(slot, slot.where, "required", f"Не заполнено поле {slot.where}.")
        return True

    def _rule_min_count(self, slot: _Slot) -> None:
        n = slot.rule.get("min_count")
        if n is not None and _count(slot.value) < n:
            self._broken(slot, slot.where, "min_count", f"В {slot.where} меньше {n} элементов.")

    def _rule_selector_types(self, slot: _Slot) -> None:
        types = slot.rule.get("selector_types")
        if not types:
            return
        for where, selectors in _selector_groups(slot.where, slot.value, slot.range):
            if not any(t in types for s in selectors for t in _chain(s)):
                self._broken(slot, where, "selector_types",
                             f"Нет места вида {', '.join(types)} — ни у селектора, ни в его уточнениях refined_by.")

    def _rule_entity_classes(self, slot: _Slot) -> None:
        classes = slot.rule.get("entity_classes")
        if not classes:
            return
        for where, ref in _each(slot.where, slot.value):
            if f"{slot.label}: {where}" in self.unresolved:
                continue                       # один дефект — одно замечание: ref_unknown уже есть
            node = self.node(ref)
            if node is not None and (node.target != "entity" or node.code not in classes):
                whose = f"сущность класса {node.code}" if node.target == "entity" else "атом"
                self._broken(slot, where, "entity_classes",
                             f"{ref} — {whose}, а нужна сущность класса {', '.join(classes)}.", ref=ref)

    def _rule_ucum(self, slot: _Slot) -> None:
        if slot.rule.get("ucum") and slot.value is not None and not units.is_ucum(slot.value):
            self._broken(slot, slot.where, "ucum",
                         f"Единица {slot.value!r} — не код UCUM (с учётом регистра: kPa, mm, W/(m2.K), Cel, 1).",
                         unit=slot.value)

    def _broken(self, slot: _Slot, where: str, kind: str, default: str, **extra) -> None:
        """Замечание правила поля: код ucum у правила ucum, иначе template; текст — message правила или общий."""
        rule = slot.rule
        message = (rule.get("message") or {}).get("ru") or default
        self.add(rule.get("severity") or "violation", "ucum" if kind == "ucum" else "template",
                 f"{slot.label}: {where}", message, template=slot.origin, path=rule["path"], rule=kind, **extra)

    def hard_rules(self, label: str, target: str, body: dict) -> None:
        """Что шаблоном не выразить: у значения или границы есть единица, границы по порядку, значение в границах."""
        for path in VALUES[target]:
            for where, v in canon.values_at(body, path):
                if not isinstance(v, dict):
                    continue
                amount, low, high = v.get("amount"), v.get("lower_bound"), v.get("upper_bound")
                if v.get("unit") is None and (amount, low, high) != (None, None, None):
                    self.add("violation", "unit_required", f"{label}: {where}.unit",
                             "Есть значение или граница, но нет единицы; у безразмерной величины единица — 1.")
                bounds = {k: x for k, x in (("amount", amount), ("lower_bound", low), ("upper_bound", high))
                          if x is not None}
                if low is not None and high is not None and low > high:
                    self.add("violation", "bounds_order", f"{label}: {where}",
                             f"Нижняя граница {low} больше верхней {high}.", **bounds)
                elif amount is not None and (low is not None and amount < low or high is not None and amount > high):
                    self.add("violation", "bounds_order", f"{label}: {where}",
                             f"Значение {amount} вне границ: {_span(low, high)}.", **bounds)

    def basis_rules(self, label: str, body: dict) -> None:
        """Основание и уверенность (спецификация 3c, разд. 2.1–2.2): author — слово человека, confidence — оценка
        модели; умолчанию и допущению нужно правило методики в derived_from, чтобы было видно, откуда они."""
        basis = body.get("basis")
        model = self.agent is not None and self.agent.startswith("model:")
        person = self.agent is not None and self.agent.startswith("person:")
        if basis == "author" and model:
            self.add("violation", "basis_author_model", f"{label}: basis",
                     "Основание basis author («утверждение автора») может поставить только человек (агент person:).",
                     basis=basis, agent=self.agent)
        if basis in ("default", "assumed") and not body.get("derived_from"):
            self.add("warning", "basis_without_rule", f"{label}: basis",
                     f"Основание basis {basis} без derived_from: не видно правила методики, по которому оно принято.",
                     basis=basis)
        if body.get("confidence") is not None and person:
            self.add("violation", "confidence_person", f"{label}: confidence",
                     "Поле confidence заполняет только модель: у записи человека его нет.", agent=self.agent)

    # --- связи ---

    def check_link(self, i: int, payload) -> _Link | None:
        """Тело связи, вид, концы и пара их видов; связь, годная для правил шаблонов, — _Link."""
        label = f"links[{i}]"
        if not self.parse(model_v1.LinkPayload, payload, label):
            return None
        rel = payload["rel"]
        concept = self.vocab["rel"].get(rel)
        if concept is None:
            self.add("violation", "unknown_code", f"{label}: rel",
                     f"вид связи {rel!r} — кода нет в загруженных пакетах", scheme="rel", value=rel)
        elif concept.get("via_field"):
            self.add("violation", "link_not_allowed", f"{label}: rel",
                     f"Связь {rel} задаётся полем {concept['via_field']} атома, а не отдельной связью.",
                     rel=rel, via_field=concept["via_field"])
            concept = None
        src = self.resolve(payload["src"], f"{label}: src")
        dst = self.resolve(payload["dst"], f"{label}: dst")
        self.field_rules(label, "link", payload, self.rules("link", rel))
        self.hard_rules(label, "link", payload)
        if concept is None or src is None or dst is None:
            return None
        pairs, pair = concept.get("pairs") or [], f"{src.target}>{dst.target}"
        if pair not in pairs:
            self.add("violation", "link_pair", label,
                     f"Связь {rel}: {src.target} → {dst.target} не допускается (можно: {', '.join(pairs)}).",
                     rel=rel, pair=pair, pairs=pairs)
            return None
        if src.identity == dst.identity:
            self.add("violation", "link_pair", label, f"Связь {rel}: запись не может ссылаться на себя.",
                     rel=rel, pair=pair, pairs=pairs)
            return None
        return _Link(label, rel, src, dst, bool(concept.get("symmetric")))

    def node_rules(self, node: _Node) -> Rules | None:
        if node.identity[0] == "item":
            return self.items[node.identity[1]].rules
        return self.rules(node.target, node.code, applied=False)      # шаблон записи базы, не записи пачки

    def link_rules(self, links: list[_Link]) -> None:
        """Правила связей шаблонов: исходящие связи записей пачки, затем allowed, затем required."""
        outgoing = self._outgoing(links)
        self._check_allowed(links)
        self._check_required(outgoing)

    def _via_fields(self, item: Prepared) -> list[tuple[str, str, list]]:
        """Поля тела, через которые выражается вид связи: (вид связи, поле, ссылки)."""
        return [(rel, name, item.payload[name]) for rel, name in self.via.items() if item.payload.get(name)]

    def _outgoing(self, links: list[_Link]) -> dict[int, list[tuple[str, _Node]]]:
        """Исходящие связи записей пачки: номер записи → (вид, другой конец). Связи пачки (у симметричной — с обоих
        концов) и поля-связи тела; связи в базе добавляет _check_required."""
        out: dict[int, list[tuple[str, _Node]]] = {}
        for link in links:
            for own, other in _ends(link):
                if own.identity[0] == "item":
                    out.setdefault(own.identity[1], []).append((link.rel, other))
        for i, item in enumerate(self.items):
            if item.ok:
                for rel, _, refs in self._via_fields(item):
                    out.setdefault(i, []).extend((rel, node) for node in map(self.node, refs) if node is not None)
        return out

    def _check_allowed(self, links: list[_Link]) -> None:
        """allowed — по шаблону каждого исходящего конца связи пачки (и записи базы) и у полей-связей тела."""
        for link in links:
            for own, _ in _ends(link):
                rules = self.node_rules(own)
                if rules is not None and rules.allowed is not None and link.rel not in rules.allowed:
                    self._not_allowed(link.where, link.rel, own.code, rules)
        for item in self.items:
            if item.ok and item.rules.allowed is not None:
                for rel, name, _ in self._via_fields(item):
                    if rel not in item.rules.allowed:
                        self._not_allowed(f"{item.label}: {name}", rel, item.code, item.rules)

    def _check_required(self, outgoing: dict[int, list[tuple[str, _Node]]]) -> None:
        """required — среди исходящих связей пачки и действующих связей записи в базе."""
        for i, item in enumerate(self.items):
            if not item.ok or not item.rules.required_links:
                continue
            mine = outgoing.get(i, [])
            if item.status is not None:
                mine = mine + self.stored_links(item.target, item.record_id)
            for req in item.rules.required_links:
                if any(_satisfies(rel, node, req) for rel, node in mine):
                    continue
                classes = req.get("to_classes")
                message = f"Нет связи {req['rel']}" + (f" с сущностью класса {', '.join(classes)}" if classes else "")
                self.add(req.get("severity") or "violation", "link_required", item.label, message + ".",
                         template=item.rules.link_origins.get(req["rel"]), rel=req["rel"],
                         **({"to_classes": classes} if classes else {}))

    def _not_allowed(self, where: str, rel: str, code: str | None, rules: Rules) -> None:
        allowed = sorted(rules.allowed)
        self.add("violation", "link_not_allowed", where,
                 f"Связь {rel} не допускается шаблоном {code} (можно: {', '.join(allowed) or 'никакие'}).",
                 rel=rel, allowed=allowed)

    def stored_links(self, target: str, record_id: uuid.UUID) -> list[tuple[str, _Node]]:
        """Действующие связи записи в базе: исходящие и симметричные входящие — (вид, другой конец)."""
        rows = self.conn.execute(
            "SELECT l.rel, l.dst_atom, l.dst_entity, e.entity_class FROM link l "
            f"LEFT JOIN entity e ON e.id = l.dst_entity WHERE l.retired_at IS NULL AND l.src_{target} = %(id)s "
            "UNION ALL SELECT l.rel, l.src_atom, l.src_entity, e.entity_class FROM link l "
            "JOIN concept c ON c.scheme = 'rel' AND c.code = l.rel LEFT JOIN entity e ON e.id = l.src_entity "
            f"WHERE l.retired_at IS NULL AND l.dst_{target} = %(id)s AND (c.data->>'symmetric')::boolean",
            {"id": record_id}).fetchall()
        return [(rel, self._db_node("atom", atom_id, None) if atom_id else self._db_node("entity", entity_id, cls))
                for rel, atom_id, entity_id, cls in rows]


def _path(loc) -> str:
    """loc ошибки Pydantic → путь поля: ("content", "values", 0, "unit") → content.values[0].unit."""
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


@functools.cache
def _field(path: str, target: str) -> dict:
    """Описание последнего поля пути правила в схеме LinkML (range, multivalued)."""
    try:
        return packs.check_path(path, target)
    except packs.PackError:                     # пути шаблонов проверены при загрузке пакетов
        return {}


def _is_set(body: dict, path: str) -> bool:
    """Поле по пути (через точку, без []) есть и непусто — условие skip_if_set."""
    node = body
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return node not in (None, "", [], {})


def _slots(body: dict, path: str) -> Iterator[tuple[str, object]]:
    """Места, где правило поля ждёт значение: (точный путь, значение или None).

    [] у промежуточного поля — каждый элемент списка; пустой список мест не даёт. Нет объекта на пути без [] —
    место есть, значения нет: required у content.values срабатывает и у атома без content.
    canon.values_at отдаёт только то, что есть, поэтому место отсутствующего поля строится здесь."""
    head, sep, rest = path.rpartition("[].")
    parents = canon.values_at(body, f"{head}[]") if sep else [("", body)]
    for where, node in parents:
        found = list(canon.values_at(node, rest)) if isinstance(node, dict) else []
        yield (f"{where}.{rest}" if where else rest), (found[0][1] if found else None)


def _empty(value, range_: str | None) -> bool:
    """Пусто для required: список без элементов, LangString без ru, объект без непустых полей, строка из пробелов."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        if range_ == "LangString":
            return _empty(value.get("ru"), None)
        return all(_empty(v, None) for v in value.values())
    return False


def _count(value) -> int:
    return len(value) if isinstance(value, list) else 0 if value is None else 1


def _each(where: str, value) -> list[tuple[str, object]]:
    if isinstance(value, list):
        return [(f"{where}[{j}]", v) for j, v in enumerate(value)]
    return [] if value is None else [(where, value)]


def _selector_groups(where: str, value, range_: str | None) -> list[tuple[str, list]]:
    """Селекторы, среди которых ищется нужный вид: путь ведёт на список селекторов или на источник (список
    источников) — тогда у каждого источника свои."""
    if range_ == "Source":
        sources = [s for s in _each(where, value) if isinstance(s[1], dict)]
        return [(at, s.get("selectors") or []) for at, s in sources]
    return [(where, value if isinstance(value, list) else [])]


def _chain(selector) -> Iterator[str]:
    """Виды селектора и его уточнений refined_by."""
    while isinstance(selector, dict):
        yield selector.get("type")
        selector = selector.get("refined_by")


def _ends(link: _Link) -> list[tuple[_Node, _Node]]:
    """(свой конец, другой конец) — у симметричной связи оба направления."""
    return [(link.src, link.dst)] + ([(link.dst, link.src)] if link.symmetric else [])


def _satisfies(rel: str, node: _Node, req: dict) -> bool:
    classes = req.get("to_classes")
    return rel == req["rel"] and (not classes or (node.target == "entity" and node.code in classes))


def _span(low, high) -> str:
    return " ".join(part for part in (f"от {low}" if low is not None else "", f"до {high}" if high is not None else "")
                    if part)
