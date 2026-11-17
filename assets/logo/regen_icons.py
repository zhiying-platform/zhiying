"""从修复后的 Logo SVG 重新生成全套图标资源（一次性修复脚本）。

修复内容（2026-11-17）：
1. 源 SVG 游离红块杂点已清除（zhiying-logo.svg / zhiying-seal.svg）
2. 本脚本重渲染 seal-*.png（此前部分尺寸被裁切）
3. 重建 zhiying.ico（此前 ico 帧来自横版 logo 裁切残图）
4. 重渲染 wizard-small.png / wizard-large.png（安装器向导图）
5. 同步 web 端 logo.svg / logo-full.svg / favicon.svg

用法: python assets/logo/regen_icons.py
依赖: Chrome（headless 截图）、Pillow（ico 封装）
"""
from __future__ import annotations

import os
import struct
import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "assets" / "logo" / "final"
WEB_ASSETS = ROOT.parent / "zhiying-web" / "src" / "assets"
WEB_PUBLIC = ROOT.parent / "zhiying-web" / "public"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

SEAL_SVG = FINAL / "zhiying-seal.svg"
LOGO_SVG = FINAL / "zhiying-logo.svg"


def render_svg(svg: Path, out_png: Path, size: tuple[int, int]) -> None:
    """通过 HTML 包装器以任意尺寸渲染 SVG（解决 Chrome 对裸 SVG 尺寸歧义）。"""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        w, h = size
        f.write(
            "<!DOCTYPE html><html><head><style>"
            "html,body{margin:0;padding:0;overflow:hidden}"
            "img{display:block;width:100vw;height:100vh}"
            "</style></head><body>"
            f'<img src="file:///{svg.as_posix()}">'
            "</body></html>"
        )
        wrapper = f.name
    try:
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
             f"--screenshot={out_png}", f"--window-size={w},{h}",
             "--force-device-scale-factor=1", "--default-background-color=00000000",
             # 等待渲染完成（实测无此项时小尺寸截图竞态空白）
             "--virtual-time-budget=2000",
             "file:///" + wrapper.replace("\\", "/")],
            capture_output=True, timeout=60, check=True,
        )
    finally:
        os.unlink(wrapper)


def main() -> None:
    # 1) seal 多尺寸 PNG
    # Chrome 对不同窗口尺寸的 SVG 缩放不一致（实测 256/128 及以下渲染不缩放或空白），
    # 故只做一次 512px 渲染（实测稳定），其余尺寸由 Pillow LANCZOS 缩放。
    master = 512
    render_svg(SEAL_SVG, FINAL / f"seal-{master}.png", (master, master))
    src = Image.open(FINAL / f"seal-{master}.png").convert("RGBA")
    bbox = src.split()[3].getbbox()
    assert bbox and bbox[2] - bbox[0] > master * 0.6, f"512 渲染异常: bbox={bbox}"
    # 裁到内容紧贴 + 居中到正方形画布，保证缩放后印章满幅居中
    side = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    cx, cy = (bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2
    half = side // 2
    pad = int(side * 0.02)
    canvas_box = (
        max(0, cx - half - pad), max(0, cy - half - pad),
        min(master, cx + half + pad), min(master, cy + half + pad),
    )
    content = src.crop(canvas_box)
    for s in (256, 128, 64, 48, 32, 16):
        content.resize((s, s), Image.LANCZOS).save(FINAL / f"seal-{s}.png")
        print(f"  seal-{s}.png (512 渲染 → LANCZOS 缩放)")

    # 2) 重建 zhiying.ico（方形印章，全部帧干净渲染）
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = []
    for s in sizes:
        im = Image.open(FINAL / f"seal-{s}.png").convert("RGBA")
        if im.size != (s, s):
            im = im.resize((s, s), Image.LANCZOS)
        imgs.append(im)
    ico_path = FINAL / "zhiying.ico"
    imgs[-1].save(ico_path, sizes=[(s, s) for s in sizes])
    # 校验帧完整性
    data = ico_path.read_bytes()
    count = struct.unpack("<H", data[4:6])[0]
    for i in range(count):
        w, _, _, _, _, _, size_, offset = struct.unpack("<BBBBHHII", data[6 + i * 16:6 + i * 16 + 16])
        img = Image.open(io.BytesIO(data[offset:offset + size_]))
        print(f"  ico frame {w}x{w}: alpha bbox={img.convert('RGBA').split()[3].getbbox()}")
    print(f"  zhiying.ico 已重建 ({count} 帧)")

    # 3) 安装器向导图（HTML 版式 → PNG）
    render_svg_to_html_png = {
        "wizard-small.html": ("wizard-small.png", (58, 58)),
        "wizard-large.html": ("wizard-large.png", (190, 346)),
    }
    for html, (png, size) in render_svg_to_html_png.items():
        render_svg(FINAL / html, FINAL / png, size)
        print(f"  {png} {Image.open(FINAL / png).size}")

    # 4) 同步 web 端
    (WEB_ASSETS / "logo.svg").write_bytes(SEAL_SVG.read_bytes())
    (WEB_ASSETS / "logo-full.svg").write_bytes(LOGO_SVG.read_bytes())
    (WEB_PUBLIC / "favicon.svg").write_bytes(SEAL_SVG.read_bytes())
    print("  web logo.svg / logo-full.svg / favicon.svg 已同步")

    # 5) 同步后端包内 ico（托盘图标）
    pkg_assets = ROOT / "src" / "zhiying" / "assets"
    pkg_assets.mkdir(exist_ok=True)
    (pkg_assets / "zhiying.ico").write_bytes(ico_path.read_bytes())
    print("  src/zhiying/assets/zhiying.ico 已同步")


if __name__ == "__main__":
    main()
