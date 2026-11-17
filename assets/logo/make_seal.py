"""从最终 Logo SVG 提取红章方形变体（favicon/ico 用），并渲染多尺寸 PNG。"""
from __future__ import annotations

import re
import subprocess

SRC = os.path.join(os.path.dirname(__file__), "final", "zhiying-logo.svg")
SEAL = os.path.join(os.path.dirname(__file__), "final", "zhiying-seal.svg")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

svg = open(SRC, encoding="utf-8").read()
m = re.search(r'd="([^"]+)" fill="#E02020"', svg)
assert m, "红层 path 未找到"
red_d = m.group(1)

out = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="4 6 88 88">\n'
    f'  <path d="{red_d}" fill="#E02020" fill-rule="evenodd"/>\n'
    "</svg>\n"
)
open(SEAL, "w", encoding="utf-8").write(out)
print("seal 方形变体已生成")

logo_dir = os.path.join(os.path.dirname(__file__), "final")
for s in (512, 256, 128, 64, 48, 32, 16):
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--screenshot={logo_dir}\\seal-{s}.png", f"--window-size={s},{s}",
         "--default-background-color=00000000",
         "file:///D:/projectMenu/zhiying/assets/logo/final/zhiying-seal.svg"],
        capture_output=True, timeout=60,
    )
import os  # noqa: E402

for f in sorted(os.listdir(logo_dir)):
    if f.startswith("seal-"):
        kb = os.path.getsize(os.path.join(logo_dir, f)) / 1024
        print(f"  {f}: {kb:.1f}KB")
