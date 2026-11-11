"""文本 LLM 统一调用（V0.2，FR-204 / DR-14）。

摘要（A3）与问答（A4）共用此入口；供应商可配置：
    ZHIYING_TEXT_PROVIDER=longcat（默认，DR-14：一个 Key 覆盖全部模型调用）
                       =siliconflow（备选，Qwen3.5 系）

注意：LongCat-2.5 是思考型模型，必须 enable_thinking=false，
否则 reasoning_tokens 吃光 max_tokens 导致 content 为空（实测）。
"""

from __future__ import annotations

import os
import time

import requests

from zhiying.envkeys import getenv


class LLMError(RuntimeError):
    pass


def _longcat_chat(messages: list[dict], max_tokens: int, temperature: float) -> str:
    base = os.environ.get("ZHIYING_LONGCAT_BASE", "https://api.longcat.chat/openai/v1").rstrip("/")
    model = os.environ.get("ZHIYING_LONGCAT_MODEL", "LongCat-2.5")
    # Key 分离（DR-20 混搭模式）：文本专用 ZHIYING_TEXT_LONGCAT_API_KEY 优先于共享 LONGCAT_API_KEY
    key = getenv("ZHIYING_TEXT_LONGCAT_API_KEY") or getenv("LONGCAT_API_KEY")
    if not key:
        raise LLMError("未配置 LONGCAT_API_KEY（或文本专用 ZHIYING_TEXT_LONGCAT_API_KEY）")
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
        json={
            "model": model,
            "enable_thinking": False,  # 思考型模型：关闭否则 content 为空（实测）
            "chat_template_kwargs": {"enable_thinking": False},  # 双保险：vLLM 风格参数，
            # 实测 enable_thinking 单独用时 reasoning_tokens 仍可能出现（复杂任务吃满
            # max_tokens 导致 content 缺失）；chat_template_kwargs 变体实测 reasoning=None
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=240,
    )
    if r.status_code != 200:
        raise LLMError(f"LongCat HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    msg = (data.get("choices") or [{}])[0].get("message", {})
    content = (msg.get("content") or "").strip()
    if not content and msg.get("reasoning_content"):
        # 兜底：思考仍在但未完全压制时，从 reasoning 中救回（最后手段）
        raise LLMError(
            f"LongCat 返回空 content（reasoning {len(msg['reasoning_content'])} 字符吃满 max_tokens）；"
            f"建议增大 max_tokens 或联系供应商"
        )
    try:
        return content
    except (KeyError, IndexError) as e:
        raise LLMError(f"LongCat 响应结构异常: {e}") from e


def _siliconflow_chat(messages: list[dict], max_tokens: int, temperature: float) -> str:
    key = getenv("ZHIYING_TEXT_SILICONFLOW_API_KEY") or getenv("SILICONFLOW_API_KEY")
    if not key:
        raise LLMError("未配置 SILICONFLOW_API_KEY（或文本专用 ZHIYING_TEXT_SILICONFLOW_API_KEY）")
    model = os.environ.get("ZHIYING_TEXT_MODEL", "Qwen/Qwen3.5-9B")
    r = requests.post(
        "https://api.siliconflow.cn/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
        timeout=180,
    )
    if r.status_code != 200:
        raise LLMError(f"SiliconFlow HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"SiliconFlow 响应结构异常: {e}") from e


def chat_text(messages: list[dict], max_tokens: int = 1200, temperature: float = 0.3, retries: int = 2) -> str:
    """统一文本 LLM 入口；免费档 503/超时自动重试（退避 5s/15s）。"""
    provider = os.environ.get("ZHIYING_TEXT_PROVIDER", "longcat")
    fn = _longcat_chat if provider == "longcat" else _siliconflow_chat
    last_err = ""
    for attempt in range(retries + 1):
        try:
            return fn(messages, max_tokens, temperature)
        except (LLMError, requests.RequestException) as e:
            last_err = str(e)[:200]
            # 非瞬时错误（401/400）不重试
            if "401" in last_err or "400" in last_err:
                break
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    raise LLMError(f"文本 LLM 失败（{provider}，重试后）：{last_err}")


def current_provider() -> str:
    return os.environ.get("ZHIYING_TEXT_PROVIDER", "longcat")
