"""Figure generators for the chris-code intro teaching deck.

One script, six figures — all conceptual diagrams (no project-data values), so
no provenance captions are needed. Run:

    uv run --python 3.12 python gen_figures.py

Palette + SVG helper are copied from the teaching-deck template so every figure
stays regenerable from this one file.
"""

BLUE = "#1a4a7a"
ORANGE = "#d97706"
GREEN = "#15803d"
RED = "#b91c1c"
GRAY = "#6b7280"
LGRAY = "#d1d5db"
FILL_BLUE = "#eaf1f8"
FILL_GREEN = "#e4f0e6"
FILL_ORANGE = "#fde8cc"
FILL_RED = "#fbe4e4"
FILL_GRAY = "#eef0f2"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SVG:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'font-family="Helvetica,Arial,sans-serif">'
        ]

    def text(self, x, y, s, size=17, fill="#222", anchor="middle",
             weight="normal", style="", mono=False):
        fam = ' font-family="SFMono-Regular,Menlo,monospace"' if mono else ""
        st = f' font-style="{style}"' if style else ""
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}"{st}{fam}>{esc(s)}</text>'
        )

    def rect(self, x, y, w, h, fill="#fff", stroke=GRAY, sw=1.5, rx=8, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
        )

    def line(self, x1, y1, x2, y2, stroke=GRAY, w=1.5, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{w}"{d}/>'
        )

    def arrow(self, x1, y1, x2, y2, stroke=GRAY, w=2.2, head=9, dash=None):
        self.line(x1, y1, x2, y2, stroke=stroke, w=w, dash=dash)
        dx, dy = x2 - x1, y2 - y1
        n = max((dx * dx + dy * dy) ** 0.5, 1e-9)
        ux, uy = dx / n, dy / n
        px, py = -uy, ux
        self.parts.append(
            f'<polygon points="{x2:.1f},{y2:.1f} '
            f'{x2 - head * ux + head * 0.55 * px:.1f},{y2 - head * uy + head * 0.55 * py:.1f} '
            f'{x2 - head * ux - head * 0.55 * px:.1f},{y2 - head * uy - head * 0.55 * py:.1f}" '
            f'fill="{stroke}"/>'
        )

    def poly(self, points, fill="#fff", stroke=GRAY, sw=1.5):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.parts.append(
            f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}"/>'
        )

    def save(self, path):
        self.parts.append("</svg>")
        with open(path, "w") as f:
            f.write("\n".join(self.parts))
        print("wrote", path)


def box(s, x, y, w, h, title, sub=None, fill="#fff", stroke=GRAY,
        tsize=20, ssize=14, tfill="#1a1a2e"):
    s.rect(x, y, w, h, fill=fill, stroke=stroke, sw=2)
    cy = y + h / 2 + (0 if sub is None else -8)
    s.text(x + w / 2, cy + 6, title, tsize, tfill, weight="bold")
    if sub:
        for i, line in enumerate(sub):
            s.text(x + w / 2, cy + 24 + i * 16, line, ssize, GRAY)


# --------------------------------------------------------------------------
# FIG 1 — the pipeline
# --------------------------------------------------------------------------
def fig_pipeline():
    s = SVG(1120, 460)
    s.text(560, 34, "The pipeline: every non-trivial change runs the same path",
           23, BLUE, weight="bold")

    stages = [
        ("Brainstorm", ["settle intent", "(hard gate)"], FILL_BLUE, BLUE),
        ("Lean spec", ["contracts,", "not code"], FILL_BLUE, BLUE),
        ("Lean plan", ["what & where"], FILL_BLUE, BLUE),
        ("Execute", ["coder agent", "per task"], FILL_GREEN, GREEN),
        ("Verify", ["gates before", "“done”"], FILL_ORANGE, ORANGE),
        ("Finish", ["merge / PR"], FILL_GRAY, GRAY),
    ]
    n = len(stages)
    bw, bh, gap = 148, 96, 33
    total = n * bw + (n - 1) * gap
    x0 = (1120 - total) / 2
    y = 150
    centers = []
    for i, (name, sub, fill, stroke) in enumerate(stages):
        x = x0 + i * (bw + gap)
        box(s, x, y, bw, bh, name, sub, fill=fill, stroke=stroke, tsize=21)
        centers.append((x + bw / 2, x, x + bw))
        if i < n - 1:
            ax0 = x + bw
            ax1 = x + bw + gap
            s.arrow(ax0 + 3, y + bh / 2, ax1 - 3, y + bh / 2, stroke=GRAY, w=2.4)

    # phase brackets
    s.text(x0 + (3 * bw + 2 * gap) / 2, y - 22, "DESIGN  —  settle what & why",
           15, BLUE, weight="bold")
    ex = x0 + 3 * (bw + gap)
    s.text(ex + bw / 2, y - 22, "BUILD", 15, GREEN, weight="bold")
    vx = x0 + 4 * (bw + gap)
    s.text(vx + bw / 2, y - 22, "PROVE", 15, ORANGE, weight="bold")

    # intent bookend arc: frozen at brainstorm, re-checked at verify
    bc = centers[0][0]
    vc = centers[4][0]
    arc_y = y + bh + 78
    s.line(bc, y + bh + 6, bc, arc_y, stroke=ORANGE, w=1.8, dash="4,4")
    s.line(vc, y + bh + 6, vc, arc_y, stroke=ORANGE, w=1.8, dash="4,4")
    s.arrow(bc, arc_y, vc, arc_y, stroke=ORANGE, w=1.8)
    s.text((bc + vc) / 2, arc_y + 22,
           "intent ledger  —  frozen in your words at brainstorm, re-checked "
           "against shipped behavior at verify",
           15, ORANGE, style="italic")
    s.text(bc, arc_y - 8, "freeze", 13, ORANGE, anchor="middle")
    s.text(vc, arc_y - 8, "re-check", 13, ORANGE, anchor="middle")

    s.save("pipeline.svg")


# --------------------------------------------------------------------------
# FIG 2 — design-open vs determined
# --------------------------------------------------------------------------
def fig_fork():
    s = SVG(1080, 500)
    s.text(540, 34, "Two kinds of work — routed by one question",
           23, BLUE, weight="bold")

    # start
    box(s, 440, 66, 200, 58, "A change to make", fill="#fff", stroke=GRAY, tsize=20)

    # diamond
    dcx, dcy = 540, 200
    dw, dh = 150, 74
    s.poly([(dcx, dcy - dh), (dcx + dw, dcy), (dcx, dcy + dh), (dcx - dw, dcy)],
           fill=FILL_ORANGE, stroke=ORANGE, sw=2)
    s.text(dcx, dcy - 6, "Is “what to build”", 17, "#1a1a2e", weight="bold")
    s.text(dcx, dcy + 16, "already settled?", 17, "#1a1a2e", weight="bold")
    s.arrow(540, 124, 540, dcy - dh - 2, stroke=GRAY)

    # NO -> design-open -> brainstorming
    s.arrow(dcx - dw, dcy, 250, dcy, stroke=GRAY)
    s.text(dcx - dw - 55, dcy - 10, "NO", 16, RED, weight="bold")
    box(s, 70, dcy - 52, 180, 104, "Design-open",
        ["“what should this be?”", "is still live", "", "→ brainstorming"],
        fill=FILL_BLUE, stroke=BLUE, tsize=19, ssize=14)

    # YES -> determined -> coherent-change
    s.arrow(dcx + dw, dcy, 830, dcy, stroke=GRAY)
    s.text(dcx + dw + 58, dcy - 10, "YES", 16, GREEN, weight="bold")
    box(s, 830, dcy - 52, 180, 104, "Determined",
        ["behavior settled;", "only the “how” is open", "", "→ coherent-change"],
        fill=FILL_GREEN, stroke=GREEN, tsize=19, ssize=14)

    # brainstorming settles design -> becomes determined (dashed down + across)
    s.line(160, dcy + 52, 160, 400, stroke=BLUE, w=1.8, dash="5,4")
    s.arrow(160, 400, 470, 400, stroke=BLUE, w=1.8, dash="5,4")
    s.text(300, 388, "settles the design", 14, BLUE, style="italic")

    # both feed the build
    box(s, 470, 372, 200, 58, "Spec → plan → build",
        fill="#fff", stroke=GRAY, tsize=19)
    s.line(920, dcy + 52, 920, 401, stroke=GREEN, w=1.8, dash="5,4")
    s.arrow(920, 401, 672, 401, stroke=GREEN, w=1.8, dash="5,4")

    s.text(540, 470,
           "Determined ≠ trivial: the behavior is fixed, but many "
           "implementations pass — only one fits the codebase.",
           16, GRAY, style="italic")
    s.save("fork.svg")


# --------------------------------------------------------------------------
# FIG 3 — the defended choice
# --------------------------------------------------------------------------
def fig_defended_choice():
    s = SVG(1000, 600)
    s.text(500, 32, "The defended choice — the engine's signature output",
           23, BLUE, weight="bold")
    s.text(500, 58,
           "Iron Law: research the codebase before proposing. Name only one "
           "candidate? The research isn’t finished.",
           15, GRAY, style="italic")

    bands = [
        ("1", "Reframe", "the 2–3 facts from research that change the "
         "problem — what’s in scope, where the boundary sits"),
        ("2", "Proposed change", "concrete & minimal: what changes, what’s "
         "deleted, what’s deliberately left untouched"),
        ("3", "Correct across every case", "a table over ALL affected cases + "
         "“cases I might be missing, and how I’d find them”"),
        ("4", "Why it’s most coherent", "reuse, idiom-fit, mirrors an existing "
         "strategy, smallest correct blast radius"),
        ("5", "Defense of alternatives", "a real rebuttal of every rejected "
         "candidate — not a one-liner"),
    ]
    x, w = 120, 760
    y0, bh, gap = 92, 78, 12
    for i, (num, title, desc) in enumerate(bands):
        y = y0 + i * (bh + gap)
        s.rect(x, y, w, bh, fill=FILL_BLUE, stroke=BLUE, sw=1.8)
        # number badge
        s.rect(x + 14, y + bh / 2 - 18, 36, 36, fill=BLUE, stroke=BLUE, rx=18)
        s.text(x + 32, y + bh / 2 + 6, num, 20, "#fff", weight="bold")
        s.text(x + 68, y + 30, title, 19, "#1a1a2e", weight="bold", anchor="start")
        s.text(x + 68, y + 54, desc, 14.5, GRAY, anchor="start")

    s.text(500, y0 + 5 * (bh + gap) + 20,
           "The point is not a working diff. It is a defensible one.",
           17, GREEN, weight="bold")
    s.save("defended_choice.svg")


# --------------------------------------------------------------------------
# FIG 4 — dispatch & the intent channel
# --------------------------------------------------------------------------
def fig_dispatch():
    s = SVG(1120, 500)
    s.text(560, 32, "Dispatch is lossless only if the “why” is written down",
           23, BLUE, weight="bold")

    # orchestrator
    box(s, 60, 150, 210, 120, "Orchestrator",
        ["holds the conversation", "— and the intent"],
        fill=FILL_BLUE, stroke=BLUE, tsize=21, ssize=14)

    # brief
    bx, by, bw, bh = 360, 120, 220, 180
    s.rect(bx, by, bw, bh, fill="#fff", stroke=ORANGE, sw=2)
    s.text(bx + bw / 2, by + 26, "The brief", 19, ORANGE, weight="bold")
    s.line(bx + 16, by + 40, bx + bw - 16, by + 40, stroke=LGRAY)
    lines = [
        ("pointers", "“contract built in Task 3 → path”"),
        ("spec §§", "sections to read"),
        ("constraints", "verbatim"),
        ("INTENT", "the outcome to produce"),
    ]
    for i, (k, v) in enumerate(lines):
        yy = by + 66 + i * 30
        hl = k == "INTENT"
        s.text(bx + 18, yy, k + ":", 15, ORANGE if hl else "#1a1a2e",
               anchor="start", weight="bold" if hl else "normal")
        s.text(bx + 108, yy, v, 12.5, GRAY, anchor="start")
    s.arrow(270, 210, bx - 4, 210, stroke=GRAY)

    # coder
    box(s, 690, 150, 210, 120, "Fresh coder agent",
        ["scope-matched;", "no conversation history"],
        fill=FILL_GREEN, stroke=GREEN, tsize=19, ssize=14)
    s.arrow(bx + bw + 4, 210, 686, 210, stroke=GRAY)

    # reads
    s.text(795, 300, "reads → spec, repo, the files it touches", 14, GRAY,
           style="italic")

    # the two-part lesson
    yy = 372
    s.rect(360, yy, 700, 100, fill=FILL_GRAY, stroke=LGRAY, sw=1.5)
    s.text(710, yy + 28, "what & where  →  recoverable by reading",
           17, "#1a1a2e", weight="bold")
    s.text(710, yy + 58, "why  →  recoverable from nothing; it lived in your head",
           17, RED, weight="bold")
    s.text(710, yy + 84,
           "so the brief must carry it — hand over only what & where, and a coder "
           "ships the wrong thing correctly.",
           14, GRAY, style="italic")

    # return leg
    s.text(155, 320, "return leg:", 14, GRAY, weight="bold")
    s.text(155, 342, "reports are compressions.", 13, GRAY)
    s.text(155, 360, "re-read the code slice,", 13, GRAY)
    s.text(155, 378, "don’t trust the summary.", 13, GRAY)
    s.save("dispatch.svg")


# --------------------------------------------------------------------------
# FIG 5 — staged parallelism
# --------------------------------------------------------------------------
def fig_staged():
    s = SVG(1000, 470)
    s.text(500, 32, "Staged parallelism — safety by scheduling, not prohibition",
           22, BLUE, weight="bold")

    def task(x, y, label, files, w=180, fill=FILL_GREEN, stroke=GREEN):
        s.rect(x, y, w, 56, fill=fill, stroke=stroke, sw=1.8)
        s.text(x + w / 2, y + 24, label, 18, "#1a1a2e", weight="bold")
        s.text(x + w / 2, y + 44, files, 12.5, GRAY, mono=True)

    lblx = 70
    # Stage 1
    s.text(lblx, 108, "Stage 1", 17, BLUE, weight="bold", anchor="start")
    task(200, 82, "Task A", "parser.py")
    task(410, 82, "Task B", "cli.py")
    s.text(720, 110, "disjoint files → run in parallel", 14, GREEN, anchor="start",
           style="italic")

    s.line(70, 162, 930, 162, stroke=LGRAY, dash="5,4")
    s.text(500, 178, "barrier: wait for all reviews to pass", 13, GRAY,
           style="italic")

    # Stage 2
    s.text(lblx, 226, "Stage 2", 17, BLUE, weight="bold", anchor="start")
    task(200, 200, "Task C", "parser.py", fill=FILL_ORANGE, stroke=ORANGE)
    s.text(410, 228, "touches parser.py again → must wait for Task A",
           14, ORANGE, anchor="start", style="italic")

    s.line(70, 280, 930, 280, stroke=LGRAY, dash="5,4")
    s.text(500, 296, "barrier", 13, GRAY, style="italic")

    # Stage 3
    s.text(lblx, 344, "Stage 3", 17, BLUE, weight="bold", anchor="start")
    task(200, 318, "Task D", "io.py")
    task(410, 318, "Task E", "types.rs")

    s.text(500, 420,
           "The orchestrator maps each task’s file footprint up front; tasks that "
           "share a file are serialized, the rest run concurrently.",
           15, GRAY, style="italic")
    s.save("staged.svg")


# --------------------------------------------------------------------------
# FIG 6 — the assurance model
# --------------------------------------------------------------------------
def fig_assurance():
    s = SVG(1080, 500)
    s.text(540, 32, "What the gates prove — recall, not a proof of correctness",
           22, BLUE, weight="bold")

    # left: correlated re-reads
    lx = 70
    s.rect(lx, 70, 430, 300, fill=FILL_RED, stroke=RED, sw=1.6)
    s.text(lx + 215, 100, "Correlated re-reads", 20, RED, weight="bold")
    s.text(lx + 215, 124, "same model, distribution, framing", 14, GRAY,
           style="italic")
    for i in range(4):
        yy = 148 + i * 44
        s.rect(lx + 60, yy, 310, 34, fill="#fff", stroke=RED, sw=1.4)
        s.text(lx + 215, yy + 22, ["spec review", "quality review",
               "design review", "another LLM pass"][i], 15, "#1a1a2e")
    s.text(lx + 215, 340, "miss the same things together", 15, RED, weight="bold")
    s.text(lx + 215, 362, "more passes → higher recall, not residual proof",
           13, GRAY, style="italic")

    # right: independent axes
    rx = 580
    s.rect(rx, 70, 430, 300, fill=FILL_GREEN, stroke=GREEN, sw=1.6)
    s.text(rx + 215, 100, "Independent axes", 20, GREEN, weight="bold")
    s.text(rx + 215, 124, "each fails differently", 14, GRAY, style="italic")
    axes = ["deterministic linter (not an LLM)",
            "spec-blind intent re-check",
            "a real failing test",
            "your own read"]
    for i, a in enumerate(axes):
        yy = 148 + i * 44
        s.rect(rx + 40, yy, 350, 34, fill="#fff", stroke=GREEN, sw=1.4)
        s.text(rx + 215, yy + 22, a, 15, "#1a1a2e")
    s.text(rx + 215, 340, "diversity over quantity", 15, GREEN, weight="bold")
    s.text(rx + 215, 362, "decorrelated checks are what actually add assurance",
           13, GRAY, style="italic")

    s.text(540, 430,
           "“Conformance” = does the code match the spec. None of it asks: is "
           "the spec right?",
           16, "#1a1a2e", weight="bold")
    s.text(540, 460,
           "Green means “nothing these lenses caught,” not “nothing is "
           "wrong.” That judgment stays with you.",
           15, GRAY, style="italic")
    s.save("assurance.svg")


# --------------------------------------------------------------------------
# FIG 7 — skills by functional group
# --------------------------------------------------------------------------
def fig_skill_groups():
    s = SVG(1080, 500)
    s.text(540, 34, "25 skills across 8 functional groups", 23, BLUE,
           weight="bold")

    groups = [
        ("Design & planning", 3, "build"),
        ("Execution", 4, "build"),
        ("Change engine", 3, "build"),
        ("Testing", 2, "assure"),
        ("Completion", 2, "assure"),
        ("Review", 5, "assure"),
        ("Quality campaigns", 3, "assure"),
        ("Meta & ops", 3, "meta"),
    ]
    palette = {"build": (FILL_BLUE, BLUE), "assure": (FILL_ORANGE, ORANGE),
               "meta": (FILL_GRAY, GRAY)}
    cols, cw, ch, gx, gy = 4, 236, 118, 20, 24
    x0 = (1080 - (cols * cw + (cols - 1) * gx)) / 2
    y0 = 78
    for i, (name, cnt, kind) in enumerate(groups):
        r, c = divmod(i, cols)
        x, y = x0 + c * (cw + gx), y0 + r * (ch + gy)
        fill, stroke = palette[kind]
        s.rect(x, y, cw, ch, fill=fill, stroke=stroke, sw=2)
        s.text(x + cw / 2, y + 56, str(cnt), 38, stroke, weight="bold")
        s.text(x + cw / 2, y + 90, name, 16, "#1a1a2e", weight="bold")

    ly = y0 + 2 * (ch + gy) + 6
    items = [("build — produce & ship", BLUE, FILL_BLUE),
             ("assure — test / review / debug", ORANGE, FILL_ORANGE),
             ("meta & ops", GRAY, FILL_GRAY)]
    lx = 250
    for label, stroke, fill in items:
        s.rect(lx, ly - 12, 16, 16, fill=fill, stroke=stroke, sw=1.5, rx=4)
        s.text(lx + 24, ly + 2, label, 14, GRAY, anchor="start")
        lx += 235
    s.text(540, ly + 34,
           "13 of the 25 are testing, review, or debugging — assurance "
           "outnumbers authorship even among skills.",
           16, "#1a1a2e", weight="bold")
    s.save("skill_groups.svg")


# --------------------------------------------------------------------------
# FIG 8 — agents: the coder-to-checker ratio
# --------------------------------------------------------------------------
def fig_agent_ratio():
    s = SVG(1080, 500)
    s.text(540, 34, "13 agents — 3 write code, 10 check it", 23, BLUE,
           weight="bold")

    # ratio squares
    n = 13
    sw_, gap = 46, 12
    total = n * sw_ + (n - 1) * gap
    x0 = (1080 - total) / 2
    y = 70
    for i in range(n):
        x = x0 + i * (sw_ + gap)
        if i < 3:
            s.rect(x, y, sw_, sw_, fill=BLUE, stroke=BLUE, sw=1, rx=7)
        else:
            s.rect(x, y, sw_, sw_, fill=ORANGE, stroke=ORANGE, sw=1, rx=7)
    s.text(x0 + 1.5 * sw_ + gap, y + sw_ + 24, "build", 15, BLUE, weight="bold")
    s.text(x0 + 8 * (sw_ + gap) + sw_ / 2, y + sw_ + 24, "assure", 15, ORANGE,
           weight="bold")

    roles = [
        ("Coders", 3, "build", "write the change"),
        ("Quality reviewers", 3, "assure", "principles + bugs"),
        ("Commit-lite gates", 2, "assure", "idiom + lint"),
        ("Design reviewers", 2, "assure", "cohesion / API"),
        ("Conformance pair", 2, "assure", "spec + intent"),
        ("Test-writer", 1, "assure", "bug-hunter"),
    ]
    palette = {"build": (FILL_BLUE, BLUE), "assure": (FILL_ORANGE, ORANGE)}
    cols, cw, ch, gx, gy = 3, 320, 96, 24, 20
    rx0 = (1080 - (cols * cw + (cols - 1) * gx)) / 2
    ry0 = 232
    for i, (name, cnt, kind, sub) in enumerate(roles):
        r, c = divmod(i, cols)
        x, yy = rx0 + c * (cw + gx), ry0 + r * (ch + gy)
        fill, stroke = palette[kind]
        s.rect(x, yy, cw, ch, fill=fill, stroke=stroke, sw=1.8)
        s.text(x + 22, yy + 40, str(cnt), 30, stroke, weight="bold",
               anchor="start")
        s.text(x + 70, yy + 34, name, 17, "#1a1a2e", weight="bold",
               anchor="start")
        s.text(x + 70, yy + 58, sub, 13.5, GRAY, anchor="start")

    s.text(540, ry0 + 2 * (ch + gy) + 8,
           "Every agent is scope-matched by file type — you describe the work, "
           "the routing is mechanical.",
           15, GRAY, style="italic")
    s.save("agent_ratio.svg")


# --------------------------------------------------------------------------
# FIG 9 — lineage from superpowers
# --------------------------------------------------------------------------
def fig_lineage():
    s = SVG(1080, 470)
    s.text(540, 34, "A true superset of superpowers", 23, BLUE, weight="bold")

    # two boxes with an arrow
    box(s, 70, 90, 300, 150, "superpowers",
        ["skills-only", "generic subagents", "fork point: v5.1.0"],
        fill=FILL_GRAY, stroke=GRAY, tsize=22, ssize=15)
    box(s, 710, 90, 300, 150, "chris-code",
        ["+ 11 new skills", "+ 13-agent layer", "coherence engine"],
        fill=FILL_BLUE, stroke=BLUE, tsize=22, ssize=15)
    s.arrow(378, 176, 702, 176, stroke=GREEN, w=3, head=12)
    s.text(540, 143, "every superpowers", 14, GREEN, weight="bold")
    s.text(540, 161, "skill carried over", 14, GREEN, weight="bold")

    # delta chips
    deltas = [("Skills", "14", "25"), ("Agents", "0", "13"), ("Hooks", "1", "0")]
    dw, dgap = 150, 30
    total = len(deltas) * dw + (len(deltas) - 1) * dgap
    x0 = (1080 - total) / 2
    yy = 300
    for i, (label, a, b) in enumerate(deltas):
        x = x0 + i * (dw + dgap)
        s.rect(x, yy, dw, 96, fill="#fff", stroke=LGRAY, sw=1.5)
        s.text(x + dw / 2, yy + 24, label, 15, GRAY)
        grew = int(b) > int(a)
        s.text(x + dw / 2, yy + 66, f"{a} → {b}", 26,
               GREEN if grew else RED, weight="bold")
    s.text(540, 448,
           "Same brainstorm → plan → execute → review → "
           "finish spine; the additions are where it diverges.",
           15, GRAY, style="italic")
    s.save("lineage.svg")


# --------------------------------------------------------------------------
# FIG 10 — the dispatch difference (generic vs scoped agents)
# --------------------------------------------------------------------------
def fig_dispatch_diff():
    s = SVG(1120, 520)
    s.text(560, 34,
           "Quality is baked into who does the work — not a prompt to remember",
           22, BLUE, weight="bold")

    # left column — superpowers
    lx = 70
    s.rect(lx, 70, 480, 400, fill=FILL_GRAY, stroke=GRAY, sw=1.6)
    s.text(lx + 240, 100, "superpowers", 20, "#1a1a2e", weight="bold")
    s.text(lx + 240, 124, "generic subagent, steered per dispatch", 14, GRAY,
           style="italic")
    box(s, lx + 60, 150, 360, 74, "Orchestrator", None, fill="#fff",
        stroke=GRAY, tsize=19)
    s.text(lx + 240, 250, "must hand-write the quality prompt", 15, RED,
           weight="bold")
    s.text(lx + 240, 272, "each time", 15, RED, weight="bold")
    s.arrow(lx + 240, 285, lx + 240, 322, stroke=GRAY, dash="4,4")
    box(s, lx + 90, 328, 300, 84, "generic subagent",
        ["cohesion / idiom / API-design", "— only if the prompt says so"],
        fill="#fff", stroke=LGRAY, tsize=18, ssize=13)
    s.text(lx + 240, 448, "quality depends on what the orchestrator remembers",
           14, RED, style="italic")

    # right column — chris-code
    rx = 590
    s.rect(rx, 70, 460, 400, fill=FILL_BLUE, stroke=BLUE, sw=1.8)
    s.text(rx + 230, 100, "chris-code", 20, BLUE, weight="bold")
    s.text(rx + 230, 124, "scoped agent, mandate built in", 14, GRAY,
           style="italic")
    s.text(rx + 230, 156, "file type → the right agent fires", 14,
           "#1a1a2e", weight="bold")
    # agent card with baked-in prompt
    s.rect(rx + 70, 176, 320, 190, fill="#fff", stroke=BLUE, sw=1.8)
    s.text(rx + 230, 204, "pytorch-coder", 18, BLUE, weight="bold", mono=True)
    s.line(rx + 90, 218, rx + 350, 218, stroke=LGRAY)
    for i, line in enumerate([
        "system prompt already carries:",
        "· review principles internalized",
        "· cohesion + idiom + API design",
        "· passes review on first attempt",
    ]):
        s.text(rx + 90, 244 + i * 30, line, 14,
               "#1a1a2e" if i == 0 else "#37424f", anchor="start",
               weight="bold" if i == 0 else "normal")
    s.text(rx + 230, 402, "quality is a property of who runs the task", 15,
           GREEN, weight="bold")
    s.text(rx + 230, 424, "— it can't be forgotten", 15, GREEN, weight="bold")
    s.text(rx + 230, 452, "all matching reviewers fire additively", 14, GRAY,
           style="italic")
    s.save("dispatch_diff.svg")


if __name__ == "__main__":
    fig_pipeline()
    fig_fork()
    fig_defended_choice()
    fig_dispatch()
    fig_staged()
    fig_assurance()
    fig_skill_groups()
    fig_agent_ratio()
    fig_lineage()
    fig_dispatch_diff()
