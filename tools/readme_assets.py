"""Баннер README: docs/assets/readme/banner-{light,dark}.svg — знак amem и созвездие в цветах веб-UI.

Цвета — токены веб-UI (docs/superpowers/specs/2026-11-06-amem-subproject-5-web-ui-design.md, разд. 4.2),
переведённые из OKLCH в hex. Звёзды раскладываются детерминированно (random.Random(seed)), поэтому повторный
запуск даёт те же файлы. Снимки экрана — настоящие, их снимает workflow readme-shots (docs/assets/readme/README.md).
Запуск из корня репозитория: python3 tools/readme_assets.py ."""
import math
import random
import sys
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans', 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

THEMES = {
    "light": dict(paper="#f4f6f8", surface="#ffffff", panel2="#eff0f3", panel3="#e5e6e9", ink="#181b20",
                  muted="#656970", sep="#e0e1e4", border="#c9cacd", press="#181b20", press_text="#ffffff",
                  sky="#0b0f19", sky2="#131823", sky_text="#e1e5eb", sky_text2="#989fab", sky_panel="#1a2030",
                  src="#2a78d6", work="#eb6834", obj="#1baf7a", mark="#f7e59f", success="#0a7e3a",
                  warning="#a46400", danger="#c52c2a", select="#dcedff", chip_src="#e1f0ff", chip_work="#ffe9dd",
                  chip_obj="#dcf8ea", term="#0f1218", term_text="#d7dbe2", shadow="0.10"),
    "dark": dict(paper="#08090c", surface="#121418", panel2="#1a1c20", panel3="#222429", ink="#edeef2",
                 muted="#9b9ea6", sep="#24262b", border="#383b3f", press="#edeef2", press_text="#121418",
                 sky="#030409", sky2="#080b13", sky_text="#e1e5eb", sky_text2="#989fab", sky_panel="#10141d",
                 src="#3987e5", work="#d95926", obj="#199e70", mark="#635418", success="#5fc183",
                 warning="#e0a64a", danger="#f0726a", select="#14263d", chip_src="#13253d", chip_work="#33201a",
                 chip_obj="#0f2a22", term="#0b0d11", term_text="#d7dbe2", shadow="0.40"),
}

def rect(x, y, w, h, fill, r=0, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" fill="{fill}" {extra}/>'


def bar(x, y, w, h=10, fill="#000", op=1.0):
    return rect(x, y, w, h, fill, r=h / 2, extra=f'opacity="{op}"')


def text(x, y, s, size, fill, weight=400, anchor="start", mono=False, op=1.0):
    fam = "mono" if mono else "sans"
    return (f'<text x="{x:.1f}" y="{y:.1f}" class="{fam}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" opacity="{op}">{escape(s)}</text>')


# созвездие

def constellation(rng, box, t, n_obj=8, n_atoms=60, selected=True, dust=80, twinkle=0, flash=None, bright=False,
                  labels=True):
    """Звёзды в прямоугольнике box=(x, y, w, h): объекты с кольцом, атомы точками, связи линиями."""
    x0, y0, w, h = box
    objs = []
    tries = 0
    while len(objs) < n_obj and tries < 5000:
        tries += 1
        p = (x0 + w * (0.1 + 0.8 * rng.random()), y0 + h * (0.14 + 0.72 * rng.random()))
        if all(math.dist(p, q) > min(w, h) * 0.26 for q in objs):
            objs.append(p)
    nodes = [dict(x=p[0], y=p[1], kind="obj", r=7 + 4 * rng.random(), parent=None) for p in objs]
    for i in range(n_atoms):
        pi = rng.randrange(len(objs))
        px, py = objs[pi]
        a = rng.random() * math.tau
        d = min(w, h) * (0.06 + 0.16 * rng.random())
        x, y = px + d * math.cos(a), py + d * math.sin(a) * 0.85
        x = min(max(x, x0 + 14), x0 + w - 14)
        y = min(max(y, y0 + 14), y0 + h - 14)
        fam = "src" if rng.random() < 0.56 else "work"
        nodes.append(dict(x=x, y=y, kind=fam, r=2.4 + 1.8 * rng.random(), parent=pi,
                          pending=rng.random() < 0.07))
    edges = []
    for i, n in enumerate(nodes):
        if n["parent"] is not None:
            edges.append((i, n["parent"]))
    atoms = [i for i, n in enumerate(nodes) if n["kind"] != "obj"]
    for i in atoms:
        if rng.random() < 0.35:
            near = sorted(atoms, key=lambda j: math.dist((nodes[i]["x"], nodes[i]["y"]), (nodes[j]["x"], nodes[j]["y"])))
            j = near[1 + rng.randrange(2)]
            edges.append((i, j))
    for i in range(len(objs)):
        near = sorted(range(len(objs)), key=lambda j: math.dist(objs[i], objs[j]))
        edges.append((i, near[1]))
    sel = 0 if selected else None
    if selected:
        cx, cy = x0 + w * 0.46, y0 + h * 0.5
        sel = min(range(len(objs)), key=lambda i: math.dist(objs[i], (cx, cy)))
    neigh = {sel} | {a for a, b in edges if b == sel} | {b for a, b in edges if a == sel} if sel is not None else set()

    out = []
    for _ in range(dust):
        dx, dy = x0 + w * rng.random(), y0 + h * rng.random()
        out.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="{0.5 + 0.8 * rng.random():.2f}" fill="{t["sky_text"]}" '
                   f'opacity="{0.08 + 0.25 * rng.random():.2f}"/>')
    for k in range(twinkle):
        dx, dy = x0 + w * rng.random(), y0 + h * rng.random()
        out.append(f'<circle class="tw" style="animation-delay:{-rng.random() * 5:.2f}s" cx="{dx:.1f}" cy="{dy:.1f}" '
                   f'r="{0.9 + 0.7 * rng.random():.2f}" fill="{t["sky_text"]}"/>')
    for a, b in edges:
        na, nb = nodes[a], nodes[b]
        hot = sel is not None and (a == sel or b == sel)
        op = 0.55 if hot else (0.22 if bright else 0.13)
        out.append(f'<line x1="{na["x"]:.1f}" y1="{na["y"]:.1f}" x2="{nb["x"]:.1f}" y2="{nb["y"]:.1f}" '
                   f'stroke="{t["sky_text"]}" stroke-width="{1.2 if hot else 1}" opacity="{op}"/>')
    for i, n in enumerate(nodes):
        dim = sel is not None and i not in neigh
        op = 0.55 if dim else 1
        col = t[n["kind"]]
        if n["kind"] == "obj":
            out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"] + 5:.1f}" fill="none" '
                       f'stroke="{col}" stroke-width="1.5" opacity="{0.5 * op:.2f}"/>')
            out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"]:.1f}" fill="{col}" opacity="{op}"/>')
        else:
            out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"]:.1f}" fill="{col}" opacity="{op}"/>')
            if n.get("pending"):
                out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"] + 5:.1f}" fill="none" '
                           f'stroke="{t["sky_text"]}" stroke-width="1.2" stroke-dasharray="3 3" opacity="{0.7 * op:.2f}"/>')
    if sel is not None:
        n = nodes[sel]
        out.append(f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"] + 10:.1f}" fill="none" '
                   f'stroke="{t["sky_text"]}" stroke-width="2"/>')
    # подписи объектов — полосы, не имена: заглушка не выдумывает данные
    for i, n in enumerate(nodes):
        if n["kind"] == "obj" and labels:
            lw = 54 + 50 * rng.random()
            lx = n["x"] + n["r"] + 12
            if lx + lw > x0 + w - 8:
                lx = n["x"] - n["r"] - 12 - lw
            out.append(bar(lx, n["y"] - 4, lw, 8, t["sky_text"], 0.55 if (sel is None or i in neigh) else 0.3))
    if flash:
        n = nodes[flash % len(nodes)] if isinstance(flash, int) else flash
        out.append(f'<circle class="flash" cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="8" fill="none" '
                   f'stroke="{t["sky_text"]}" stroke-width="2"/>')
    return "\n".join(out), nodes


def sky_window(x, y, w, h, t, r, gid):
    grad = (f'<radialGradient id="{gid}" cx="50%" cy="45%" r="75%">'
            f'<stop offset="0" stop-color="{t["sky2"]}"/><stop offset="1" stop-color="{t["sky"]}"/></radialGradient>')
    return grad, rect(x, y, w, h, f"url(#{gid})", r=r)


def style(extra=""):
    return (f'<style>.sans{{font-family:{FONT}}}.mono{{font-family:{MONO}}}'
            '@keyframes tw{0%,100%{opacity:.18}50%{opacity:.95}}'
            '.tw{animation:tw 4.8s ease-in-out infinite}'
            '@keyframes flash{0%{transform:scale(.6);opacity:.95}70%{opacity:0}100%{transform:scale(3.4);opacity:0}}'
            '.flash{transform-box:fill-box;transform-origin:center;animation:flash 5.2s ease-out infinite}'
            '@media (prefers-reduced-motion:reduce){.tw,.flash{animation:none}.flash{opacity:0}}'
            f'{extra}</style>')


def svg(w, h, title, body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{escape(title)}"><title>{escape(title)}</title>{style()}<defs>{defs}</defs>{body}</svg>\n')


# баннер

def banner(theme):
    t = THEMES[theme]
    rng = random.Random(7)
    BW, BH = 1600, 400
    defs, sky = sky_window(700, 28, 872, 344, t, 22, "bsky")
    defs += '<clipPath id="bclip"><rect x="700" y="28" width="872" height="344" rx="22"/></clipPath>'
    stars, nodes = constellation(rng, (720, 40, 832, 320), t, n_obj=8, n_atoms=64, selected=True, dust=120,
                                 twinkle=18, flash=23, bright=True, labels=False)
    paper = t["paper"] if theme == "light" else t["surface"]
    edge = t["sep"] if theme == "light" else t["border"]
    body = [rect(0.75, 0.75, BW - 1.5, BH - 1.5, paper, r=28, extra=f'stroke="{edge}" stroke-width="1.5"'),
            sky, f'<g clip-path="url(#bclip)">{stars}</g>',
            rect(700, 28, 872, 344, "none", r=22, extra='stroke="#ffffff14" stroke-width="1.5"'),
            text(92, 222, "amem", 132, t["ink"], weight=600),
            text(98, 282, "another memory", 30, t["muted"]),
            # три семьи знания — точки-подписи под знаком
            f'<circle cx="104" cy="327" r="6" fill="{t["src"]}"/>',
            f'<circle cx="124" cy="327" r="6" fill="{t["work"]}"/>',
            f'<circle cx="144" cy="327" r="6" fill="{t["obj"]}"/>']
    return svg(BW, BH, "amem — another memory", "\n".join(body), defs)


def main(root: Path):
    out = root / "docs" / "assets" / "readme"
    out.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        path = out / f"banner-{theme}.svg"
        path.write_text(banner(theme), encoding="utf-8")
        print(path.relative_to(root), path.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
