#!/usr/bin/env python3
"""Check commit messages: Conventional Commits, written in English.

    tools/check_commits.py FILE           # commit-msg hook: one message file
    tools/check_commits.py --revs REV...  # every non-merge commit in git rev-list REV... (CI)

Rules:
- the header is `type(scope)!: subject`; type is one of TYPES, the scope and `!` are optional,
  the scope is lowercase (`a-z 0-9 . _ / -`), the subject does not end with a period;
- the header is at most 100 characters and has no Cyrillic;
- a blank line separates the header from the body;
- the body is English too: Cyrillic is allowed only inside `code` or «quotes»
  (file paths, document titles, quoted wording);
- merges, reverts and fixup!/squash!/amend! commits are not checked.
"""
import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")
MAX_HEADER = 100

HEADER = re.compile(r"(?P<type>\w+)(?:\((?P<scope>[^()]*)\))?(?P<breaking>!)?: (?P<subject>.*)")
SCOPE = re.compile(r"[a-z0-9][a-z0-9._/-]*")
CYRILLIC = re.compile(r"[Ѐ-ԯ]")
QUOTED = re.compile(r"`[^`\n]*`|«[^»\n]*»")
SKIPPED = re.compile(r"Merge |Revert \"|fixup! |squash! |amend! ")
SCISSORS = "# ------------------------ >8 ------------------------"


def message_lines(text: str, strip_comments: bool) -> list[str]:
    """Lines of the message as git stores it: no editor comments, no blank lines around."""
    lines = []
    for line in text.splitlines():
        if strip_comments and line.startswith(SCISSORS):
            break
        if strip_comments and line.startswith("#"):
            continue
        lines.append(line.rstrip())
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def problems(text: str, strip_comments: bool = False) -> list[str]:
    lines = message_lines(text, strip_comments)
    if not lines:
        return ["the message is empty"]
    header = lines[0]
    if SKIPPED.match(header):
        return []
    m = HEADER.fullmatch(header)
    if not m:
        return [f"the header must look like `type(scope): subject`, got: {header}"]
    found = []
    if m["type"] not in TYPES:
        found.append(f"unknown type `{m['type']}`; use one of: {', '.join(TYPES)}")
    if m["scope"] is not None and not SCOPE.fullmatch(m["scope"]):
        found.append(f"the scope `{m['scope']}` must be lowercase: a-z 0-9 . _ / -")
    subject = m["subject"]  # never empty: trailing spaces are stripped, and `feat:` does not match
    if subject != subject.lstrip():
        found.append("the subject has extra spaces before it")
    elif subject.endswith("."):
        found.append("the subject must not end with a period")
    if len(header) > MAX_HEADER:
        found.append(f"the header is {len(header)} characters, at most {MAX_HEADER} allowed;"
                     " move details to the body")
    if CYRILLIC.search(header):
        found.append("the header must be in English (no Cyrillic)")
    if len(lines) > 1 and lines[1]:
        found.append("leave a blank line between the header and the body")
    for n, line in enumerate(lines[1:], start=2):
        if CYRILLIC.search(QUOTED.sub("", line)):
            found.append(f"line {n} is not in English; Cyrillic is allowed only inside `code` or «quotes»")
    return found


def check_file(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        found = problems(f.read(), strip_comments=True)
    if not found:
        return 0
    print("commit message does not follow the convention (tools/check_commits.py):", file=sys.stderr)
    for p in found:
        print(f"  - {p}", file=sys.stderr)
    print(f"the message is kept in {path}; fix it and run: git commit -e -F {path}", file=sys.stderr)
    return 1


def check_revs(revs: list[str]) -> int:
    log = subprocess.run(["git", "log", "-z", "--no-merges", "--format=%H%n%B", *revs],
                         capture_output=True, text=True, encoding="utf-8")
    if log.returncode != 0:
        print(log.stderr.strip(), file=sys.stderr)
        return 2
    bad = total = 0
    for entry in filter(None, log.stdout.split("\0")):
        sha, _, text = entry.partition("\n")
        total += 1
        found = problems(text)
        if found:
            bad += 1
            print(f"{sha[:10]} {text.splitlines()[0] if text.strip() else ''}")
            for p in found:
                print(f"  - {p}")
    print(f"{total} commits checked, {bad} do not follow the convention")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--revs":
        return check_revs(argv[1:])
    if len(argv) == 1 and not argv[0].startswith("-"):
        return check_file(argv[0])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
