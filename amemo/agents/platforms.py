"""Платформы агентов для установщика (спецификация подпроекта 4, разд. 6.2): где лежат настройки и в каком формате.

Форматы сверены с документацией 09.11.2026; своего номера версии у них нет, поэтому версия — дата сверки
(FORMAT у каждой платформы). Расхождение с новой версией агента правится здесь, в одном месте.

Claude Code (https://code.claude.com/docs/en/mcp, …/hooks, …/skills, …/settings; Claude Code 2.1.283):
- MCP глобально — `claude mcp add --scope user --transport stdio --env K=V ИМЯ -- КОМАНДА …`; команда пишет
  в ~/.claude.json, ключ верхнего уровня mcpServers.ИМЯ = {type: stdio, command, args, env};
  проект — .mcp.json в корне ({"mcpServers": {…}}; Claude Code спрашивает одобрения проектных серверов);
- хуки — settings.json (~/.claude/settings.json, проект — .claude/settings.json): hooks.СОБЫТИЕ — список групп
  {matcher?, hooks: [{type: command, command, timeout}]}; timeout — секунды; команда идёт через оболочку;
- навыки — ~/.claude/skills/ИМЯ/SKILL.md и .claude/skills/ИМЯ/SKILL.md; frontmatter name, description;
- CLAUDE_CONFIG_DIR переносит ~/.claude, а с ним и .claude.json;
- Windows: оболочка хука — Git Bash, а без него PowerShell (поле shell — bash | powershell); форма exec —
  command (программа) и args (её аргументы) — идёт без оболочки и одинакова в обоих случаях: на Windows хук
  amemo ставится так. Домашняя папка — %USERPROFILE%.

Codex CLI (https://github.com/openai/codex, rust-v0.165.0: codex-rs/config/src/mcp_types.rs, hook_config.rs,
loader/README.md, ext/skills/src/host_roots.rs; https://developers.openai.com/codex/config-reference):
- MCP — таблица [mcp_servers.ИМЯ] в $CODEX_HOME/config.toml (по умолчанию ~/.codex): command, args, env
  (встроенная таблица); проект — .codex/config.toml, Codex читает его только у доверенного проекта;
- хуки — hooks.json рядом с config.toml ($CODEX_HOME/hooks.json, проект — .codex/hooks.json), формат как
  у Claude Code ({"hooks": {СОБЫТИЕ: [{matcher?, hooks: [{type: command, command, timeout}]}]}}); вывод
  SessionStart и UserPromptSubmit — hookSpecificOutput.additionalContext; формы exec нет: команда идёт через
  $SHELL -lc, а на Windows — через %COMSPEC% /C (cmd.exe; codex-rs/hooks/src/engine/command_runner.rs).
  PreCompact у Codex не превращает stdout в указания к сжатию, поэтому amemo его у Codex не ставит. Новые хуки
  Codex может попросить одобрить;
- инструкции — AGENTS.md ($CODEX_HOME/AGENTS.md, проект — AGENTS.md в корне);
- навыки — ~/.agents/skills/ИМЯ/SKILL.md ($CODEX_HOME/skills — устаревшее место), проект — .agents/skills.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..portable import WINDOWS, home as home_

CLAUDE_FORMAT = "claude-code/2026-11-09"
CODEX_FORMAT = "codex-cli/2026-11-09"
CLAUDE_DOCS = ("https://code.claude.com/docs/en/mcp", "https://code.claude.com/docs/en/hooks",
               "https://code.claude.com/docs/en/skills", "https://code.claude.com/docs/en/settings")
CODEX_DOCS = ("https://developers.openai.com/codex/config-reference", "https://github.com/openai/codex")

SERVER = "amemo"                                 # имя сервера MCP у агента
SKILLS = ("amemo-remember", "amemo-answer", "amemo-verify")
HOOK_TIMEOUT = 5                                # с; бюджет хука 1,5 с (разд. 6.1) — запас на холодный запуск


@dataclass(frozen=True)
class Layout:
    """Файлы одной установки: None — у платформы этого нет (или не в этом месте)."""
    agent: str                      # claude-code | codex
    model: str                      # имя для AMEMO_AS_MODEL и model:… у amemo mcp
    format: str
    project: Path | None
    mcp_json: Path | None = None    # JSON с mcpServers (Claude Code)
    mcp_toml: Path | None = None    # config.toml с [mcp_servers.amemo] (Codex)
    hooks_json: Path | None = None  # settings.json (Claude Code) или hooks.json (Codex)
    hook_events: tuple[str, ...] = ()
    agents_md: Path | None = None
    skills: Path | None = None
    use_cli: bool = False           # MCP глобально — через `claude mcp add`, если команда есть
    hook_form: str = "sh"           # sh — строка для sh -c; exec — command и args без оболочки; cmd — для cmd.exe /C
    notes: tuple[str, ...] = ()     # объявления этой установки (автовыбор, ограничения формата)


AGENTS = ("claude-code", "codex")


def _home(env: Mapping[str, str]) -> Path:
    return home_(env)


def layout(agent: str, env: Mapping[str, str], project: Path | None = None, *,
           windows: bool | None = None) -> Layout:
    """Где и что ставить агенту agent глобально или в проект project; windows — форма хуков для Windows (None —
    по этой машине, WINDOWS)."""
    home = _home(env)
    windows = WINDOWS if windows is None else windows
    if agent == "claude-code":
        form = "exec" if windows else "sh"
        if project is not None:
            return Layout(agent, "claude-code", CLAUDE_FORMAT, project, mcp_json=project / ".mcp.json",
                          hooks_json=project / ".claude" / "settings.json",
                          hook_events=("SessionStart", "UserPromptSubmit", "PreCompact"),
                          skills=project / ".claude" / "skills", hook_form=form,
                          notes=("Claude Code спросит одобрения сервера amemo из .mcp.json проекта",))
        notes = ()
        config_dir = env.get("CLAUDE_CONFIG_DIR", "").strip()
        if config_dir:
            base = Path(config_dir).expanduser()
            user_json = base / ".claude.json"
            notes = (f"CLAUDE_CONFIG_DIR задана: настройки Claude Code — в {base}",)
        else:
            base, user_json = home / ".claude", home / ".claude.json"
        return Layout(agent, "claude-code", CLAUDE_FORMAT, None, mcp_json=user_json,
                      hooks_json=base / "settings.json",
                      hook_events=("SessionStart", "UserPromptSubmit", "PreCompact"),
                      skills=base / "skills", use_cli=True, hook_form=form, notes=notes)
    if agent == "codex":
        events = ("SessionStart", "UserPromptSubmit")
        form = "cmd" if windows else "sh"
        if project is not None:
            return Layout(agent, "codex", CODEX_FORMAT, project, mcp_toml=project / ".codex" / "config.toml",
                          hooks_json=project / ".codex" / "hooks.json", hook_events=events, hook_form=form,
                          agents_md=project / "AGENTS.md", skills=project / ".agents" / "skills",
                          notes=("Codex читает .codex/config.toml и .codex/hooks.json только у доверенного "
                                 "проекта: отметьте проект доверенным в Codex",
                                 "Codex может попросить одобрить новые хуки",))
        codex_home = env.get("CODEX_HOME", "").strip()
        base = Path(codex_home).expanduser() if codex_home else home / ".codex"
        notes = (f"CODEX_HOME задана: настройки Codex — в {base}",) if codex_home else ()
        return Layout(agent, "codex", CODEX_FORMAT, None, mcp_toml=base / "config.toml",
                      hooks_json=base / "hooks.json", hook_events=events, agents_md=base / "AGENTS.md",
                      skills=home / ".agents" / "skills", hook_form=form,
                      notes=notes + ("Codex может попросить одобрить новые хуки",))
    raise ValueError(f"агент {agent!r} не поддерживается: допустимы {', '.join(AGENTS)}")
