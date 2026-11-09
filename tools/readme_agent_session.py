"""Agent session for the README "Memory for agents" screen: a real MCP client over stdio against `amem mcp`.

Three steps an agent takes — amem_search, amem_get on the best hit, amem_helpful on what it used — with the
arguments and the structured results written to a JSON transcript; web/tools/readme-shots.mjs draws it.
Settings are the service's (AMEM_DSN, AMEM_DATA, AMEM_DOCS, AMEM_PACKS…); run after tools/seed_sample_en.py.
Run: python tools/readme_agent_session.py OUT.json [--query TEXT] [--prompt TEXT]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROMPT = "How accurate is the TH-20 humidity reading near saturation? Cite the source."
QUERY = "TH-20 humidity accuracy"


async def session(query: str) -> list[dict]:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "amem.cli", "mcp", "--agent", "model:claude-code"],
                                   env=dict(os.environ))
    calls: list[dict] = []

    async def call(client, name, **arguments):
        result = await client.call_tool(name, arguments)
        calls.append({"tool": name, "args": arguments, "error": bool(result.is_error),
                      "result": result.structured_content})
        if result.is_error:
            raise SystemExit(f"{name}: {json.dumps(result.structured_content, ensure_ascii=False)}")
        return result.structured_content

    async with Client(params, mode="legacy") as client:
        found = await call(client, "amem_search", query=query, limit=4)
        top = found["items"][0]["ref"]
        await call(client, "amem_get", refs=[top])
        await call(client, "amem_helpful", retrieval_id=found["retrieval_id"], refs=[top])
    return calls


def main(argv=None) -> int:
    import anyio

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--query", default=QUERY)
    ap.add_argument("--prompt", default=PROMPT)
    args = ap.parse_args(argv)
    calls = anyio.run(session, args.query)
    args.out.write_text(json.dumps({"prompt": args.prompt, "calls": calls}, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
    print(f"{args.out}: {len(calls)} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
