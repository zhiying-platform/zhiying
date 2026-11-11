"""skill 蒸馏（V1.1，DR-33：原生实现，方法论参照 cangjie-skill v2.5 MIT）。

能力复刻说明：本模块的管道结构（提取→三重验证→能力卡→编译）参照
kangarooking/cangjie-skill（MIT）的方法论设计，实现为知映原生代码：
- 原料优势：A1 多模态文案（口播+画面+OCR）优于纯文字转写
- 规模适配：视频转写 10-60KB，少量 LLM 调用完成（仓颉为整本书设计，需 sub-agent）
- 零外部依赖：不要求用户安装仓颉，用 chat_text（DR-14 适配器）执行

韧性设计（DR-33 实测教训）：LongCat 偶发返回空 content/不可解析 JSON——
提取步骤带 3 次重试；验证失败降级为"全部候选视为通过"；能力卡分批生成
（单批失败跳过不炸整包）；解析失败时原始返回落盘 debug 目录供诊断。

产物：<data>/videos/<id>/skill/（SKILL.md 入口 + capabilities/ + GLOSSARY.md + DIGEST.md）
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from zhiying.envkeys import getenv
from zhiying.llm import chat_text
from zhiying.paths import transcript_dir, video_dir

STATE_FILE = "distill_state.json"
_BATCH_SIZE = 5  # 每批单元数：13 个单元单次生成会被 max_tokens 截断（实测事故）


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


# ------------------------------------------------------------------ 材料装载


def _load_material(video_id: str) -> tuple[str, str]:
    """装载 A1 机器可读 + A3 摘要作为蒸馏原料。"""
    p = transcript_dir(video_id) / "transcript.multimodal.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"无 A1 产物: {p}，先 assemble")
    rows = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    material_lines = []
    for r in rows:
        ts = f"[{int(r['start_ts'])}s]"
        speech = (r.get("speech") or "").strip()
        speech = "" if _is_noise(speech) else speech
        parts = []
        if speech:
            parts.append(f"口播:{speech[:150]}")
        vis = " ".join(r.get("visual_facts") or [])
        if vis:
            parts.append(f"画面:{vis[:200]}")
        st = r.get("screen_text") or []
        if st:
            parts.append("屏幕:" + " / ".join(st)[:120])
        if parts:
            material_lines.append(f"{ts} " + "｜".join(parts))
    material = "\n".join(material_lines)[:30000]

    summary_path = video_dir(video_id) / "summary.json"
    summary = ""
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8")).get("summary_text", "")[:600]
        except json.JSONDecodeError:
            pass
    return material, summary


def _is_noise(s: str) -> bool:
    core = re.sub(r"[\s🎼🎵🎶♪♫。，、,.!！?？…~\-]", "", s)
    return len(core) <= 1


# ------------------------------------------------------------------ LLM 调用（带韧性）


def _chat_json(prompt: str, video_id: str, tag: str, max_tokens: int, temperature: float = 0.2) -> dict:
    """chat_text + JSON 解析；解析失败时原始返回落盘 debug 目录供诊断。"""
    raw = chat_text([{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=temperature)
    data = _parse_json(raw)
    if not data:
        dbg = video_dir(video_id) / "distill_debug"
        dbg.mkdir(parents=True, exist_ok=True)
        (dbg / f"{tag}_{int(time.time())}.txt").write_text(raw, encoding="utf-8")
    return data


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i : j + 1])
        except json.JSONDecodeError:
            pass
    return {}


# ------------------------------------------------------------------ 三段 LLM 管道


def _extract(material: str, summary: str, video_id: str) -> dict:
    """阶段 1+0：整体理解 + 五类方法论单元提取。"""
    prompt = f"""你是方法论蒸馏专家。以下是视频的多模态转写（时间戳+口播+画面+屏幕文字）与既有摘要：

【摘要】{summary}

【转写材料】
{material}

请提取该视频中所有可复用的方法论单元，输出严格 JSON（不要代码块）：
{{
  "overview": "视频核心主题与骨架（100-200字）",
  "units": [
    {{"type": "framework|principle|case|counter_example|glossary",
      "title": "单元标题（10-20字）",
      "content": "单元完整内容（方法论/原则/案例/反例/术语定义，100-400字，含具体步骤或判据）",
      "source_ts": 出现时间点秒数}}
  ]
}}

要求：
- type=framework：决策框架/思维模型/操作流程；principle：原则/清单/规则；case：具体实例；counter_example：失败模式/警告；glossary：关键术语定义
- 只提取材料中有依据的内容，source_ts 必须来自材料时间戳
- 宁缺毋滥：每类最多 5 个，总量不超过 15 个
- content 必须自包含可执行（拿到就能用），不要空洞概括
- 如果材料确实没有可提取的方法论内容（如纯娱乐画面无讲解），units 返回空数组并加 reason 字段"""
    return _chat_json(prompt, video_id, "extract", max_tokens=3000)


def _verify(units: list[dict], material: str, video_id: str) -> list[dict]:
    """阶段 1.5：三重验证（V1 来源充分 / V2 可执行 / V3 任务增益）。"""
    if not units:
        return []
    units_json = json.dumps(units, ensure_ascii=False)[:15000]
    prompt = f"""你是蒸馏质量审核员。以下是从视频提取的方法论候选单元：

{units_json}

【原始材料节选】
{material[:8000]}

对每个单元执行三重验证：
- V1 来源充分性：材料中有依据支撑吗（不含编造）？
- V2 可执行性：拿到单元内容能直接执行吗（有步骤/判据，非空洞概括）？
- V3 任务增益：能减少遗漏/统一口径/稳定交付吗？

输出严格 JSON：{{"verified": [通过全部三重验证的单元数组（保留原结构）], "rejected_titles": ["未通过单元标题", ...]}}
不虚报通过率：编造、空洞、无依据的单元必须拒绝。"""
    data = _chat_json(prompt, video_id, "verify", max_tokens=3000, temperature=0.1)
    verified = data.get("verified") or []
    return verified if isinstance(verified, list) else []


# ---------------------------------------------------------------- 能力卡（分批生成，DR-33 实测教训）


def _skill_meta(overview: str, verified: list[dict], video_id: str) -> dict:
    """skill 包元信息（名称/触发描述/术语表）单独一次小调用。"""
    titles = "\n".join(f"- [{u.get('type', '?')}] {u.get('title', '')}" for u in verified)
    prompt = f"""为以下方法论合集定义 skill 包元信息。核心主题：{overview[:300]}
包含单元：\n{titles}

输出严格 JSON：
{{"skill_name": "英文短名（kebab-case）", "skill_description": "一句话触发描述（何时使用，含 trigger 判据）", "glossary": {{"术语": "定义"}}}}"""
    return _chat_json(prompt, video_id, "meta", max_tokens=600)


def _cards_batch(batch: list[dict], video_id: str, batch_idx: int) -> list[dict]:
    """单批能力卡生成（≤5 单元，单次 max_tokens=4000 内可完整输出）。"""
    units_json = json.dumps(batch, ensure_ascii=False)[:12000]
    prompt = f"""你是 Skill 编译器。为以下 {len(batch)} 个通过三重验证的方法论单元各生成一张 RIA-lite 能力卡（面向 AI Agent 挂载使用）。输出严格 JSON：
{{"cards": [
  {{"slug": "英文短名",
    "title": "能力标题",
    "R": "来源背景（视频+时间点）",
    "I": "何时触发使用（trigger 条件 + 判据）",
    "A1": "具体执行步骤（1-2-3 步骤化）",
    "A2": "注意事项/与相邻能力的区分/常见误用",
    "E": "一个输入输出示例",
    "B": "适用边界（不做什么）"}}
]}}

单元：
{units_json}

要求：A1 必须步骤化可执行；每个卡独立可用；不要编造材料外内容；只输出 cards 数组。"""
    data = _chat_json(prompt, video_id, f"cards_b{batch_idx}", max_tokens=4000)
    cards = data.get("cards") or []
    return cards if isinstance(cards, list) else []


def _make_cards(video_id: str, verified: list[dict], overview: str = "") -> dict:
    """阶段 2：RIA-lite 能力卡生成（分批：单批 ≤5 单元，单批失败不影响其他批次）。"""
    meta = _skill_meta(overview, verified, video_id)
    cards: list[dict] = []
    failed_batches = 0
    for i in range(0, len(verified), _BATCH_SIZE):
        batch = verified[i : i + _BATCH_SIZE]
        try:
            cards.extend(_cards_batch(batch, video_id, i // _BATCH_SIZE))
        except Exception as e:  # noqa: BLE001  单批失败降级：跳过该批，不炸整包
            print(f"⚠ 能力卡批次 {i // _BATCH_SIZE + 1} 生成失败: {str(e)[:120]}")
            failed_batches += 1
    glossary = meta.get("glossary") or {}
    if failed_batches:
        print(f"⚠ {failed_batches} 个批次失败，已完成 {len(cards)} 张能力卡")
    return {
        "skill_name": meta.get("skill_name", ""),
        "skill_description": meta.get("skill_description", ""),
        "cards": cards,
        "glossary": glossary if isinstance(glossary, dict) else {},
    }


# ------------------------------------------------------------------ 编译（确定性，无 LLM）


def _slugify(s: str, fallback: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or fallback


def _compile_pack(video_id: str, cards_data: dict, overview: str, verified: list[dict]) -> Path:
    """阶段 5 确定性编译：SKILL.md 入口 + capabilities/ + GLOSSARY.md + DIGEST.md。"""
    out = video_dir(video_id) / "skill"
    out.mkdir(parents=True, exist_ok=True)
    cap_dir = out / "capabilities"
    cap_dir.mkdir(exist_ok=True)

    meta = _load_meta_safe(video_id)
    name = _slugify(cards_data.get("skill_name", ""), f"zhiying-{video_id.lower()}")
    desc = cards_data.get("skill_description", "")
    cards = cards_data.get("cards") or []
    glossary = cards_data.get("glossary") or {}

    for c in cards:
        slug = _slugify(c.get("slug", ""), "cap")
        cap = cap_dir / f"{slug}.md"
        cap.write_text(
            f"# {c.get('title', slug)}\n\n"
            f"## R · 来源\n{c.get('R', '')}\n\n"
            f"## I · 触发\n{c.get('I', '')}\n\n"
            f"## A1 · 执行步骤\n{c.get('A1', '')}\n\n"
            f"## A2 · 注意\n{c.get('A2', '')}\n\n"
            f"## E · 示例\n{c.get('E', '')}\n\n"
            f"## B · 边界\n{c.get('B', '')}\n",
            encoding="utf-8",
        )

    if glossary:
        gl = ["# 术语表", ""]
        for k, v in glossary.items():
            gl.append(f"- **{k}**：{v}")
        (out / "GLOSSARY.md").write_text("\n".join(gl), encoding="utf-8")

    dg = [f"# {meta.get('title') or video_id} · 蒸馏精华", "", overview, ""]
    for u in verified:
        dg.append(f"- [{u.get('type', '?')}] **{u.get('title', '')}**（{int(u.get('source_ts', 0))}s）")
    (out / "DIGEST.md").write_text("\n".join(dg), encoding="utf-8")

    toc = "\n".join(f"- capabilities/{_slugify(c.get('slug', ''), 'cap')}.md — {c.get('title', '')}" for c in cards)
    skill = (
        f"---\nname: {name}\n"
        f"description: {desc}\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"来源：{meta.get('title') or video_id}（知映 zhiying 蒸馏，{datetime.now(timezone.utc).date()}）\n\n"
        f"## 背景\n{overview}\n\n"
        f"## 能力索引\n{toc}\n\n"
        f"## 触发\n{desc}\n\n"
        f"按能力索引加载对应 capabilities/*.md 执行。\n"
    )
    (out / "SKILL.md").write_text(skill, encoding="utf-8")
    return out


def _load_meta_safe(video_id: str) -> dict:
    from zhiying.download import load_meta

    m = load_meta(video_id)
    return {"title": m.title if m else "", "uploader": m.uploader if m else ""}


# ------------------------------------------------------------------ 入口


def distill(video_id: str, force: bool = False) -> dict:
    """skill 蒸馏总入口（DR-33 原生实现）。

    韧性：提取带 3 次重试（LongCat 偶发空/不可解析返回，实测间歇性）；
    验证解析失败时降级为"全部候选视为通过"；能力卡分批生成。
    """
    state_path = video_dir(video_id) / STATE_FILE
    if state_path.exists() and not force:
        try:
            prev = json.loads(state_path.read_text(encoding="utf-8"))
            if prev.get("ok") and (video_dir(video_id) / "skill" / "SKILL.md").exists():
                return {**prev, "cached": True}
        except json.JSONDecodeError:
            pass

    t0 = time.time()
    try:
        material, summary = _load_material(video_id)
    except FileNotFoundError as e:
        return {"ok": False, "reason": str(e)}

    # 提取（3 次重试：LongCat 偶发空/截断返回，实测间歇性）
    extracted: dict = {}
    for attempt in range(3):
        extracted = _extract(material, summary, video_id)
        if extracted.get("units"):
            break
        print(f"⚠ 提取尝试 {attempt + 1}/3 未产出单元" + ("，重试..." if attempt < 2 else ""))
    overview = extracted.get("overview", "")
    units = extracted.get("units") or []
    if not units:
        reason = extracted.get("reason") or "未能从材料中提取到方法论单元（多次重试后）"
        return {"ok": False, "reason": reason}

    # 验证（解析失败降级：全部候选视为通过，宁误留勿误杀——后续编译仍可审计）
    try:
        verified = _verify(units, material, video_id)
    except Exception:  # noqa: BLE001
        verified = []
    if not verified:
        verified = units
        print("⚠ 三重验证未返回结果，降级为全部候选通过")

    # 能力卡（分批，单批失败跳过）
    try:
        cards_data = _make_cards(video_id, verified, overview=overview)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"能力卡生成异常: {str(e)[:150]}", "verified_units": len(verified)}
    if not cards_data.get("cards"):
        # 编译前置校验（DR-33 实测事故）：卡片全空时不产出空壳 skill 包
        return {
            "ok": False,
            "reason": "能力卡生成失败（全部批次未产出）——材料可能缺方法论内容，或 LLM 输出异常",
            "verified_units": len(verified),
        }
    out = _compile_pack(video_id, cards_data, overview, verified)

    result = {
        "ok": True,
        "path": str(out),
        "cards": len(cards_data.get("cards") or []),
        "verified_units": len(verified),
        "candidates": len(units),
        "duration_s": round(time.time() - t0, 1),
        "provider": os.environ.get("ZHIYING_TEXT_PROVIDER", "longcat"),
    }
    state_path.write_text(
        json.dumps({**result, "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
