from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.12.0"
version = "1.0.0"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
        allow_inf_nan = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'amem',
     'default_range': 'string',
     'description': 'Единственное описание схемы базы знаний. Из него генерируются '
                    'amem/model_v1.py (Pydantic) и amem/schema/amem_v1.schema.json '
                    '(JSON Schema): python tools/gen_schema.py. Коды полей, видов '
                    'и связей — латиницей и неизменны; подписи — в аннотациях '
                    'label_ru / label_en.',
     'id': 'amem',
     'imports': ['linkml:types'],
     'license': 'MIT',
     'name': 'amem_v1',
     'prefixes': {'amem': {'prefix_prefix': 'amem', 'prefix_reference': 'amem/'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'amem/schema/amem_v1.yaml',
     'title': 'amem — схема атома v1'} )

class Status(str, Enum):
    """
    Статус атома, сущности или понятия словаря.
    """
    draft = "draft"
    needs_review = "needs_review"
    auto_verified = "auto_verified"
    verified = "verified"
    rejected = "rejected"
    deprecated = "deprecated"
    superseded = "superseded"


class Rank(str, Enum):
    preferred = "preferred"
    normal = "normal"
    deprecated = "deprecated"


class ValueState(str, Enum):
    known = "known"
    unknown = "unknown"
    none = "none"


class SourceRole(str, Enum):
    primary = "primary"
    secondary = "secondary"
    derived = "derived"


class Visibility(str, Enum):
    private = "private"
    department = "department"
    company = "company"


class ObjectKind(str, Enum):
    file = "file"
    web = "web"
    message = "message"


class ObjectStatus(str, Enum):
    """
    Что из объекта атомизировано (бывший реестр документов). Текущий статус — последняя отметка.
    """
    parsed = "parsed"
    partial = "partial"
    skipped = "skipped"


class SourceVerdict(str, Enum):
    """
    Итог сверки источника с текстом файла (уровень 2 автопроверки). Значок в выдаче — ✓, ≈ или ⚠; у no_text и external значка нет.
    """
    ok = "ok"
    moved = "moved"
    fuzzy = "fuzzy"
    by_locator = "by_locator"
    unresolved = "unresolved"
    not_found = "not_found"
    no_file = "no_file"
    no_text = "no_text"
    external = "external"
    error = "error"


class ReviewState(str, Enum):
    none = "none"
    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class ChangesetState(str, Enum):
    approved = "approved"
    rejected = "rejected"


class ActivityKind(str, Enum):
    task = "task"
    wave = "wave"
    session = "session"
    migration = "migration"


class Severity(str, Enum):
    violation = "violation"
    warning = "warning"
    info = "info"


class CheckCode(str, Enum):
    """
    Код замечания автопроверки; уровень и важность — в спецификации.
    """
    schema = "schema"
    unknown_code = "unknown_code"
    ref_unknown = "ref_unknown"
    template = "template"
    ucum = "ucum"
    unit_required = "unit_required"
    bounds_order = "bounds_order"
    link_not_allowed = "link_not_allowed"
    link_required = "link_required"
    link_pair = "link_pair"
    retired_record = "retired_record"
    record_error = "record_error"
    source_unresolved = "source_unresolved"
    version_missing = "version_missing"
    digest_mismatch = "digest_mismatch"
    pdf_page_required = "pdf_page_required"
    pdf_quote_required = "pdf_quote_required"
    quote_not_found = "quote_not_found"
    quote_fuzzy = "quote_fuzzy"
    quote_ocr = "quote_ocr"
    number_not_found = "number_not_found"
    page_moved = "page_moved"
    place_unresolved = "place_unresolved"
    no_text = "no_text"
    external_source = "external_source"
    source_error = "source_error"
    numbers_unchecked = "numbers_unchecked"
    edition_filled = "edition_filled"
    unknown_property = "unknown_property"
    out_of_range = "out_of_range"
    unit_mismatch = "unit_mismatch"
    conflict = "conflict"
    duplicate = "duplicate"
    related = "related"
    basis_author_model = "basis_author_model"
    basis_without_rule = "basis_without_rule"
    confidence_person = "confidence_person"
    bundle_pack_missing = "bundle_pack_missing"
    bundle_key_collision = "bundle_key_collision"
    bundle_object_conflict = "bundle_object_conflict"


class ReviewReason(str, Enum):
    """
    Почему запись попала в очередь проверки.
    """
    semantic = "semantic"
    warning = "warning"
    high_risk = "high_risk"
    semantic_doubt = "semantic_doubt"
    edit = "edit"
    source_changed = "source_changed"
    audit = "audit"
    calibration = "calibration"
    imported = "imported"


class ReviewItemState(str, Enum):
    queued = "queued"
    claimed = "claimed"
    done = "done"
    obsolete = "obsolete"


class VerificationMethod(str, Enum):
    llm_judge = "llm_judge"
    human = "human"


class VerificationOutcome(str, Enum):
    confirmed = "confirmed"
    partial = "partial"
    refuted = "refuted"
    uncertain = "uncertain"


class HighRiskRule(str, Enum):
    """
    Правило шаблона, по которому запись считается рискованной.
    """
    always = "always"
    numeric = "numeric"
    low_confidence = "low_confidence"


class Basis(str, Enum):
    """
    Основание значения, когда оно не взято из документа об объекте.
    """
    default = "default"
    assumed = "assumed"
    author = "author"


class TemplateTarget(str, Enum):
    atom = "atom"
    entity = "entity"
    link = "link"


class CardState(str, Enum):
    """
    Состояние поля карточки amem.card/1 (спецификация 3c, разд. 3.4).
    """
    known = "known"
    missing = "missing"
    asked = "asked"
    na = "na"
    conflict = "conflict"


class TemplateBody(str, Enum):
    """
    Текст записи в форме вида (Template.ui.body) — подсказка интерфейсу, на проверку записи не влияет.
    """
    wanted = "wanted"
    required = "required"
    none = "none"


class TemplateWidget(str, Enum):
    """
    Блок страницы записи вида (Template.ui.widgets) — подсказка интерфейсу.
    """
    sources = "sources"
    links = "links"
    around = "around"
    values_table = "values_table"
    similar = "similar"
    children = "children"


class FieldType(str, Enum):
    """
    Тип поля формы вида (amem/forms.py); без явного типа выводится из пути поля.
    """
    object = "object"
    record = "record"
    quantity = "quantity"
    date = "date"
    period = "period"
    choice = "choice"
    tags = "tags"
    text = "text"


class KindFamily(str, Enum):
    """
    Семья вида атома (Concept.family, спецификация подпроекта 4, разд. 1.2): откуда знание — из документа или из работы. По ней интерфейс группирует виды и раскрашивает граф. Вид без family считается work.
    """
    source = "source"
    work = "work"



class LangString(ConfiguredBaseModel):
    """
    Текст на нескольких языках; русский обязателен.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    ru: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LangString']} })
    en: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['LangString']} })


class Selector(ConfiguredBaseModel):
    """
    Место внутри файла. refined_by уточняет его — лист → диапазон, страница → цитата.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    type: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector', 'TemplateUiField']} })
    value: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector', 'CardField']} })
    label: Optional[str] = Field(default=None, description="""Как место подписано в документе — «л. 24–25».""", json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    refined_by: Optional[Selector] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector']} })

    @field_validator('type')
    def pattern_type(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid type format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid type format: {v}"
            raise ValueError(err_msg)
        return v


class Source(ConfiguredBaseModel):
    """
    Источник: объект + версия + селекторы + цитата. Во входных данных агент даёт path (путь в папке документов), сервер заменяет его на object, object_version и digest.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    path: Optional[str] = Field(default=None, description="""Путь в папке документов или название письма / адрес сайта. Только во входных данных.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Source', 'FieldRule', 'TemplateUiField']} })
    object: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Source']} })
    object_version: Optional[int] = Field(default=None, ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Source']} })
    digest: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Source', 'ObjectVersion']} })
    selectors: Optional[list[Selector]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Source']} })
    quote: Optional[str] = Field(default=None, description="""Дословная цитата в пределах одной страницы — её сверяет с файлом проверка уровня 2. Для PDF обязательна.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Source']} })
    edition: Optional[str] = Field(default=None, description="""Редакция документа — сущность класса edition.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Source']} })
    role: Optional[SourceRole] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Source']} })

    @field_validator('object')
    def pattern_object(cls, v):
        pattern=re.compile(r"^obj:[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid object format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid object format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('digest')
    def pattern_digest(cls, v):
        pattern=re.compile(r"^sha256:[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid digest format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid digest format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('edition')
    def pattern_edition(cls, v):
        pattern=re.compile(r"^(ent:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid edition format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid edition format: {v}"
            raise ValueError(err_msg)
        return v


class Value(ConfiguredBaseModel):
    """
    Величина (Wikidata Quantity + UCUM). property — код из словаря property.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    property: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterRule', 'CardField']} })
    label: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    amount: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterDefault']} })
    lower_bound: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier']} })
    upper_bound: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier']} })
    unit: Optional[str] = Field(default=None, description="""Код UCUM с учётом регистра — kPa, mm, W/(m2.K), Cel, 1.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'Concept',
                       'ParameterDefault']} })
    quantity_kind: Optional[str] = Field(default=None, description="""Род величины QUDT — Pressure, Length.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Concept']} })
    value_text: Optional[str] = Field(default=None, description="""Нечисловое значение — ветровой район «II».""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterDefault']} })
    value_state: Optional[ValueState] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier']} })
    note: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'LinkPayload', 'Verification']} })
    qualifiers: Optional[list[Qualifier]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'AtomPayload', 'LinkPayload']} })

    @field_validator('property')
    def pattern_property(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid property format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid property format: {v}"
            raise ValueError(err_msg)
        return v


class Qualifier(ConfiguredBaseModel):
    """
    Условие применимости (уточнение в духе Wikidata).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    property: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterRule', 'CardField']} })
    label: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    value_text: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterDefault']} })
    amount: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterDefault']} })
    lower_bound: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier']} })
    upper_bound: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier']} })
    unit: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'Concept',
                       'ParameterDefault']} })
    value_state: Optional[ValueState] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier']} })

    @field_validator('property')
    def pattern_property(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid property format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid property format: {v}"
            raise ValueError(err_msg)
        return v


class Symbol(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    symbol: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Symbol']} })
    label: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    term: Optional[str] = Field(default=None, description="""Атом-термин с определением обозначения.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Symbol']} })
    unit: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'Concept',
                       'ParameterDefault']} })

    @field_validator('term')
    def pattern_term(cls, v):
        pattern=re.compile(r"^(atm:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid term format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid term format: {v}"
            raise ValueError(err_msg)
        return v


class Formula(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    latex: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Formula']} })
    plain: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Formula']} })
    symbols: Optional[list[Symbol]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Formula']} })


class Column(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    code: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Column', 'Concept', 'Template', 'CheckIssue']} })
    label: LangString = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    unit: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'Concept',
                       'ParameterDefault']} })

    @field_validator('code')
    def pattern_code(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid code format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid code format: {v}"
            raise ValueError(err_msg)
        return v


class Table(ConfiguredBaseModel):
    """
    Таблица целиком. rows — список строк, каждая строка — список значений по columns.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    columns: list[Column] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Table']} })
    rows: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Table']} })


class Content(ConfiguredBaseModel):
    """
    Форма записи — одна или несколько.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    values: Optional[list[Value]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Content']} })
    formula: Optional[Formula] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Content']} })
    table: Optional[Table] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Content']} })


class Scope(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    project: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Scope']} })
    discipline: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Scope']} })
    visibility: Optional[Visibility] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Scope']} })

    @field_validator('project')
    def pattern_project(cls, v):
        pattern=re.compile(r"^(ent:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid project format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid project format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('discipline')
    def pattern_discipline(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid discipline format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid discipline format: {v}"
            raise ValueError(err_msg)
        return v


class ExternalIds(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    bsdd: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ExternalIds']} })
    wikidata: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ExternalIds']} })
    ifc: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ExternalIds']} })


class Provenance(ConfiguredBaseModel):
    """
    Происхождение записи при переносе между базами (задел под хаб, разд. 5 спеки amem).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    origin_base: Optional[str] = Field(default=None, description="""base_id базы, из которой атом пришёл при разворачивании проекта в собственную базу. Заполняется только при импорте из другой базы; не ссылка — UUID-строка.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance']} })
    origin_revision_hash: Optional[str] = Field(default=None, description="""content_hash ревизии в базе-источнике — по нему повторный импорт узнаёт то же содержание.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance']} })
    origin_agent: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance']} })

    @field_validator('origin_base')
    def pattern_origin_base(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid origin_base format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid origin_base format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('origin_revision_hash')
    def pattern_origin_revision_hash(cls, v):
        pattern=re.compile(r"^sha256-c[1-9][0-9]*:[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid origin_revision_hash format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid origin_revision_hash format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('origin_agent')
    def pattern_origin_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid origin_agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid origin_agent format: {v}"
            raise ValueError(err_msg)
        return v


class AtomPayload(ConfiguredBaseModel):
    """
    Тело атома — что предлагает агент. В ревизии хранится в канонической форме: без ref и path, ссылки — только по UUID, у источника object, object_version и digest (проверяет этап 2).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    ref: Optional[str] = Field(default=None, description="""Временное имя в пачке (@имя) для ссылок внутри неё. В ревизию не записывается.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    key: Optional[str] = Field(default=None, description="""Необязательный читаемый ключ.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'ObjectRecord', 'Activity']} })
    label: LangString = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    summary_plain: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    body: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'TemplateUi']} })
    aliases: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    codes: Optional[list[str]] = Field(default=None, description="""Марки, обозначения, символы целиком — m10, dn50, w0, 10.1.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    retrieval_context: Optional[LangString] = Field(default=None, description="""Фраза агента к контексту поиска; остальное сервер собирает сам.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    content: Optional[Content] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    qualifiers: Optional[list[Qualifier]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'AtomPayload', 'LinkPayload']} })
    about: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    sources: Optional[list[Source]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload', 'CardField']} })
    rank: Optional[Rank] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'CardField']} })
    valid_from: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    valid_to: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    scope: Optional[Scope] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    tags: Optional[list[str]] = Field(default=None, description="""Свободные метки. Приставка вида «объект:…» запрещена — это about.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    derived_from: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    provenance: Optional[Provenance] = Field(default=None, description="""Происхождение атома при переносе из другой базы; у своих атомов поля нет.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    basis: Optional[Basis] = Field(default=None, description="""Основание значения без документа; при заданном basis источник не обязателен (has_source 1.1.0).""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'CardField']} })
    confidence: Optional[float] = Field(default=None, description="""Уверенность агента-модели в утверждении (распознавание, извлечение). Человек поле не заполняет.""", ge=0, le=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'LinkPayload', 'CardField', 'Verification']} })

    @field_validator('ref')
    def pattern_ref(cls, v):
        pattern=re.compile(r"^@[a-z0-9_]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid ref format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid ref format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('key')
    def pattern_key(cls, v):
        pattern=re.compile(r"^[a-z0-9][a-z0-9_.]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid key format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid key format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('kind')
    def pattern_kind(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid kind format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid kind format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('about')
    def pattern_about(cls, v):
        pattern=re.compile(r"^(ent:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid about format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid about format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('tags')
    def pattern_tags(cls, v):
        pattern=re.compile(r"^(?![^\s:]+:).+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid tags format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid tags format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('derived_from')
    def pattern_derived_from(cls, v):
        pattern=re.compile(r"^(atm:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid derived_from format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid derived_from format: {v}"
            raise ValueError(err_msg)
        return v


class Atom(AtomPayload):
    """
    Атом в выдаче сервера — тело текущей ревизии + технические поля, которые ставит сервер.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    schema_version: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    revision: Optional[int] = Field(default=None, ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    content_hash: Optional[str] = Field(default=None, description="""Хэш канонического тела ревизии; метка cN — версия правил канонизации (сейчас c1, amem/canon.py).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    status: Optional[Status] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Concept', 'CardField']} })
    review_state: Optional[ReviewState] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    folder: Optional[str] = Field(default=None, description="""Папка записи — метаданные, не часть ревизии (amem/folders.py); null — без папки.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    created_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    recorded_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'ObjectVersion']} })
    changeset: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Link']} })
    agent: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'Verification']} })
    activity: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Bundle', 'Changeset']} })
    ref: Optional[str] = Field(default=None, description="""Временное имя в пачке (@имя) для ссылок внутри неё. В ревизию не записывается.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    key: Optional[str] = Field(default=None, description="""Необязательный читаемый ключ.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'ObjectRecord', 'Activity']} })
    label: LangString = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    summary_plain: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    body: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'TemplateUi']} })
    aliases: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    codes: Optional[list[str]] = Field(default=None, description="""Марки, обозначения, символы целиком — m10, dn50, w0, 10.1.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    retrieval_context: Optional[LangString] = Field(default=None, description="""Фраза агента к контексту поиска; остальное сервер собирает сам.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    content: Optional[Content] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    qualifiers: Optional[list[Qualifier]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'AtomPayload', 'LinkPayload']} })
    about: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    sources: Optional[list[Source]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload', 'CardField']} })
    rank: Optional[Rank] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'CardField']} })
    valid_from: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    valid_to: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    scope: Optional[Scope] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    tags: Optional[list[str]] = Field(default=None, description="""Свободные метки. Приставка вида «объект:…» запрещена — это about.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    derived_from: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    provenance: Optional[Provenance] = Field(default=None, description="""Происхождение атома при переносе из другой базы; у своих атомов поля нет.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload']} })
    basis: Optional[Basis] = Field(default=None, description="""Основание значения без документа; при заданном basis источник не обязателен (has_source 1.1.0).""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'CardField']} })
    confidence: Optional[float] = Field(default=None, description="""Уверенность агента-модели в утверждении (распознавание, извлечение). Человек поле не заполняет.""", ge=0, le=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'LinkPayload', 'CardField', 'Verification']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('schema_version')
    def pattern_schema_version(cls, v):
        pattern=re.compile(r"^amem\.atom/[0-9]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid schema_version format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid schema_version format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('content_hash')
    def pattern_content_hash(cls, v):
        pattern=re.compile(r"^sha256-c[1-9][0-9]*:[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid content_hash format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid content_hash format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('changeset')
    def pattern_changeset(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid changeset format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid changeset format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('agent')
    def pattern_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid agent format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('activity')
    def pattern_activity(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid activity format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid activity format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('ref')
    def pattern_ref(cls, v):
        pattern=re.compile(r"^@[a-z0-9_]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid ref format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid ref format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('key')
    def pattern_key(cls, v):
        pattern=re.compile(r"^[a-z0-9][a-z0-9_.]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid key format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid key format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('kind')
    def pattern_kind(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid kind format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid kind format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('about')
    def pattern_about(cls, v):
        pattern=re.compile(r"^(ent:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid about format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid about format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('tags')
    def pattern_tags(cls, v):
        pattern=re.compile(r"^(?![^\s:]+:).+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid tags format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid tags format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('derived_from')
    def pattern_derived_from(cls, v):
        pattern=re.compile(r"^(atm:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid derived_from format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid derived_from format: {v}"
            raise ValueError(err_msg)
        return v


class EntityPayload(ConfiguredBaseModel):
    """
    Вещь — объект, система, изделие, узел, материал, норматив, редакция, документ. В ревизии хранится в канонической форме: без ref и path, ссылки — только по UUID, у источника object, object_version и digest (проверяет этап 2).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    key: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    entity_class: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload']} })
    label: LangString = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    aliases: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    codes: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    description: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload', 'Template']} })
    external_ids: Optional[ExternalIds] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload']} })
    edition_of: Optional[str] = Field(default=None, description="""Только у класса edition — норматив или документ, редакцией которого она является.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload']} })
    valid_from: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    valid_to: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    sources: Optional[list[Source]] = Field(default=None, description="""Файлы, которыми представлена сущность (для документа и редакции), или откуда она известна.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload', 'CardField']} })

    @field_validator('ref')
    def pattern_ref(cls, v):
        pattern=re.compile(r"^@[a-z0-9_]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid ref format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid ref format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('key')
    def pattern_key(cls, v):
        pattern=re.compile(r"^[a-z0-9][a-z0-9_.]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid key format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid key format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('entity_class')
    def pattern_entity_class(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid entity_class format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid entity_class format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('edition_of')
    def pattern_edition_of(cls, v):
        pattern=re.compile(r"^(ent:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid edition_of format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid edition_of format: {v}"
            raise ValueError(err_msg)
        return v


class Entity(EntityPayload):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    schema_version: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    revision: Optional[int] = Field(default=None, ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    content_hash: Optional[str] = Field(default=None, description="""Хэш канонического тела ревизии; метка cN — версия правил канонизации (сейчас c1, amem/canon.py).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    status: Optional[Status] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Concept', 'CardField']} })
    review_state: Optional[ReviewState] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    folder: Optional[str] = Field(default=None, description="""Папка записи — метаданные, не часть ревизии (amem/folders.py); null — без папки.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity']} })
    created_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    recorded_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'ObjectVersion']} })
    changeset: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Link']} })
    agent: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'Verification']} })
    activity: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Bundle', 'Changeset']} })
    ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    key: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    entity_class: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload']} })
    label: LangString = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    aliases: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    codes: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    description: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload', 'Template']} })
    external_ids: Optional[ExternalIds] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload']} })
    edition_of: Optional[str] = Field(default=None, description="""Только у класса edition — норматив или документ, редакцией которого она является.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload']} })
    valid_from: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    valid_to: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload']} })
    sources: Optional[list[Source]] = Field(default=None, description="""Файлы, которыми представлена сущность (для документа и редакции), или откуда она известна.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload', 'CardField']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('schema_version')
    def pattern_schema_version(cls, v):
        pattern=re.compile(r"^amem\.entity/[0-9]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid schema_version format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid schema_version format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('content_hash')
    def pattern_content_hash(cls, v):
        pattern=re.compile(r"^sha256-c[1-9][0-9]*:[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid content_hash format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid content_hash format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('changeset')
    def pattern_changeset(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid changeset format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid changeset format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('agent')
    def pattern_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid agent format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('activity')
    def pattern_activity(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid activity format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid activity format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('ref')
    def pattern_ref(cls, v):
        pattern=re.compile(r"^@[a-z0-9_]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid ref format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid ref format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('key')
    def pattern_key(cls, v):
        pattern=re.compile(r"^[a-z0-9][a-z0-9_.]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid key format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid key format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('entity_class')
    def pattern_entity_class(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid entity_class format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid entity_class format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('edition_of')
    def pattern_edition_of(cls, v):
        pattern=re.compile(r"^(ent:([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid edition_of format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid edition_of format: {v}"
            raise ValueError(err_msg)
        return v


class LinkPayload(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    rel: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload', 'RequiredLink']} })
    src: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload']} })
    dst: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload']} })
    note: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'LinkPayload', 'Verification']} })
    qualifiers: Optional[list[Qualifier]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'AtomPayload', 'LinkPayload']} })
    confidence: Optional[float] = Field(default=None, ge=0, le=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'LinkPayload', 'CardField', 'Verification']} })

    @field_validator('rel')
    def pattern_rel(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid rel format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid rel format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('src')
    def pattern_src(cls, v):
        pattern=re.compile(r"^((atm|ent):([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid src format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid src format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('dst')
    def pattern_dst(cls, v):
        pattern=re.compile(r"^((atm|ent):([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid dst format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid dst format: {v}"
            raise ValueError(err_msg)
        return v


class Link(LinkPayload):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    created_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    changeset: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Link']} })
    agent: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'Verification']} })
    retired_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Link']} })
    rel: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload', 'RequiredLink']} })
    src: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload']} })
    dst: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload']} })
    note: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'LinkPayload', 'Verification']} })
    qualifiers: Optional[list[Qualifier]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'AtomPayload', 'LinkPayload']} })
    confidence: Optional[float] = Field(default=None, ge=0, le=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'LinkPayload', 'CardField', 'Verification']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('changeset')
    def pattern_changeset(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid changeset format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid changeset format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('agent')
    def pattern_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid agent format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('rel')
    def pattern_rel(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid rel format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid rel format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('src')
    def pattern_src(cls, v):
        pattern=re.compile(r"^((atm|ent):([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid src format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid src format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('dst')
    def pattern_dst(cls, v):
        pattern=re.compile(r"^((atm|ent):([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[a-z0-9][a-z0-9_.]*)|@[a-z0-9_]+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid dst format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid dst format: {v}"
            raise ValueError(err_msg)
        return v


class ObjectVersion(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    n: int = Field(default=..., ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectVersion']} })
    digest: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Source', 'ObjectVersion']} })
    size: Optional[int] = Field(default=None, ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectVersion']} })
    recorded_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'ObjectVersion']} })

    @field_validator('digest')
    def pattern_digest(cls, v):
        pattern=re.compile(r"^sha256:[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid digest format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid digest format: {v}"
            raise ValueError(err_msg)
        return v


class ObjectRecord(ConfiguredBaseModel):
    """
    Объект — файл (копия по хэшу), страница сайта или переписка.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    kind: ObjectKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'ObjectRecord', 'Activity']} })
    original_name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })
    media_type: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })
    format_puid: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })
    url: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })
    retrieved_at: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })
    logical_paths: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })
    versions: Optional[list[ObjectVersion]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ObjectRecord']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class Bundle(ConfiguredBaseModel):
    """
    Пачка предложений агента — один пакет изменений (kb_add, kb_import).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    reason: Optional[str] = Field(default=None, description="""Основание — что за документ или задача.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Changeset', 'ReviewItem']} })
    activity: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Bundle', 'Changeset']} })
    entities: Optional[list[EntityPayload]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    atoms: Optional[list[AtomPayload]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'CardField']} })
    links: Optional[list[LinkPayload]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Template']} })

    @field_validator('activity')
    def pattern_activity(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid activity format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid activity format: {v}"
            raise ValueError(err_msg)
        return v


class Concept(ConfiguredBaseModel):
    """
    Понятие словаря (SKOS).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    scheme: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    code: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Column', 'Concept', 'Template', 'CheckIssue']} })
    label: LangString = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    definition: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    inverse_label: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    broader: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    status: Optional[Status] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Concept', 'CardField']} })
    unit: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'Concept',
                       'ParameterDefault']} })
    quantity_kind: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Concept']} })
    plausible_min: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    plausible_max: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    pairs: Optional[list[str]] = Field(default=None, description="""Допустимые пары концов связи «от>к» — atom>entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    symmetric: Optional[bool] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    via_field: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })
    family: Optional[KindFamily] = Field(default=None, description="""Семья вида атома — только у понятий scheme kind; без неё вид считается work.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Concept']} })

    @field_validator('scheme')
    def pattern_scheme(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid scheme format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid scheme format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('code')
    def pattern_code(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid code format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid code format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('broader')
    def pattern_broader(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid broader format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid broader format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('pairs')
    def pattern_pairs(cls, v):
        pattern=re.compile(r"^(atom|entity)>(atom|entity)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid pairs format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid pairs format: {v}"
            raise ValueError(err_msg)
        return v


class FieldRule(ConfiguredBaseModel):
    """
    Правило шаблона для поля. path — через точку; [] — каждый элемент списка, ставится у промежуточных списков (sources[].edition). Правило с [] относится к каждому элементу: у нормы каждый источник — сам документ. required — поле непустое: список — хотя бы один элемент, текст — непустой ru, объект — хотя бы одно непустое поле. min_count — не меньше N элементов (для N больше 1; для одного — required). selector_types — хотя бы один селектор из перечня, с учётом цепочки refined_by. entity_classes — класс сущности, на которую ведёт ссылка. ucum — значение — код UCUM. severity по умолчанию — violation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    path: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Source', 'FieldRule', 'TemplateUiField']} })
    required: Optional[bool] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'LinkRules', 'ParameterRule', 'CardField']} })
    min_count: Optional[int] = Field(default=None, ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule']} })
    severity: Optional[Severity] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'RequiredLink', 'CheckIssue']} })
    ucum: Optional[bool] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule']} })
    selector_types: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule']} })
    entity_classes: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule']} })
    skip_if_set: Optional[str] = Field(default=None, description="""Путь до поля того же тела; если оно непусто, правило не применяется.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule']} })
    message: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'CheckIssue']} })

    @field_validator('path')
    def pattern_path(cls, v):
        pattern=re.compile(r"^[a-z_][a-z0-9_]*(\[\])?(\.[a-z_][a-z0-9_]*(\[\])?)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid path format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid path format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('selector_types')
    def pattern_selector_types(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid selector_types format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid selector_types format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('entity_classes')
    def pattern_entity_classes(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid entity_classes format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid entity_classes format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('skip_if_set')
    def pattern_skip_if_set(cls, v):
        pattern=re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid skip_if_set format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid skip_if_set format: {v}"
            raise ValueError(err_msg)
        return v


class RequiredLink(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    rel: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LinkPayload', 'RequiredLink']} })
    to_classes: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['RequiredLink']} })
    severity: Optional[Severity] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'RequiredLink', 'CheckIssue']} })

    @field_validator('rel')
    def pattern_rel(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid rel format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid rel format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('to_classes')
    def pattern_to_classes(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid to_classes format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid to_classes format: {v}"
            raise ValueError(err_msg)
        return v


class LinkRules(ConfiguredBaseModel):
    """
    Связи атома этого вида. allowed — какие исходящие связи разрешены (входящие не ограничиваются); исходящая связь другого вида — нарушение violation. required — хотя бы одна связь этого вида, а при to_classes — к сущности одного из этих классов; about и derived_from проверяются по полям атома. severity по умолчанию — violation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    allowed: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['LinkRules']} })
    required: Optional[list[RequiredLink]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'LinkRules', 'ParameterRule', 'CardField']} })

    @field_validator('allowed')
    def pattern_allowed(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid allowed format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid allowed format: {v}"
            raise ValueError(err_msg)
        return v


class ParameterRule(ConfiguredBaseModel):
    """
    Правило профиля сущности: какая величина нужна объекту этого класса. required — блокер; default — умолчание области (в карточке показывается, значением не считается); origin — код словаря parameter_origin.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    property: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterRule', 'CardField']} })
    required: Optional[bool] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'LinkRules', 'ParameterRule', 'CardField']} })
    group: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    origin: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    default: Optional[ParameterDefault] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    ask: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    hint: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField', 'TemplateUiField']} })
    when: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })

    @field_validator('property')
    def pattern_property(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid property format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid property format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('group')
    def pattern_group(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid group format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid group format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('origin')
    def pattern_origin(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid origin format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid origin format: {v}"
            raise ValueError(err_msg)
        return v


class ParameterDefault(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    amount: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterDefault']} })
    unit: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'Concept',
                       'ParameterDefault']} })
    value_text: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterDefault']} })


class CardField(ConfiguredBaseModel):
    """
    Поле карточки: правило профиля и выведенное по действующим атомам parameter состояние. У known — значение и признаки (status, by, basis, rank, confidence, source_role, sources) — у лучшего из атомов с этим значением (verified, затем человек, затем новее); candidates — остальные значения, кроме rank deprecated. Карточка не хранится — класс только описывает формат (JSON Schema).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    property: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Qualifier', 'ParameterRule', 'CardField']} })
    required: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'LinkRules', 'ParameterRule', 'CardField']} })
    group: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    origin: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    rule: Optional[str] = Field(default=None, description="""Шаблон, чьё правило действует (code@version).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CardField']} })
    default: Optional[Any] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    ask: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    hint: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField', 'TemplateUiField']} })
    when: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField']} })
    state: CardState = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CardField', 'Changeset', 'ReviewItem']} })
    value: Optional[Any] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector', 'CardField']} })
    atoms: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'CardField']} })
    candidates: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CardField']} })
    status: Optional[Status] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Concept', 'CardField']} })
    by: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CardField']} })
    basis: Optional[Basis] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'CardField']} })
    rank: Optional[Rank] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'CardField']} })
    confidence: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'LinkPayload', 'CardField', 'Verification']} })
    source_role: Optional[SourceRole] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CardField']} })
    sources: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'EntityPayload', 'CardField']} })

    @field_validator('property')
    def pattern_property(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid property format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid property format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('atoms')
    def pattern_atoms(cls, v):
        pattern=re.compile(r"^atm:[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid atoms format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid atoms format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('by')
    def pattern_by(cls, v):
        pattern=re.compile(r"^(person|model)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid by format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid by format: {v}"
            raise ValueError(err_msg)
        return v


class Card(ConfiguredBaseModel):
    """
    Карточка сущности amem.card/1 (profile.card): поля профиля её класса, величины вне профиля (extra), сводка и карточки предков по part_of. Вычисляется, не хранится.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    format: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'BundleManifest', 'CheckReport']} })
    entity: Any = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Card']} })
    profile: Optional[str] = Field(default=None, description="""Шаблон класса с профилем (code@version) или пусто, если профиля нет.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Card']} })
    templates: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'CheckReport']} })
    fields: Optional[list[CardField]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'Template', 'TemplateUi']} })
    extra: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card']} })
    summary: Any = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Card']} })
    ancestors: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card']} })

    @field_validator('format')
    def pattern_format(cls, v):
        pattern=re.compile(r"^amem\.card/1$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid format format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid format format: {v}"
            raise ValueError(err_msg)
        return v


class BundleManifest(ConfiguredBaseModel):
    """
    Манифест подборки amem.bundle/1 (bundle.export, файл manifest.json): откуда и что отобрано, пакеты, состав и sha256 каждого файла подборки (parts). Пишется последним; bundle.inspect сверяет части без базы.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    format: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'BundleManifest', 'CheckReport']} })
    created_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    base_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    agent: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'Verification']} })
    amem_version: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    selection: Any = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    packs: list[Any] = Field(default=..., description="""Пакеты, которым принадлежат коды записей, с зависимостями — name, version, digest, requires.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    counts: Any = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    parts: Any = Field(default=..., description="""Путь файла в подборке → sha256 (hex); все файлы, кроме самого манифеста.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    with_files: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    with_history: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })
    with_packs: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BundleManifest']} })

    @field_validator('format')
    def pattern_format(cls, v):
        pattern=re.compile(r"^amem\.bundle/1$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid format format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid format format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('base_id')
    def pattern_base_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid base_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid base_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('agent')
    def pattern_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid agent format: {v}"
            raise ValueError(err_msg)
        return v


class Template(ConfiguredBaseModel):
    """
    Шаблон вида атома, класса сущности или вида связи (applies_to) — или интерфейс (applies_to пуст): интерфейс действует на все записи своего target, даже если у вида нет своего шаблона. extends — интерфейсы и шаблоны того же target, без циклов; применяются слева направо, затем свои правила. Правила сводятся по path: правило потомка заменяет правило предка с тем же path. Данные с версией (semver).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    code: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Column', 'Concept', 'Template', 'CheckIssue']} })
    version: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Template']} })
    target: TemplateTarget = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Template', 'ReviewItem']} })
    applies_to: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Template']} })
    extends: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Template']} })
    description: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EntityPayload', 'Template']} })
    fields: Optional[list[FieldRule]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'Template', 'TemplateUi']} })
    links: Optional[LinkRules] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Template']} })
    high_risk: Optional[list[HighRiskRule]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Template']} })
    parameters: Optional[list[ParameterRule]] = Field(default=None, description="""Профиль параметров — только у target entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Template']} })
    ui: Optional[TemplateUi] = Field(default=None, description="""Как показывать вид в интерфейсе — форма, текст, блоки страницы (TemplateUi).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Template']} })

    @field_validator('code')
    def pattern_code(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid code format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid code format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('version')
    def pattern_version(cls, v):
        pattern=re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid version format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid version format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('applies_to')
    def pattern_applies_to(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid applies_to format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid applies_to format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('extends')
    def pattern_extends(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid extends format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid extends format: {v}"
            raise ValueError(err_msg)
        return v


class TemplateUiField(ConfiguredBaseModel):
    """
    Подпись, подсказка и тип поля формы. path — путь правила поля шаблона (FieldRule.path) или величина content.values[property=X] / qualifiers[property=X]; один path — не больше одного раза.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    path: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Source', 'FieldRule', 'TemplateUiField']} })
    label: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    hint: Optional[LangString] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ParameterRule', 'CardField', 'TemplateUiField']} })
    type: Optional[FieldType] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector', 'TemplateUiField']} })

    @field_validator('path')
    def pattern_path(cls, v):
        pattern=re.compile(r"^[a-z_][a-z0-9_]*(\[\])?(\.[a-z_][a-z0-9_]*(\[\])?)*(\[property=[a-z][a-z0-9_]*\])?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid path format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid path format: {v}"
            raise ValueError(err_msg)
        return v


class TemplateUi(ConfiguredBaseModel):
    """
    Как показывать вид в интерфейсе (спецификация подпроекта 4, разд. 6a.2): текст записи, блоки страницы, подписи и типы полей формы. На проверку записей не влияет; ключи fields сверяет проверка пакета (packs.py).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    body: Optional[TemplateBody] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'TemplateUi']} })
    widgets: Optional[list[TemplateWidget]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['TemplateUi']} })
    fields: Optional[list[TemplateUiField]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'Template', 'TemplateUi']} })


class Agent(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Agent']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class Activity(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    kind: ActivityKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'ObjectRecord', 'Activity']} })
    label: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Selector',
                       'Value',
                       'Qualifier',
                       'Symbol',
                       'Column',
                       'AtomPayload',
                       'EntityPayload',
                       'Concept',
                       'TemplateUiField',
                       'Activity']} })
    started_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Activity']} })
    ended_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Activity']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class Changeset(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    agent: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'Verification']} })
    activity: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom', 'Entity', 'Bundle', 'Changeset']} })
    reason: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Changeset', 'ReviewItem']} })
    state: ChangesetState = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CardField', 'Changeset', 'ReviewItem']} })
    check_report: Optional[Any] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Changeset']} })
    created_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('agent')
    def pattern_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid agent format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('activity')
    def pattern_activity(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid activity format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid activity format: {v}"
            raise ValueError(err_msg)
        return v


class CheckIssue(ConfiguredBaseModel):
    """
    Замечание автопроверки.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    level: int = Field(default=..., ge=1, le=4, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckIssue']} })
    severity: Severity = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'RequiredLink', 'CheckIssue']} })
    code: CheckCode = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Column', 'Concept', 'Template', 'CheckIssue']} })
    where: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CheckIssue']} })
    message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FieldRule', 'CheckIssue']} })
    details: Optional[Any] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckIssue', 'ReviewItem']} })


class CheckReport(ConfiguredBaseModel):
    """
    Отчёт пакета; пишется в changeset.check_report до записи ревизий.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    format: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'BundleManifest', 'CheckReport']} })
    levels: Any = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CheckReport']} })
    issues: Optional[list[CheckIssue]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckReport']} })
    degraded: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckReport']} })
    templates: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Card', 'CheckReport']} })
    records: Optional[list[Any]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckReport']} })

    @field_validator('format')
    def pattern_format(cls, v):
        pattern=re.compile(r"^amem\.check/1$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid format format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid format format: {v}"
            raise ValueError(err_msg)
        return v


class ReviewItem(ConfiguredBaseModel):
    """
    Пункт очереди проверки. Ревизия — атома или сущности, по target.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    target: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Template', 'ReviewItem']} })
    record_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })
    revision_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })
    reason: ReviewReason = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Changeset', 'ReviewItem']} })
    state: ReviewItemState = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CardField', 'Changeset', 'ReviewItem']} })
    changeset_id: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })
    details: Optional[Any] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckIssue', 'ReviewItem']} })
    created_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    created_by: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })
    claimed_by: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })
    claimed_until: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })
    closed_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReviewItem']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('target')
    def pattern_target(cls, v):
        pattern=re.compile(r"^(atom|entity)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid target format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid target format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('record_id')
    def pattern_record_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid record_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid record_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('revision_id')
    def pattern_revision_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid revision_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid revision_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('changeset_id')
    def pattern_changeset_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid changeset_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid changeset_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('created_by')
    def pattern_created_by(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid created_by format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid created_by format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('claimed_by')
    def pattern_claimed_by(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid claimed_by format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid claimed_by format: {v}"
            raise ValueError(err_msg)
        return v


class Verification(ConfiguredBaseModel):
    """
    Вердикт по пункту очереди; неизменяемый.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'amem'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'ObjectRecord',
                       'Agent',
                       'Activity',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })
    review_item_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Verification']} })
    method: VerificationMethod = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Verification']} })
    outcome: VerificationOutcome = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Verification']} })
    confidence: Optional[float] = Field(default=None, ge=0, le=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AtomPayload', 'LinkPayload', 'CardField', 'Verification']} })
    agent: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'Verification']} })
    note: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'LinkPayload', 'Verification']} })
    created_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Atom',
                       'Entity',
                       'Link',
                       'BundleManifest',
                       'Changeset',
                       'ReviewItem',
                       'Verification']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('review_item_id')
    def pattern_review_item_id(cls, v):
        pattern=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid review_item_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid review_item_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('agent')
    def pattern_agent(cls, v):
        pattern=re.compile(r"^(person|model):[a-z0-9_.-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.fullmatch(element):
                    err_msg = f"Invalid agent format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.fullmatch(v):
            err_msg = f"Invalid agent format: {v}"
            raise ValueError(err_msg)
        return v


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
LangString.model_rebuild()
Selector.model_rebuild()
Source.model_rebuild()
Value.model_rebuild()
Qualifier.model_rebuild()
Symbol.model_rebuild()
Formula.model_rebuild()
Column.model_rebuild()
Table.model_rebuild()
Content.model_rebuild()
Scope.model_rebuild()
ExternalIds.model_rebuild()
Provenance.model_rebuild()
AtomPayload.model_rebuild()
Atom.model_rebuild()
EntityPayload.model_rebuild()
Entity.model_rebuild()
LinkPayload.model_rebuild()
Link.model_rebuild()
ObjectVersion.model_rebuild()
ObjectRecord.model_rebuild()
Bundle.model_rebuild()
Concept.model_rebuild()
FieldRule.model_rebuild()
RequiredLink.model_rebuild()
LinkRules.model_rebuild()
ParameterRule.model_rebuild()
ParameterDefault.model_rebuild()
CardField.model_rebuild()
Card.model_rebuild()
BundleManifest.model_rebuild()
Template.model_rebuild()
TemplateUiField.model_rebuild()
TemplateUi.model_rebuild()
Agent.model_rebuild()
Activity.model_rebuild()
Changeset.model_rebuild()
CheckIssue.model_rebuild()
CheckReport.model_rebuild()
ReviewItem.model_rebuild()
Verification.model_rebuild()
