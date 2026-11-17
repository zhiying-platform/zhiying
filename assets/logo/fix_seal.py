"""重建 seal SVG v3：红章 + 仅章内黑字（映的笔画被裁剪窗口带入的黑轮廓全部剔除）。

流程：定位印章（最大红连通域）→ 方形裁剪（严格=印章范围+微留白）
     → 分色描摹 → 黑层轮廓按位置过滤（中心必须在印章矩形内）
     → 红(含白文知镂空) + 黑(章内知笔画) 两层 evenodd。
"""
from __future__ import annotations

import cv2
import numpy as np

SRC = r"C:\Users\25333\.openclaw\workspace\media\inbound\openclaw-staged-68e53663-4374-471c-8371-a3d5893ed322\input-image---44716fe7-a8f3-4fff-bb8e-dccb9ab59990.png"
OUT_SEAL = r"D:\projectMenu\zhiying\assets\logo\final\zhiying-seal.svg"
UP = 6
MIN_AREA = 90
EPS = 0.4


def trace(mask: np.ndarray) -> list[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    kept = []
    for c in contours:
        if cv2.contourArea(c) < MIN_AREA:
            continue
        ap = cv2.approxPolyDP(c, EPS, True)
        pts = ap.reshape(-1, 2)
        if len(pts) >= 3:
            kept.append(pts)
    return kept


def build_path(contours: list[np.ndarray], ox: float, oy: float, scale: float) -> str:
    parts: list[str] = []
    for pts in contours:
        s = (pts - np.array([ox, oy])) / scale
        d = f"M {s[0][0]:.2f} {s[0][1]:.2f}"
        for px, py in s[1:]:
            d += f" L {px:.2f} {py:.2f}"
        d += " Z"
        parts.append(d)
    return " ".join(parts)


def main() -> None:
    src = cv2.imread(SRC, cv2.IMREAD_COLOR)
    assert src is not None
    h, w = src.shape[:2]

    # 1) 定位印章：最大红连通域
    b, g, r = src[..., 0].astype(int), src[..., 1].astype(int), src[..., 2].astype(int)
    red_mask = ((r > 110) & (r - np.maximum(g, b) > 45)).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(red_mask, connectivity=8)
    best = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA])
    sx, sy, sw, sh, _ = stats[best]
    print(f"印章: ({sx},{sy}) {sw}x{sh}")

    # 2) 裁剪窗口 = 印章矩形外扩 6px（不含左侧映字区域）
    m = 6
    x0, y0 = max(0, sx - m), max(0, sy - m)
    x1, y1 = min(w, sx + sw + m), min(h, sy + sh + m)
    crop = src[y0:y1, x0:x1]
    print(f"裁剪: ({x0},{y0})..({x1},{y1}) → {crop.shape[1]}x{crop.shape[0]}")

    # 3) 放大 + 分色
    img = cv2.resize(crop, (crop.shape[1] * UP, crop.shape[0] * UP), interpolation=cv2.INTER_CUBIC)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    b, g, r = img[..., 0].astype(int), img[..., 1].astype(int), img[..., 2].astype(int)
    mx = np.maximum(np.maximum(b, g), r)
    red = ((r > 110) & (r - np.maximum(g, b) > 45)).astype(np.uint8) * 255
    black = (mx < 115).astype(np.uint8) * 255
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    black = cv2.morphologyEx(black, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    red_cs = trace(red)
    # 印章矩形（放大坐标系，含 6px 外扩）
    stamp_x0, stamp_y0 = m * UP, m * UP
    stamp_x1, stamp_y1 = (m + sw) * UP, (m + sh) * UP

    # 4) 黑层过滤：只保留中心落在印章矩形内的轮廓（章内的知笔画）
    black_cs_all = trace(black)
    black_cs = []
    for pts in black_cs_all:
        cxp, cyp = pts.mean(axis=0)
        if stamp_x0 - 8 <= cxp <= stamp_x1 + 8 and stamp_y0 - 8 <= cyp <= stamp_y1 + 8:
            black_cs.append(pts)
    print(f"轮廓: 红 {len(red_cs)} | 黑 全部 {len(black_cs_all)} → 章内 {len(black_cs)}")

    vw, vh = crop.shape[1], crop.shape[0]
    red_d = build_path(red_cs, 0, 0, UP)
    blk_d = build_path(black_cs, 0, 0, UP)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vw:.0f}" height="{vh:.0f}" viewBox="0 0 {vw:.2f} {vh:.2f}">\n'
        f'  <path d="{red_d}" fill="#E02020" fill-rule="evenodd"/>\n'
        f'  <path d="{blk_d}" fill="#1a1a1a" fill-rule="evenodd"/>\n'
        "</svg>\n"
    )
    open(OUT_SEAL, "w", encoding="utf-8").write(svg)
    print(f"seal SVG: viewBox=0 0 {vw:.2f} {vh:.2f}")


if __name__ == "__main__":
    main()
