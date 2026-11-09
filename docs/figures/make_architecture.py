"""Architecture diagram with fixed coordinates -> architecture.svg"""
W, H = 1600, 860
INK, INK2, LINE, RED = "#0b0b0b", "#52514e", "#6f6e69", "#c23b3b"
BLUE, BLUE_BG, ORANGE, ORANGE_BG, GREY_BG = "#2a78d6", "#eef4fc", "#eb6834", "#fdf1eb", "#f4f3ef"
FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"
out = []


def box(x, y, w, h, lines, fill="white", stroke=LINE, dash=None, bold_first=True, size=15, rx=10):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"{d}/>')
    lh = size * 1.32
    y0 = y + h / 2 - (len(lines) - 1) * lh / 2 + size * 0.35
    for i, t in enumerate(lines):
        wgt = ' font-weight="bold"' if (i == 0 and bold_first) else ""
        out.append(f'<text x="{x + w / 2}" y="{y0 + i * lh}" font-size="{size}" text-anchor="middle" fill="{INK}"{wgt}>{t}</text>')


def cyl(x, y, w, h, lines, size=14):
    e = 12
    out.append(f'<path d="M{x},{y + e} L{x},{y + h - e} A{w / 2},{e} 0 0 0 {x + w},{y + h - e} L{x + w},{y + e}" fill="{GREY_BG}" stroke="{LINE}" stroke-width="1.4"/>')
    out.append(f'<ellipse cx="{x + w / 2}" cy="{y + e}" rx="{w / 2}" ry="{e}" fill="{GREY_BG}" stroke="{LINE}" stroke-width="1.4"/>')
    lh = size * 1.32
    y0 = y + h / 2 + e / 2 - (len(lines) - 1) * lh / 2 + size * 0.35
    for i, t in enumerate(lines):
        wgt = ' font-weight="bold"' if i == 0 else ""
        out.append(f'<text x="{x + w / 2}" y="{y0 + i * lh}" font-size="{size}" text-anchor="middle" fill="{INK}"{wgt}>{t}</text>')


def path(points, color=LINE, dash=None, width=1.6, arrow=True):
    d = " ".join(("M" if i == 0 else "L") + f"{px},{py}" for i, (px, py) in enumerate(points))
    da = f' stroke-dasharray="{dash}"' if dash else ""
    mk = f' marker-end="url(#a_{color[1:]})"' if arrow else ""
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{da}{mk}/>')


def label(x, y, lines, color=INK2, anchor="start", size=13, italic=False):
    st = ' font-style="italic"' if italic else ""
    for i, t in enumerate(lines):
        out.append(f'<text x="{x}" y="{y + i * size * 1.3}" font-size="{size}" text-anchor="{anchor}" fill="{color}"{st}>{t}</text>')


def cluster(x, y, w, h, title, stroke, fill, tcolor):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
    out.append(f'<text x="{x + 18}" y="{y + 30}" font-size="16" font-weight="bold" fill="{tcolor}">{title}</text>')


# ---- left: agent ----
box(60, 24, 480, 74, ["Question + schema + hint", "BIRD mini-dev, 300 eval questions"], fill=GREY_BG)
cluster(40, 130, 520, 360, "Agent (A)   src/agent.py", BLUE, BLUE_BG, "#1d5aa3")
box(80, 180, 440, 76, ["gpt-6-luna", "system prompt + Layer 1: prompt_rule (3 rules)"])
box(80, 318, 440, 140, ["Fixed loop policy, at most 4 LLM calls",
                        "oneshot: write once",
                        "retry: fix after an error or a block",
                        "selfcheck: also see result rows, reply OK or fix"])
box(80, 700, 440, 84, ["Scorer (A)", "own read-only connection to the real files", "execution accuracy vs gold SQL"], fill=GREY_BG)

# ---- middle: harness ----
cluster(720, 130, 520, 690, "Harness (B)   src/harness.py", ORANGE, ORANGE_BG, "#b4461c")
label(738, 182, ["execute() → ExecResult"], color="#b4461c", size=14)
box(760, 200, 300, 84, ["Layer 2: allowlist", "sqlglot parses the SQL text", "one SELECT / WITH / UNION only"], size=14)
box(760, 316, 300, 116, ["Open the database", "scratch copy, readonly off: read-write", "otherwise: mode=ro + query_only",
                         "(Layer 3: readonly; safety net", "always on for the real BIRD files)"], size=13)
box(760, 464, 300, 84, ["Layer 4: approval", "SQLite authorizer sees each action", "non-read → human (auto-deny, log)"], size=14)
box(760, 580, 300, 70, ["Execute", "30 s timeout, 1,000-row cap (always on)"], size=14)
box(760, 700, 300, 84, ["ExecResult", "rows, or error, or", "blocked + blocked_by + reason"], fill="#fff8f4", size=14)
path([(910, 284), (910, 316)])
path([(910, 432), (910, 464)])
path([(910, 548), (910, 580)])
path([(910, 650), (910, 700)])
# block pills
for y, txt in [(222, "blocked"), (362, "write fails: blocked"), (486, "denied")]:
    path([(1060, y + 20), (1090, y + 20)], color=RED, dash="5,4")
    out.append(f'<rect x="1092" y="{y + 4}" width="134" height="32" rx="16" fill="white" stroke="{RED}" stroke-width="1.3"/>')
    out.append(f'<text x="1159" y="{y + 25}" font-size="12.5" text-anchor="middle" fill="{RED}">{txt}</text>')
label(1159, 540, ["each block returns an", "ExecResult, blocked = True"], color=RED, anchor="middle", size=11.5, italic=True)

# ---- right: data + attacks ----
box(1290, 24, 290, 110, ["Attack suite (B)", "src/attacks.py", "direct tier: 30 SQL payloads", "agent tier: 9 requests + 16 planted cells"],
    fill=GREY_BG, dash="7,5", size=13.5)
cyl(1300, 480, 270, 120, ["Scratch copies", "student_club + planted", "api_credentials table", "(attacks only, deleted after)"], size=13.5)
cyl(1300, 640, 270, 110, ["Real BIRD databases", "11 SQLite files", "never writable"], size=13.5)

# ---- edges ----
path([(300, 98), (300, 180)])                                   # question -> llm
path([(300, 256), (300, 318)]); label(310, 293, ["SQL"])        # llm -> loop
path([(300, 458), (300, 700)]); label(310, 600, ["final SQL"])  # loop -> scorer
path([(520, 350), (650, 350), (650, 242), (760, 242)])          # loop -> allowlist
label(660, 232, ["every query"], size=12.5)
path([(760, 742), (610, 742), (610, 440), (520, 440)])          # result -> loop
label(598, 640, ["feedback to the model:", "error message, block reason,", "or (selfcheck) 10-row preview,", "60 characters per cell"], anchor="end", size=12.5)
path([(1060, 604), (1262, 604), (1262, 560), (1300, 560)])
label(1072, 596, ["attack runs"], size=12.5)
path([(1060, 630), (1280, 630), (1280, 700), (1300, 700)])
label(1072, 648, ["eval runs"], size=12.5)
path([(1290, 62), (540, 62)], dash="7,5")                       # attacks -> question
label(1270, 52, ["agent tier"], anchor="end", size=12.5)
path([(1330, 134), (1330, 170), (1010, 170), (1010, 200)], dash="7,5")   # attacks -> allowlist
label(1340, 162, ["direct tier"], size=12.5)
path([(1500, 134), (1500, 480)], dash="2,4")                    # attacks -> scratch
label(1510, 300, ["plants data"], size=12.5)

defs = "".join(
    f'<marker id="a_{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in (LINE, RED))
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">'
       f'<defs>{defs}</defs><rect width="100%" height="100%" fill="white"/>' + "".join(out) + "</svg>")
open(__file__.replace("make_architecture.py", "architecture.svg"), "w").write(svg)
print("ok")
