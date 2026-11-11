"""调试脚本：烹饪视频 _extract 原始返回。"""
import sys

sys.path.insert(0, r"D:\projectMenu\zhiying\src")

from zhiying.distill import _load_material
from zhiying.llm import _longcat_chat

material, summary = _load_material("BV1GJ411x7t7")
print("材料长度:", len(material))

prompt = (
    "从以下视频转写材料中提取可复用的方法论单元（操作流程/步骤/原则/案例），"
    '输出 JSON {"units":[{"type":"...","title":"...","content":"...","source_ts":秒数}]}，'
    "若无可提取内容 units 返回空数组并加 reason。材料：\n" + material[:20000]
)
raw = _longcat_chat([{"role": "user", "content": prompt}], max_tokens=3000, temperature=0.2)
out = r"D:\projectMenu\zhiying\scripts\debug_gj_raw.txt"
open(out, "w", encoding="utf-8").write(raw)
print("RAW 长度:", len(raw), "| 已存", out)
