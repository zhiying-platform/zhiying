"""把用户选定的 Logo 位图（印章版知映）矢量化为 SVG。v2：点数组直传，无字符串解析。

分色：红层（印章体+落款小方）、黑层（映字 + Zhi Ying 文字）。
白文「知」是红层的镂空（RETR_CCOMP + evenodd 自动成孔）。
3x 放大后描摹再缩回，保留钤印粗糙边缘的有机质感。
"""
from __future__ import annotations

import os

import cv2
import numpy as np

SRC = os.environ.get("ZHIYING_LOGO_SOURCE", os.path.join(os.path.dirname(__file__), "final", "seal-source.png"))
OUT = os.path.join(os.path.dirname(__file__), "final", "zhiying-logo.svg")
UP = 6
MIN_AREA = 90  # 放大坐标系下的最小轮廓面积
EPS = 0.4  # 极小 epsilon：保留书法曲线，勿放大


def trace_points(mask: np.ndarray) -> tuple[list[np.ndarray], tuple[int, int, int, int]]:
    """轮廓 → 点数组列表（保留孔洞层级）；返回 (contours, bbox)。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    kept: list[np.ndarray] = []
    bx0 = by0 = 10**9
    bx1 = by1 = -1
    for c in contours:
        if cv2.contourArea(c) < MIN_AREA:
            continue
        ap = cv2.approxPolyDP(c, EPS, True)
        pts = ap.reshape(-1, 2)
        if len(pts) < 3:
            continue
        kept.append(pts)
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        bx0, by0, bx1, by1 = min(bx0, int(x0)), min(by0, int(y0)), max(bx1, int(x1)), max(by1, int(y1))
    return kept, (bx0, by0, bx1, by1)


def build_path(contours: list[np.ndarray], ox: int, oy: int) -> str:
    """点数组 → SVG path d（坐标已平移缩放到 viewBox）。"""
    parts: list[str] = []
    for pts in contours:
        s = (pts - np.array([ox, oy])) / UP
        d = f"M {s[0][0]:.2f} {s[0][1]:.2f}"
        for px, py in s[1:]:
            d += f" L {px:.2f} {py:.2f}"
        d += " Z"
        parts.append(d)
    return " ".join(parts)


def main() -> None:
    src = cv2.imread(SRC, cv2.IMREAD_COLOR)
    assert src is not None, "源图读取失败"
    h, w = src.shape[:2]
    img = cv2.resize(src, (w * UP, h * UP), interpolation=cv2.INTER_CUBIC)
    img = cv2.GaussianBlur(img, (5, 5), 0)

    b = img[..., 0].astype(int)
    g = img[..., 1].astype(int)
    r = img[..., 2].astype(int)
    mx = np.maximum(np.maximum(b, g), r)

    # 红层：红主导（印章体 + 落款小方块）
    red = ((r > 110) & (r - np.maximum(g, b) > 45)).astype(np.uint8) * 255
    # 黑层：暗像素（映字 + Zhi Ying 文字）
    black = (mx < 115).astype(np.uint8) * 255
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    black = cv2.morphologyEx(black, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    red_cs, _ = trace_points(red)
    blk_cs, _ = trace_points(black)
    assert red_cs and blk_cs, "分色失败：红层或黑层无轮廓"

    # 全体包围盒（含两层）+ 内边距
    all_pts = np.vstack(red_cs + blk_cs)
    px0, py0 = all_pts.min(axis=0)
    px1, py1 = all_pts.max(axis=0)
    pad = 6 * UP
    px0, py0 = max(0, px0 - pad), max(0, py0 - pad)

    red_d = build_path(red_cs, px0, py0)
    blk_d = build_path(blk_cs, px0, py0)
    vw = (px1 - px0) / UP
    vh = (py1 - py0) / UP

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw:.0f} {vh:.0f}">\n'
        f"  <path d=\"{red_d}\" fill=\"#E02020\" fill-rule=\"evenodd\"/>\n"
        f"  <path d=\"{blk_d}\" fill=\"#1a1a1a\" fill-rule=\"evenodd\"/>\n"
        "</svg>\n"
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"SVG 已生成: {OUT}  viewBox=0 0 {vw:.0f} {vh:.0f}")
    print(f"red path {len(red_d)} chars | black path {len(blk_d)} chars")


if __name__ == "__main__":
    main()
