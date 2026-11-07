"""Образцы графа для части C (небо): обзор базы, окрестности объекта и записи, большая база.

Запуск из web/: python3 tools/make-graph-fixtures.py
"""
import json
import random
from collections import deque
from pathlib import Path

OUT = Path("src/mocks/fixtures")
recs = json.loads((OUT / "records.json").read_text(encoding="utf-8"))["items"]
links = json.loads((OUT / "links-a3.json").read_text(encoding="utf-8"))
P = "0193b7c2-5e1a-7d40-9f2e-0000000000"
E = lambda n: f"ent:{P}{n:02x}"  # noqa: E731
A = lambda n: f"atm:{P}{n:02x}"  # noqa: E731
SOURCE = {"fact", "parameter", "term", "requirement"}


def family(r):
    if r["target"] == "entity":
        return "object"
    return "source" if r["kind_or_class"] in SOURCE else "work"


edges = []
for child in (2, 3, 4, 5):
    edges.append({"src": E(child), "dst": E(1), "rel": "part_of"})
edges += [{"src": E(1), "dst": E(8), "rel": "part_of"}, {"src": E(6), "dst": E(1), "rel": "about"},
          {"src": E(7), "dst": E(2), "rel": "about"}]
for r in recs:
    if r["target"] == "atom":
        for a in r.get("about", []):
            edges.append({"src": r["ref"], "dst": a["ref"], "rel": "about"})
for l in links:
    src, dst = (A(0x0B), l["other"]["ref"]) if l["direction"] == "out" else (l["other"]["ref"], A(0x0B))
    edges.append({"src": src, "dst": dst, "rel": l["rel"]})
edges.append({"src": A(0x12), "dst": A(0x09), "rel": "superseded_by"})
edges.append({"src": A(0x13), "dst": A(0x0A), "rel": "supports"})
for e in edges:
    e["confidence"] = None

deg = {r["ref"]: 0 for r in recs}
for e in edges:
    deg[e["src"]] += 1
    deg[e["dst"]] += 1


def node(r, depth=None):
    n = {"ref": r["ref"], "label": r["label"], "kind_or_class": r["kind_or_class"], "family": family(r),
         "status": r["status"], "pending": r["status"] == "needs_review", "degree": deg[r["ref"]]}
    if depth is not None:
        n["depth"] = depth
    return n


def around(ref, depth):
    adj = {}
    for e in edges:
        adj.setdefault(e["src"], set()).add(e["dst"])
        adj.setdefault(e["dst"], set()).add(e["src"])
    seen = {ref: 0}
    q = deque([ref])
    while q:
        cur = q.popleft()
        if seen[cur] >= depth:
            continue
        for n in adj.get(cur, ()):
            if n not in seen:
                seen[n] = seen[cur] + 1
                q.append(n)
    by = {r["ref"]: r for r in recs}
    nodes = [node(by[k], d) for k, d in seen.items()]
    es = [e for e in edges if e["src"] in seen and e["dst"] in seen]
    return {"ref": ref, "nodes": nodes, "edges": es, "truncated": False, "total": len(nodes)}


base = {"ref": None, "nodes": [node(r) for r in sorted(recs, key=lambda r: -deg[r["ref"]])], "edges": edges,
        "truncated": False, "total": len(recs)}

rnd = random.Random(7)
objs = [{"ref": f"ent:big-{i:02d}", "label": f"Объект {i + 1}", "kind_or_class": "artifact", "family": "object",
         "status": "verified", "pending": False, "degree": 0} for i in range(12)]
atoms = []
big_edges = [{"src": f"ent:big-{i:02d}", "dst": "ent:big-00", "rel": "part_of", "confidence": None} for i in range(1, 12)]
for i in range(408):
    o = rnd.randrange(12)
    fam = rnd.choice(["source", "source", "work"])
    atoms.append({"ref": f"atm:big-{i:03d}", "label": f"Запись {i + 1}", "kind_or_class": "fact" if fam == "source" else "note",
                  "family": fam, "status": "needs_review" if i % 37 == 0 else "verified", "pending": i % 37 == 0, "degree": 1})
    big_edges.append({"src": f"atm:big-{i:03d}", "dst": f"ent:big-{o:02d}", "rel": "about", "confidence": None})
d = {}
for e in big_edges:
    d[e["src"]] = d.get(e["src"], 0) + 1
    d[e["dst"]] = d.get(e["dst"], 0) + 1
for n in objs + atoms:
    n["degree"] = d.get(n["ref"], 0)
kept = sorted(objs + atoms, key=lambda n: -n["degree"])[:300]
keep = {n["ref"] for n in kept}
big = {"ref": None, "nodes": kept, "edges": [e for e in big_edges if e["src"] in keep and e["dst"] in keep],
       "truncated": True, "total": len(objs) + len(atoms)}

files = {"graph-base.json": base, "graph-e3.json": around(E(3), 2), "graph-a3.json": around(A(0x0B), 2), "graph-big.json": big}
for name, data in files.items():
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print({k: (len(v["nodes"]), len(v["edges"])) for k, v in files.items()})
