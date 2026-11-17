"""调试脚本：打印 LLM 对 BV1J54W6NELg 材料的原始返回。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from zhiying.distill import _load_material
from zhiying.llm import _longcat_chat

material, summary = _load_material("BV1J54W6NELg")
print("材料长度:", len(material))

prompt = (
    "从以下视频转写材料中提取可复用的方法论单元，输出 JSON {\"units\": [{...}]}。"
    "如果材料中没有可提取的方法论单元（如纯游戏画面无讲解），units 返回空数组并加 reason 字段说明原因。\n\n材料：\n"
    + material[:3000]
)
raw = _longcat_chat([{"role": "user", "content": prompt}], max_tokens=1500, temperature=0.2)
print("=== RAW 原始返回 ===")
print(raw[:800])
