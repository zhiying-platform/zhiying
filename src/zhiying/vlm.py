"""VLM 适配器（PRD FR-105，DR-14 拍板首选 LongCat-2.5）。

统一接口：describe_frame(frame_path, prompt) -> str
适配器可配置切换（ZHIYING_VLM_PROVIDER），切换只改配置不改代码。

URL 桥接：LongCat-2.5 API 仅支持 URL 传图/视频（文章取证），本地帧图需先
上传到临时图床换公网地址。图床上传器同样可配置（ZHIYING_IMAGE_UPLOADER）。

端点与模型名均为配置项（base_url 探测记录见 docs/plan/V0.1-PLAN.md B4 段）。
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

import requests

from zhiying.envkeys import getenv


class VLMError(RuntimeError):
    pass


# ---------------------------------------------------------------- 图床上传桥接


def upload_image(frame_path: Path) -> str:
    """本地帧图 → 公网临时 URL。上传器可配置，当前实现 catbox（直链稳定）。

    失败时抛 VLMError，由上层决定降级策略。
    """
    uploader = os.environ.get("ZHIYING_IMAGE_UPLOADER", "catbox")
    if uploader == "catbox":
        try:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                files={"fileToUpload": (frame_path.name, frame_path.open("rb"), _mime(frame_path))},
                data={"reqtype": "fileupload"},
                timeout=60,
            )
            if r.status_code == 200 and r.text.startswith("http"):
                return r.text.strip()
            raise VLMError(f"catbox 上传失败 HTTP {r.status_code}: {r.text[:120]}")
        except requests.RequestException as e:
            raise VLMError(f"catbox 上传异常: {e}") from e
    raise VLMError(f"未知上传器: {uploader}")


def _mime(p: Path) -> str:
    return mimetypes.guess_type(str(p))[0] or "image/jpeg"


# ---------------------------------------------------------------- LongCat 适配器


def _longcat_config() -> tuple[str, str, str]:
    """返回 (base_url, model, api_key)，全部可环境变量覆盖。

    Key 分离（DR-20 混搭模式）：视觉专用 ZHIYING_VLM_LONGCAT_API_KEY
    优先于共享 LONGCAT_API_KEY；两者都未配置时报错。
    """
    base = os.environ.get("ZHIYING_LONGCAT_BASE", "https://api.longcat.chat/openai/v1")
    model = os.environ.get("ZHIYING_LONGCAT_MODEL", "LongCat-2.5")
    key = getenv("ZHIYING_VLM_LONGCAT_API_KEY") or getenv("LONGCAT_API_KEY")
    if not key:
        raise VLMError("未配置 LONGCAT_API_KEY（或视觉专用 ZHIYING_VLM_LONGCAT_API_KEY）")
    return base.rstrip("/"), model, key.strip()


def describe_frame_longcat(frame_path: Path, prompt: str) -> str:
    """LongCat-2.5 视觉调用（base64 内联，无需图床；DR-14 首选）。

    实测（2026-11-10 Key 激活后）：
    - 支持 data:image 内联（文章所述仅 URL 传图已过时）
    - 思考型模型：max_tokens 会被 reasoning_tokens 吃光导致 content 为空
      → 必须 enable_thinking=false（实测生效，content 117 字含双语 OCR）
    """
    base, model, key = _longcat_config()
    b64 = base64.b64encode(Path(frame_path).read_bytes()).decode()
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "enable_thinking": False,  # 关键：关闭思考模式，否则 content 为空
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": 800,
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise VLMError(f"LongCat HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise VLMError(f"LongCat 响应结构异常: {e}: {str(data)[:300]}") from e


def describe_frame_siliconflow(frame_path: Path, prompt: str) -> str:
    """硅基流动视觉调用（Qwen-VL 系，base64 内联，无需图床）。

    LongCat-2.5 适配器保持首选（DR-14）；实测 2026-11-09 SiliconFlow
    Qwen/Qwen3-VL-8B-Instruct 已跑通帧图→描述+OCR 回收闭环，作为默认可用实现。
    """
    key = getenv("ZHIYING_VLM_SILICONFLOW_API_KEY") or getenv("SILICONFLOW_API_KEY")
    if not key:
        raise VLMError("未配置 SILICONFLOW_API_KEY（或视觉专用 ZHIYING_VLM_SILICONFLOW_API_KEY）")
    key = key.strip()
    model = os.environ.get("ZHIYING_SF_VLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    b64 = base64.b64encode(Path(frame_path).read_bytes()).decode()
    resp = requests.post(
        "https://api.siliconflow.cn/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise VLMError(f"SiliconFlow HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise VLMError(f"SiliconFlow 响应结构异常: {e}: {str(data)[:300]}") from e


# ---------------------------------------------------------------- 通用入口


def describe_frame(frame_path: Path, prompt: str | None = None) -> str:
    """统一入口：按 ZHIYING_VLM_PROVIDER 分发（longcat|siliconflow）。

    DR-14 首选 LongCat-2.5；2026-11-10 Key 激活且 enable_thinking=false 打通后
    默认指向 longcat；SiliconFlow Qwen3-VL 保持为可用备选。
    """
    provider = os.environ.get("ZHIYING_VLM_PROVIDER", "longcat")
    prompt = prompt or (
        "请详细描述这张视频截图中的所有可见信息：画面场景、屏幕文字（OCR）、"
        "人物动作、图表/PPT/代码内容（如有）。用中文简洁输出。"
    )
    if provider == "longcat":
        return describe_frame_longcat(Path(frame_path), prompt)
    if provider == "siliconflow":
        return describe_frame_siliconflow(Path(frame_path), prompt)
    raise VLMError(f"未知 VLM provider: {provider}")
