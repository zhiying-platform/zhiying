"""把中文字形转为 SVG 矢量路径（不依赖系统字体的字标基础）。

流程：PIL 高位渲染字符(白底黑字) → cv2 轮廓追踪(含内孔, RETR_CCOMP)
     → 路径转 SVG path d（evenodd 填充规则处理镂空）。
输出坐标基于渲染画布，调用方自行平移/缩放放置。
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def char_to_paths(
    text: str,
    font_path: str,
    canvas: int = 1024,
    font_size: int = 780,
) -> tuple[str, float, float]:
    """渲染单行字符并返回 (svg_path_d, 内容宽, 内容高)。

    坐标系：y 向下（SVG 同向），返回前已裁剪到字形包围盒。
    """
    img = Image.new("L", (canvas, canvas), color=255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    # 顶部基线起点；用 anchor 左上以稳定包围
    draw.text((canvas // 2, canvas // 2), text, font=font, fill=0, anchor="mm")
    arr = np.array(img)  # 白底黑字

    # 裁剪到字形包围盒
    ys, xs = np.where(arr < 128)
    if len(xs) == 0:
        raise ValueError("未渲染出字形")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = arr[y0 : y1 + 1, x0 : x1 + 1]

    # 轮廓追踪（RETR_CCOMP：外轮廓+孔洞两层）
    binary = (crop < 128).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    d_parts: list[str] = []
    for c in contours:
        if len(c) < 3:
            continue
        pts = c.reshape(-1, 2)
        d = f"M {pts[0][0]} {pts[0][1]}"
        for px, py in pts[1:]:
            d += f" L {px} {py}"
        d += " Z"
        d_parts.append(d)
    return " ".join(d_parts), float(x1 - x0 + 1), float(y1 - y0 + 1)


def normalize_paths(
    d: str, w: float, h: float, target_h: float, origin_x: float, origin_y: float
) -> str:
    """把 path 平移(原点到 origin)并缩放到目标高度；返回新 d 字符串。

    实现：按 token 解析坐标数字对（M/L 后的 x y），统一变换。
    """
    tokens = d.split()
    out: list[str] = []
    i = 0
    scale = target_h / h
    while i < len(tokens):
        t = tokens[i]
        if t in ("M", "L"):
            x, y = float(tokens[i + 1]), float(tokens[i + 2])
            nx = origin_x + (x - 0) * scale
            ny = origin_y + (y - 0) * scale
            out.append(f"{t} {nx:.2f} {ny:.2f}")
            i += 3
        elif t == "Z":
            out.append("Z")
            i += 1
        else:
            out.append(t)
            i += 1
    return " ".join(out)
