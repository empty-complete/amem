"""Следы секретов при записи (подпроект 4, разд. 6.6): private.secret_like по известным формам и предупреждение
secret_like в submit — служба HTTP (запись не отклоняется, значения в ответе нет)."""
import pytest

import contract
from amem import private
from test_service_write import V1, batch, fact, kb, post_submit, start  # noqa: F401 — фикстуры

AWS = "AKIA" + "IOSFODNN7EXAMPLE"                 # собирается по частям: в исходнике нет готового ключа


@pytest.mark.parametrize("text, kind", [
    (f"ключ доступа {AWS} к бакету", "aws_access_key"),
    ("ASIA" + "Q" * 16, "aws_access_key"),
    ("токен ghp_" + "a1B2" * 9, "github_token"),
    ("gho_" + "Z" * 36, "github_token"),
    ("github_pat_" + "11AAAA_" * 4, "github_token"),
    ("sk-" + "abc123XYZ" * 3, "api_key"),
    ("sk-ant-api03-" + "x" * 30, "api_key"),
    ("sk-proj-" + "q" * 24, "api_key"),
    ("xoxb-" + "1234567890-abcdef", "slack_token"),
    ("AIza" + "B" * 35, "google_api_key"),
    ("sk_live_" + "a" * 24, "stripe_key"),
    ("amem_" + "A" * 43, "amem_token"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIE…", "private_key"),
    ("-----BEGIN PRIVATE KEY-----", "private_key"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private_key"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "s" * 30, "jwt"),
    ("postgresql://amem:" + "s3cret" + "@db:5432/amem", "url_password"),
    ("https://user:" + "hunter22" + "@example.org/x", "url_password"),
    ("password=" + "Hunter2024", "password"),
    ("PASSWORD: " + "qwerty77", "password"),
    ("пароль: " + "Qwerty123!", "password"),
    ('api_key: "' + "abcd1234efgh" + '"', "password"),
])
def test_known_secret_forms(text, kind):
    assert kind in private.secret_like(text)


@pytest.mark.parametrize("text", [
    "ВН-45", "КБ-14 крепится к закладной анкером М10", "sha256:" + "a" * 64, "sha256:" + "0f" * 32,
    "018f3c1e-7a2b-7c3d-8e4f-123456789abc", "https://example.org/path?q=1", "postgresql://db:5432/amem",
    "ssh://git@example.org/repo.git", "user@example.org", "пароль от щита хранится у мастера",
    "Пароль задаёт администратор.", "password: ********", "password=<пароль>", "password: ${DB_PASSWORD}",
    "password=%(pw)s", "пароль: xxxxxx", "risk-assessment-procedure-document", "disk-" + "a" * 30, "sk-14",
    "AKIA в тексте", "ключ API лежит в хранилище секретов", "M10x1.25", "СП 20.13330.2016, табл. 11.2",
    "eyJ без продолжения", "-----BEGIN CERTIFICATE-----", "токен — 32 случайных байта",
    # значение после «пароль:» — слово, путь, обращение к окружению или переменной (ревью задачи 10)
    "Пароль: обязателен", "пароль: настраивается", "secret: стеклопакет", "pwd: /var/lib/app", "pwd: ~/projects",
    "api_key = os.environ['X']", 'api_key = os.getenv("API_KEY")', "secret=settings.SECRET_KEY",
    "password: process.env.DB_PASSWORD", "password=${DB_PASSWORD}", "password: required",
])
def test_ordinary_text_is_not_secret(text):
    assert private.secret_like(text) == []


def test_secret_like_needs_a_string():
    with pytest.raises(TypeError):
        private.secret_like(None)


def test_submit_warns_secret_like_without_the_value(start, kb):
    key = "ghp_" + "k" * 36
    body = batch(fact(summary_plain={"ru": f"Доступ к щиту — токен {key}"}),
                 links=[{"rel": "depends_on", "src": "@a", "dst": "@a", "note": {"ru": "password=" + "Hunter2024"}}],
                 reason="пароль: " + "Qwerty123!")
    response = post_submit(start(person=True), body)
    found = contract.check(response, "/submit", "post") if response.status_code == 200 else response.json()
    secrets = [(w["code"], w["ref"], w["path"]) for w in found["warnings"] if w["code"] == "secret_like"]
    assert ("secret_like", "@a", "summary_plain.ru") in secrets
    assert ("secret_like", "", "reason") in secrets
    assert key not in response.text and "Hunter2024" not in response.text and "Qwerty123!" not in response.text
    assert all("токен GitHub" in w["message"] for w in found["warnings"] if w["path"] == "summary_plain.ru")


def test_submit_with_secret_is_written_not_rejected(start, kb):
    body = batch(fact(summary_plain={"ru": "Ключ " + "AKIA" + "Z" * 16 + " — от бакета"}))
    found = contract.check(post_submit(start(person=True), body), "/submit", "post")
    assert [r["status"] for r in found["records"]] == ["verified"]
    assert [(w["code"], w["ref"], w["path"]) for w in found["warnings"]] == [("secret_like", "@a",
                                                                             "summary_plain.ru")]
    assert "AKIA" in kb.execute("SELECT payload->'summary_plain'->>'ru' FROM atom_revision").fetchone()[0]


def test_private_text_is_not_checked_for_secrets(start, kb):
    body = batch(fact(summary_plain={"ru": "Кронштейн держится на одном анкере. <private>" + AWS + "</private>"}))
    found = contract.check(post_submit(start(person=True), body), "/submit", "post")
    assert [w["code"] for w in found["warnings"]] == ["private_removed"]
