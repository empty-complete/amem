"""Баннер и заглушки снимков экрана для README: docs/assets/readme/{banner-*.svg, en/*.svg, ru/*.svg}.

Цвета — токены веб-UI (docs/superpowers/specs/2026-11-06-amem-subproject-5-web-ui-design.md, разд. 4.2),
переведённые из OKLCH в hex. Звёзды раскладываются детерминированно (random.Random(seed)), поэтому повторный
запуск даёт те же файлы. Заглушки заменяются настоящими снимками по списку docs/assets/readme/README.md.
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

TEXT = {
    "en": dict(
        search="Search memory", review="Review", changes="Changes", write="Write",
        chip="Placeholder · screenshot coming soon",
        fact="Fact", verified="Verified", sources="Sources", links="Links", neighbourhood="Neighbourhood",
        page="Page", waiting="Waiting for you", reject="Reject", confirm="Confirm",
        known="known", missing="missing", conflict="conflict", completeness="Completeness",
        from_sources="From sources", from_work="From work", objects="Objects", pending="Waiting",
        open="Open", note="Note", session="agent session",
        sky=("The sky", "Your whole memory as a living constellation: knowledge from sources in blue,",
             "from work in orange, objects in green. Click a star to open it."),
        record=("A claim next to its proof", "A record reads like a note: properties, a Markdown body",
                "and the quote highlighted on the real page of the source file."),
        queue=("Review in one keystroke", "Agents propose, checks pre-verify, you confirm or reject.",
               "Each item shows the claim, the quote and its neighbourhood."),
        card=("Entity cards", "A profile says which parameters an object needs; the card shows",
              "what is known, missing or in conflict — computed live from atoms."),
        agent=("Memory for agents", "Claude Code and Codex ask amem first: search, fetch only",
               "the records they need, then mark what helped."),
    ),
    "ru": dict(
        search="Поиск по памяти", review="Проверка", changes="Изменения", write="Записать",
        chip="Заглушка · снимок экрана будет позже",
        fact="Факт", verified="Проверено", sources="Источники", links="Связи", neighbourhood="Окрестность",
        page="Стр.", waiting="Ждут решения", reject="Отклонить", confirm="Подтвердить",
        known="известно", missing="нет", conflict="расхождение", completeness="Полнота",
        from_sources="Из источников", from_work="Из работы", objects="Объекты", pending="Ждут решения",
        open="Открыть", note="Заметка", session="сессия агента",
        sky=("Небо", "Вся память — живое созвездие: знание из источников синим,",
             "из работы оранжевым, объекты зелёным. Нажмите на звезду, чтобы открыть."),
        record=("Утверждение рядом с источником", "Запись читается как заметка: свойства, тело в Markdown",
                "и цитата, подсвеченная на настоящей странице файла."),
        queue=("Проверка одним нажатием", "Агенты предлагают, автопроверка сверяет, вы подтверждаете",
               "или отклоняете. В пункте — утверждение, цитата и окрестность."),
        card=("Карточка объекта", "Профиль говорит, какие параметры нужны объекту; карточка показывает,",
              "что известно, чего нет и где расхождение, — собирается из атомов на лету."),
        agent=("Память для агентов", "Claude Code и Codex сначала спрашивают amem: поиск, затем",
               "только нужные записи, затем отметка того, что помогло."),
    ),
}

W, H = 1600, 900


def tw(text: str, size: float) -> float:
    """Примерная ширина строки системного шрифта: кириллица шире латиницы."""
    k = 0.6 if any("а" <= ch.lower() <= "я" for ch in text) else 0.55
    return len(text) * size * k


def rect(x, y, w, h, fill, r=0, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" fill="{fill}" {extra}/>'


def bar(x, y, w, h=10, fill="#000", op=1.0):
    return rect(x, y, w, h, fill, r=h / 2, extra=f'opacity="{op}"')


def text(x, y, s, size, fill, weight=400, anchor="start", mono=False, op=1.0):
    fam = "mono" if mono else "sans"
    return (f'<text x="{x:.1f}" y="{y:.1f}" class="{fam}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" opacity="{op}">{escape(s)}</text>')


def pill(x, y, label, size, fg, bg=None, stroke=None, dot=None, h=None, pad=14, dashed=False):
    h = h or size * 2
    w = tw(label, size) + pad * 2 + (16 if dot else 0)
    s = ""
    st = f'stroke="{stroke}" stroke-width="1.5"' if stroke else ""
    if dashed:
        st += ' stroke-dasharray="5 4"'
    s += rect(x, y, w, h, bg or "none", r=h / 2, extra=st)
    tx = x + pad
    if dot:
        s += f'<circle cx="{x + pad + 4:.1f}" cy="{y + h / 2:.1f}" r="4.5" fill="{dot}"/>'
        tx += 16
    s += text(tx, y + h / 2 + size * 0.35, label, size, fg)
    return s, w


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


# общая рамка экрана приложения

def chrome(t, L):
    s = [rect(0, 0, W, 64, t["surface"]), rect(0, 63, W, 1, t["sep"]),
         text(32, 42, "amem", 24, t["ink"], weight=600)]
    s.append(rect(500, 14, 600, 36, t["panel2"], r=18))
    s.append(f'<circle cx="527" cy="31" r="7" fill="none" stroke="{t["muted"]}" stroke-width="2"/>'
             f'<line x1="532" y1="36" x2="537" y2="41" stroke="{t["muted"]}" stroke-width="2" stroke-linecap="round"/>')
    s.append(text(550, 37, L["search"], 16, t["muted"]))
    s.append(rect(1068, 21, 22, 22, "none", r=6, extra=f'stroke="{t["border"]}" stroke-width="1.5"'))
    s.append(text(1079, 37, "/", 14, t["muted"], anchor="middle", mono=True))
    x = 1140
    s.append(text(x, 38, L["review"], 16, t["ink"]))
    x += tw(L["review"], 16) + 8
    s.append(rect(x, 22, 24, 20, t["panel3"], r=10))
    x += 48
    s.append(text(x, 38, L["changes"], 16, t["ink"]))
    x += tw(L["changes"], 16) + 28
    ww = tw(L["write"], 16) + 36
    s.append(rect(x, 14, ww, 36, t["press"], r=18))
    s.append(text(x + ww / 2, 37, L["write"], 16, t["press_text"], weight=600, anchor="middle"))
    for i in range(3):
        s.append(f'<circle cx="{1548 + i * 8}" cy="32" r="2.2" fill="{t["muted"]}"/>')
    return "\n".join(s)


def label_card(t, L, key, cx=800, cy=470):
    """Табличка заглушки: крупно, чтобы читалась и в сетке README в два столбца (масштаб ~0,27)."""
    title = L[key][0]
    chip_label = L["chip"]
    cyr = any("а" <= ch.lower() <= "я" for ch in title)
    size = min(68, 1060 / (len(title) * (0.68 if cyr else 0.62)))      # жирный шире обычного
    cw = max(len(title) * size * (0.68 if cyr else 0.62) + 140, tw(chip_label, 24) + 160, 640)
    ch = 236
    x, y = cx - cw / 2, cy - ch / 2
    chip_w = tw(chip_label, 24) + 52
    sep_stroke = f'stroke="{t["sep"]}"'
    s = [f'<g filter="url(#shadow)">{rect(x, y, cw, ch, t["surface"], r=24, extra=sep_stroke)}</g>',
         rect(cx - chip_w / 2, y + 36, chip_w, 48, "none", r=24,
              extra=f'stroke="{t["muted"]}" stroke-width="2" stroke-dasharray="8 6"'),
         text(cx, y + 68, chip_label, 24, t["muted"], anchor="middle"),
         text(cx, y + 150 + size * 0.38, title, round(size), t["ink"], weight=600, anchor="middle")]
    return "\n".join(s)


def frame(theme, lang, key, content, extra_defs="", label_at=(800, 470)):
    t, L = THEMES[theme], TEXT[lang]
    defs = (f'<clipPath id="win"><rect width="{W}" height="{H}" rx="22"/></clipPath>'
            f'<filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">'
            f'<feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#000" flood-opacity="{t["shadow"]}"/></filter>'
            + extra_defs)
    body = (f'<g clip-path="url(#win)">{rect(0, 0, W, H, t["paper"])}{content}{chrome(t, L)}</g>'
            + rect(0.75, 0.75, W - 1.5, H - 1.5, "none", r=22, extra=f'stroke="{t["border"]}" stroke-width="1.5"')
            + label_card(t, L, key, *label_at))
    return svg(W, H, f"amem — {L[key][0]} (placeholder)", body, defs)


def lines(x, y, widths, t, gap=22, h=10, op=0.32, fill=None):
    return "\n".join(bar(x, y + i * gap, w, h, fill or t["muted"], op) for i, w in enumerate(widths))


# экраны

def screen_sky(theme, lang):
    t, L = THEMES[theme], TEXT[lang]
    rng = random.Random(11)
    defs, sky = sky_window(0, 64, W, H - 64, t, 0, "sky")
    stars, _ = constellation(rng, (40, 120, 1140, 720), t, n_obj=9, n_atoms=88, dust=160, twinkle=14, flash=40)
    c = [sky, stars]
    c.append(bar(32, 96, 200, 16, t["sky_text"], 0.85))
    c.append(bar(32, 126, 330, 10, t["sky_text2"], 0.6))
    x = 32
    for lab, dot, dashed in ((L["from_sources"], t["src"], False), (L["from_work"], t["work"], False),
                             (L["objects"], t["obj"], False), (L["pending"], None, True)):
        p, pw = pill(x, 152, lab, 14, t["sky_text"], stroke="#ffffff33", dot=dot, h=32)
        c.append(p)
        x += pw + 10
    # карточка выбранной звезды
    px, py, pw_, ph = 1224, 96, 344, 300
    c.append(rect(px, py, pw_, ph, t["sky_panel"], r=14, extra='stroke="#ffffff1a"'))
    p, _ = pill(px + 24, py + 24, L["objects"], 13, t["sky_text"], bg="#ffffff10", dot=t["obj"], h=28)
    c.append(p)
    c.append(bar(px + 24, py + 76, 250, 16, t["sky_text"], 0.85))
    c.append(bar(px + 24, py + 104, 180, 16, t["sky_text"], 0.85))
    c.append(lines(px + 24, py + 144, [290, 260, 210], t, gap=22, op=0.35, fill=t["sky_text2"]))
    p, ow = pill(px + 24, py + 236, L["open"], 14, t["sky_text"], stroke="#ffffff40", h=36, pad=18)
    c.append(p)
    p, _ = pill(px + 24 + ow + 10, py + 236, L["note"], 14, t["sky_text"], stroke="#ffffff40", h=36, pad=18)
    c.append(p)
    # легенда и клавиши
    lx = 32
    for col in (t["src"], t["work"], t["obj"]):
        c.append(f'<circle cx="{lx + 5}" cy="866" r="5" fill="{col}"/>')
        c.append(bar(lx + 18, 862, 90, 8, t["sky_text2"], 0.5))
        lx += 136
    for i, k in enumerate(("/", "N", "?")):
        kx = 1400 + i * 56
        c.append(rect(kx, 852, 26, 26, "none", r=6, extra='stroke="#ffffff40" stroke-width="1.3"'))
        c.append(text(kx + 13, 870, k, 14, t["sky_text2"], anchor="middle", mono=True))
    return frame(theme, lang, "sky", "\n".join(c), defs, label_at=(700, 500))


def note_header(t, L, x, y):
    c = []
    c.append(lines(x, y, [80, 120], t, gap=0, h=8, op=0.3))
    c[-1] = bar(x, y, 70, 8, t["muted"], 0.3) + bar(x + 84, y, 120, 8, t["muted"], 0.3)
    p, pw = pill(x, y + 28, L["fact"], 14, t["ink"], bg=t["chip_src"], dot=t["src"], h=30)
    c.append(p)
    vx = x + pw + 10
    vw = tw(L["verified"], 14) * 1.15 + 50
    c.append(rect(vx, y + 28, vw, 30, "none", r=15, extra=f'stroke="{t["success"]}" stroke-width="1.5"'))
    c.append(f'<path d="M{vx + 15} {y + 43} l5 5 l9 -10" fill="none" stroke="{t["success"]}" stroke-width="2.2" '
             f'stroke-linecap="round" stroke-linejoin="round"/>')
    c.append(text(vx + 34, y + 48, L["verified"], 14, t["success"], weight=600))
    c.append(bar(x, y + 84, 660, 24, t["ink"], 0.85))
    c.append(bar(x, y + 120, 430, 24, t["ink"], 0.85))
    return "\n".join(c)


def screen_record(theme, lang):
    t, L = THEMES[theme], TEXT[lang]
    rng = random.Random(5)
    c = []
    x = 96
    c.append(note_header(t, L, x, 104))
    # свойства: подпись — значение
    y = 292
    for i, vw in enumerate((180, 120, 220, 150)):
        c.append(bar(x, y + i * 44, 120, 9, t["muted"], 0.4))
        c.append(bar(x + 220, y + i * 44 - 2, vw, 12, t["ink"], 0.7))
        c.append(rect(x, y + i * 44 + 22, 760, 1, t["sep"]))
    # тело
    c.append(lines(x, 486, [760, 720, 744, 520], t, gap=24))
    # цитата
    qy = 600
    c.append(rect(x, qy, 760, 112, t["panel2"], r=12))
    c.append(rect(x, qy, 4, 112, t["src"], r=2))
    c.append(bar(x + 28, qy + 26, 640, 10, t["muted"], 0.32))
    c.append(rect(x + 24, qy + 48, 420, 24, t["mark"], r=4))
    c.append(bar(x + 32, qy + 55, 400, 10, t["ink"], 0.6))
    c.append(bar(x + 28, qy + 86, 300, 10, t["muted"], 0.32))
    # виджеты
    c.append(text(x, 760, L["sources"], 16, t["ink"], weight=600))
    c.append(text(x + 400, 760, L["links"], 16, t["ink"], weight=600))
    c.append(rect(x, 776, 360, 76, t["surface"], r=12, extra=f'stroke="{t["sep"]}"'))
    c.append(rect(x + 18, 794, 30, 38, t["panel3"], r=5))
    c.append(bar(x + 64, 798, 190, 10, t["ink"], 0.6) + bar(x + 64, 818, 130, 8, t["muted"], 0.35))
    c.append(rect(x + 400, 776, 360, 76, t["surface"], r=12, extra=f'stroke="{t["sep"]}"'))
    c.append(f'<circle cx="{x + 424}" cy="814" r="5" fill="{t["work"]}"/>')
    c.append(bar(x + 440, 798, 170, 10, t["ink"], 0.6) + bar(x + 440, 818, 110, 8, t["muted"], 0.35))
    # справа: страница источника и окрестность
    rx, rw = 948, 556
    c.append(rect(rx, 96, rw, 500, t["surface"], r=14, extra=f'stroke="{t["sep"]}"'))
    c.append(rect(rx + 22, 116, 22, 28, t["panel3"], r=4))
    c.append(bar(rx + 56, 122, 200, 10, t["ink"], 0.6))
    p, _ = pill(rx + rw - 110, 114, f'{L["page"]} 12', 13, t["muted"], bg=t["panel2"], h=28, pad=12)
    c.append(p)
    c.append(rect(rx + 22, 160, rw - 44, 1, t["sep"]))
    # лист документа
    sx, sy, sw, sh = rx + 70, 180, rw - 140, 396
    c.append(rect(sx, sy, sw, sh, t["paper"], r=4, extra=f'stroke="{t["sep"]}"'))
    ly = sy + 34
    c.append(bar(sx + 36, ly, 180, 12, t["ink"], 0.6))
    ly += 34
    for i in range(12):
        w_ = sw - 72 - (rng.random() * 90 if i % 4 != 3 else 160)
        if i == 6:
            c.append(rect(sx + 30, ly - 7, w_ * 0.72 + 12, 22, t["mark"], r=3))
            c.append(bar(sx + 36, ly, w_ * 0.72, 8, t["ink"], 0.55))
        else:
            c.append(bar(sx + 36, ly, w_, 7, t["muted"], 0.28))
        ly += 25
    c.append(text(rx, 632, L["neighbourhood"], 16, t["ink"], weight=600))
    d2, sky = sky_window(rx, 648, rw, 220, t, 14, "nsky")
    stars, _ = constellation(random.Random(3), (rx + 10, 656, rw - 20, 204), t, n_obj=4, n_atoms=26, dust=50)
    c.append(sky)
    c.append(f'<clipPath id="nclip"><rect x="{rx}" y="648" width="{rw}" height="220" rx="14"/></clipPath>')
    c.append(f'<g clip-path="url(#nclip)">{stars}</g>')
    return frame(theme, lang, "record", "\n".join(c), d2, label_at=(800, 450))


def screen_queue(theme, lang):
    t, L = THEMES[theme], TEXT[lang]
    c = [rect(0, 64, 440, H - 64, t["surface"]), rect(440, 64, 1, H - 64, t["sep"])]
    c.append(text(28, 108, L["waiting"], 18, t["ink"], weight=600))
    c.append(rect(28 + tw(L["waiting"], 18) * 1.18 + 12, 92, 28, 22, t["panel3"], r=11))
    x = 28
    for lab, dot in ((L["from_sources"], t["src"]), (L["from_work"], t["work"]), (L["objects"], t["obj"])):
        p, pw = pill(x, 128, lab, 13, t["ink"], stroke=t["border"], dot=dot, h=28, pad=11)
        c.append(p)
        x += pw + 8
    rng = random.Random(9)
    y = 180
    for i in range(9):
        if i == 1:
            c.append(rect(8, y - 2, 424, 76, t["select"], r=10))
        fam = t["src"] if rng.random() < 0.6 else t["work"]
        c.append(f'<circle cx="34" cy="{y + 22}" r="5" fill="{fam}"/>')
        c.append(bar(52, y + 16, 250 + 90 * rng.random(), 11, t["ink"], 0.7))
        c.append(bar(52, y + 42, 120 + 80 * rng.random(), 8, t["muted"], 0.35))
        c.append(rect(340, y + 36, 76, 20, "none", r=10, extra=f'stroke="{t["warning"]}" stroke-width="1.3" opacity="0.8"'))
        c.append(rect(28, y + 72, 396, 1, t["sep"]))
        y += 76
    # пункт
    x = 504
    c.append(note_header(t, L, x, 104))
    c.append(lines(x, 296, [880, 840, 600], t, gap=24))
    qy = 380
    c.append(rect(x, qy, 1000, 104, t["panel2"], r=12))
    c.append(rect(x, qy, 4, 104, t["src"], r=2))
    c.append(bar(x + 28, qy + 24, 820, 10, t["muted"], 0.32))
    c.append(rect(x + 24, qy + 46, 520, 24, t["mark"], r=4))
    c.append(bar(x + 32, qy + 53, 500, 10, t["ink"], 0.6))
    c.append(bar(x + 28, qy + 82, 360, 10, t["muted"], 0.32))
    d2, sky = sky_window(x, 508, 1000, 268, t, 14, "qsky")
    stars, _ = constellation(random.Random(21), (x + 20, 516, 960, 252), t, n_obj=5, n_atoms=34, dust=70)
    c.append(sky)
    c.append(f'<clipPath id="qclip"><rect x="{x}" y="508" width="1000" height="268" rx="14"/></clipPath>')
    c.append(f'<g clip-path="url(#qclip)">{stars}</g>')
    # решение
    c.append(rect(441, 800, W - 441, 100, t["surface"]))
    c.append(rect(441, 800, W - 441, 1, t["sep"]))
    c.append(lines(x, 838, [260], t, gap=0, h=9, op=0.3))
    cw = tw(L["confirm"], 16) + 48
    rw = tw(L["reject"], 16) + 48
    bx = 1504 - cw
    c.append(rect(bx, 826, cw, 44, t["press"], r=22))
    c.append(text(bx + cw / 2, 854, L["confirm"], 16, t["press_text"], weight=600, anchor="middle"))
    c.append(rect(bx - rw - 12, 826, rw, 44, "none", r=22, extra=f'stroke="{t["border"]}" stroke-width="1.5"'))
    c.append(text(bx - rw - 12 + rw / 2, 854, L["reject"], 16, t["ink"], weight=600, anchor="middle"))
    return frame(theme, lang, "queue", "\n".join(c), d2, label_at=(940, 470))


def screen_card(theme, lang):
    t, L = THEMES[theme], TEXT[lang]
    c = []
    x = 96
    c.append(bar(x, 104, 70, 8, t["muted"], 0.3) + bar(x + 84, 104, 120, 8, t["muted"], 0.3))
    p, pw = pill(x, 132, L["objects"], 14, t["ink"], bg=t["chip_obj"], dot=t["obj"], h=30)
    c.append(p)
    c.append(bar(x + pw + 12, 142, 160, 10, t["muted"], 0.35))
    c.append(bar(x, 188, 560, 30, t["ink"], 0.85))
    # полнота
    c.append(text(x, 262, L["completeness"], 15, t["muted"]))
    segs = ((0.58, t["success"]), (0.12, t["danger"]), (0.30, t["panel3"]))
    sx = x
    for frac, col in segs:
        sw = 760 * frac
        c.append(rect(sx, 276, sw - 4, 10, col, r=5))
        sx += sw
    lx = x
    for lab, col in ((L["known"], t["success"]), (L["conflict"], t["danger"]), (L["missing"], t["muted"])):
        c.append(f'<circle cx="{lx + 5}" cy="{311}" r="5" fill="{col}"/>')
        c.append(text(lx + 16, 316, lab, 14, t["muted"]))
        lx += tw(lab, 14) + 44
    # сгруппированные списки
    y = 350
    states = [(L["known"], t["success"]), (L["known"], t["success"]), (L["conflict"], t["danger"]),
              (L["known"], t["success"]), (L["missing"], t["muted"]), (L["known"], t["success"]),
              (L["missing"], t["muted"])]
    rng = random.Random(4)
    for g, n in ((0, 4), (1, 3)):
        c.append(bar(x, y + 4, 140, 10, t["muted"], 0.45))
        y += 26
        c.append(rect(x, y, 760, n * 56, t["surface"], r=14, extra=f'stroke="{t["sep"]}"'))
        for i in range(n):
            lab, col = states[(g * 4 + i) % len(states)]
            ry = y + i * 56
            c.append(bar(x + 22, ry + 24, 150 + 70 * rng.random(), 10, t["ink"], 0.6))
            if lab != L["missing"]:
                c.append(bar(x + 470, ry + 22, 90 + 40 * rng.random(), 13, t["ink"], 0.8))
            c.append(text(x + 738, ry + 34, lab, 14, col, weight=600 if lab == L["conflict"] else 400, anchor="end"))
            if i < n - 1:
                c.append(rect(x + 22, ry + 56, 716, 1, t["sep"]))
        y += n * 56 + 28
    # небо объекта
    rx, rw = 1008, 496
    d2, sky = sky_window(rx, 96, rw, 520, t, 14, "csky")
    stars, _ = constellation(random.Random(17), (rx + 10, 106, rw - 20, 500), t, n_obj=5, n_atoms=40, dust=70)
    c.append(sky)
    c.append(f'<clipPath id="cclip"><rect x="{rx}" y="96" width="{rw}" height="520" rx="14"/></clipPath>')
    c.append(f'<g clip-path="url(#cclip)">{stars}</g>')
    c.append(rect(rx, 636, rw, 232, t["surface"], r=14, extra=f'stroke="{t["sep"]}"'))
    p, _ = pill(rx + 22, 658, L["fact"], 13, t["ink"], bg=t["chip_src"], dot=t["src"], h=28)
    c.append(p)
    c.append(bar(rx + 22, 706, 380, 14, t["ink"], 0.8))
    c.append(lines(rx + 22, 740, [430, 360], t, gap=22))
    p, ow = pill(rx + 22, 804, L["open"], 14, t["ink"], stroke=t["border"], h=36, pad=18)
    c.append(p)
    p, _ = pill(rx + 22 + ow + 10, 804, L["note"], 14, t["ink"], stroke=t["border"], h=36, pad=18)
    c.append(p)
    return frame(theme, lang, "card", "\n".join(c), d2, label_at=(800, 470))


def screen_agent(theme, lang):
    t, L = THEMES[theme], TEXT[lang]
    c = []
    # окно терминала
    x, y, w, h = 96, 104, 1408, 752
    c.append(rect(x, y, w, h, t["term"], r=16, extra='stroke="#ffffff14"'))
    for i, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        c.append(f'<circle cx="{x + 26 + i * 22}" cy="{y + 24}" r="6.5" fill="{col}" opacity="0.85"/>')
    c.append(text(x + w / 2, y + 30, L["session"], 14, "#8b93a1", anchor="middle", mono=True))
    c.append(rect(x, y + 48, w, 1, "#ffffff12"))
    tx = x + 44
    ty = y + 104
    term = t["term_text"]
    c.append(text(tx, ty, "›", 22, "#8b93a1", mono=True))
    c.append(bar(tx + 30, ty - 12, 560, 13, term, 0.75))
    ty += 70
    calls = (("amem_search", t["src"], 300), ("amem_get", t["obj"], 220), ("amem_helpful", t["work"], 260))
    for name, col, aw in calls:
        c.append(f'<circle cx="{tx + 6}" cy="{ty - 7}" r="5" fill="{col}"/>')
        c.append(text(tx + 26, ty, name, 20, term, weight=600, mono=True))
        nx = tx + 26 + len(name) * 12.2
        c.append(text(nx, ty, "(", 20, "#8b93a1", mono=True))
        c.append(bar(nx + 16, ty - 11, aw, 11, "#8b93a1", 0.55))
        c.append(text(nx + 24 + aw, ty, ")", 20, "#8b93a1", mono=True))
        ty += 34
        c.append(text(tx + 26, ty, "└", 18, "#5d6573", mono=True))
        c.append(bar(tx + 52, ty - 10, 420 + (60 if name == "amem_get" else 0), 9, term, 0.32))
        if name == "amem_get":
            ty += 30
            c.append(bar(tx + 52, ty - 10, 520, 9, term, 0.32))
        ty += 54
    # ответ с источником
    c.append(lines(tx, ty, [980, 900, 640], t, gap=28, h=12, op=0.6, fill=term))
    ty += 3 * 28 + 6
    c.append(rect(tx, ty, 360, 30, "none", r=15, extra=f'stroke="{t["src"]}" stroke-width="1.4"'))
    c.append(bar(tx + 16, ty + 11, 320, 8, t["src"], 0.75))
    return frame(theme, lang, "agent", "\n".join(c), label_at=(1080, 300))


SCREENS = {"sky": screen_sky, "record": screen_record, "review": screen_queue, "card": screen_card,
           "agent": screen_agent}


def main(root: Path):
    out = root / "docs" / "assets" / "readme"
    for theme in THEMES:
        (out).mkdir(parents=True, exist_ok=True)
        (out / f"banner-{theme}.svg").write_text(banner(theme), encoding="utf-8")
        for lang in TEXT:
            (out / lang).mkdir(exist_ok=True)
            for name, fn in SCREENS.items():
                (out / lang / f"{name}-{theme}.svg").write_text(fn(theme, lang), encoding="utf-8")
    for p in sorted(out.rglob("*.svg")):
        print(p.relative_to(root), p.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
