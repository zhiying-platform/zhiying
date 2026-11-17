"""用真矢量字形生成三个参考图级别的「知映」字标概念 SVG。"""
from __future__ import annotations

import sys

sys.path.insert(0, r"D:\projectMenu\zhiying\assets\logo")
from glyphs import char_to_paths  # noqa: E402

OUT = r"D:\projectMenu\zhiying\assets\logo\concepts"
XINWEI = r"C:\Windows\Fonts\STXINWEI.TTF"
KAITI = r"C:\Windows\Fonts\simkai.ttf"

RED = "#C8102E"
INK = "#171717"
BLUE = "#2563eb"


def glyph_d(text: str, font: str, target_h: float, ox: float, oy: float) -> str:
    d, w, h = char_to_paths(text, font)
    # 平移：字形包围盒左上角 → (ox, oy)
    tokens = d.split()
    out: list[str] = []
    i = 0
    scale = target_h / h
    while i < len(tokens):
        t = tokens[i]
        if t in ("M", "L"):
            x, y = float(tokens[i + 1]), float(tokens[i + 2])
            out.append(f"{t} {ox + x * scale:.2f} {oy + y * scale:.2f}")
            i += 3
        elif t == "Z":
            out.append("Z")
            i += 1
        else:
            out.append(t)
            i += 1
    return " ".join(out)


def glyph_width(text: str, font: str, target_h: float) -> float:
    _, w, h = char_to_paths(text, font)
    return w * (target_h / h)


# ---------- 概念 A：朱方章 + 墨映（参考图2/4：红章白知 + 黑映） ----------
def concept_a() -> str:
    gh = 44.0
    # 红章内白文「知」（居中）
    zw = glyph_width("知", XINWEI, gh)
    zhi = glyph_d("知", XINWEI, gh, 47 - zw / 2, 28)
    # 章外墨色「映」
    yw = glyph_width("映", XINWEI, gh * 1.06)
    ying = glyph_d("映", XINWEI, gh * 1.06, 96, 26)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 100">
  <rect x="14" y="12" width="70" height="70" rx="10" fill="{RED}"/>
  <path d="{zhi}" fill="#ffffff" fill-rule="evenodd"/>
  <path d="{ying}" fill="{INK}" fill-rule="evenodd"/>
  <text x="102" y="92" font-family="Arial" font-size="9" fill="{INK}">Zhi Ying</text>
  <rect x="128" y="83" width="7" height="7" fill="{RED}"/>
</svg>'''


# ---------- 概念 B：朱印竖章（参考图1：竖排红章白文） ----------
def concept_b() -> str:
    gh = 26.0
    # 竖排两字：知 上、映 下（章内白文）
    zhi = glyph_d("知", XINWEI, gh, 50 - glyph_width("知", XINWEI, gh) / 2, 22)
    ying = glyph_d("映", XINWEI, gh, 50 - glyph_width("映", XINWEI, gh) / 2, 56)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 140">
  <rect x="26" y="4" width="48" height="106" rx="5" fill="{RED}"/>
  <rect x="30.5" y="8.5" width="39" height="97" rx="2.5" fill="none" stroke="#fff" stroke-width="1.4"/>
  <path d="{zhi}" fill="#ffffff" fill-rule="evenodd"/>
  <path d="{ying}" fill="#ffffff" fill-rule="evenodd"/>
  <text x="50" y="128" text-anchor="middle" font-family="Arial" font-size="8.5" letter-spacing="2.5" fill="#111">ZHI YING</text>
</svg>'''


# ---------- 概念 C：胶片环映（参考图6：胶片带环绕 + 红黑字） ----------
def concept_c() -> str:
    gh = 30.0
    zw = glyph_width("知", XINWEI, gh)
    yw = glyph_width("映", XINWEI, gh)
    zhi = glyph_d("知", XINWEI, gh, 50 - zw - 3, 52)
    ying = glyph_d("映", XINWEI, gh, 53, 52)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 120">
  <path d="M 24 34 Q 70 10 116 34" fill="none" stroke="{RED}" stroke-width="13"/>
  <path d="M 24 34 Q 70 10 116 34" fill="none" stroke="#fff" stroke-width="13" stroke-dasharray="5 8"/>
  <path d="{zhi}" fill="{INK}" fill-rule="evenodd"/>
  <path d="{ying}" fill="{RED}" fill-rule="evenodd"/>
  <text x="70" y="104" text-anchor="middle" font-family="Arial" font-size="9" letter-spacing="3" fill="#111">— ZHIYING —</text>
  <path d="M 24 88 Q 70 112 116 88" fill="none" stroke="{INK}" stroke-width="13"/>
  <path d="M 24 88 Q 70 112 116 88" fill="none" stroke="#fff" stroke-width="13" stroke-dasharray="5 8"/>
</svg>'''


with open(f"{OUT}\\wa-zhufang.svg", "w", encoding="utf-8") as f:
    f.write(concept_a())
with open(f"{OUT}\\wb-vertical.svg", "w", encoding="utf-8") as f:
    f.write(concept_b())
with open(f"{OUT}\\wc-filmring.svg", "w", encoding="utf-8") as f:
    f.write(concept_c())
print("三个真矢量字标概念已生成")
