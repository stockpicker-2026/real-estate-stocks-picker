"""
腾讯云多模型客户端（DeepSeek V3.2 + GLM-5 + Kimi K2.5 三模型）
- 三个模型均使用 LKEAP OpenAI 兼容接口（Bearer Token）
"""

import logging
from typing import Optional

import httpx

from app.config import (
    DEEPSEEK_MODEL, DEEPSEEK_ENABLED,
    GLM_MODEL, GLM_ENABLED,
    KIMI_MODEL, KIMI_ENABLED,
    LKEAP_API_KEY,
)

logger = logging.getLogger(__name__)

# ── LKEAP OpenAI 兼容接口 ──
LKEAP_OPENAI_BASE = "https://api.lkeap.cloud.tencent.com/v3"


# ========== LKEAP OpenAI 兼容接口通用调用 ==========

async def _call_lkeap_openai(
    model: str,
    prompt: str,
    system: str = "",
    temperature: Optional[float] = None,
    enable_search: bool = False,
    label: str = "",
) -> Optional[str]:
    """调用 LKEAP OpenAI 兼容接口（三模型共用）"""
    if not LKEAP_API_KEY:
        logger.warning(f"未配置 LKEAP_API_KEY，跳过 {label} 调用")
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if enable_search:
        body["enable_search"] = True

    headers = {
        "Authorization": f"Bearer {LKEAP_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{LKEAP_OPENAI_BASE}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                content = msg.get("content", "")
                return content if content else None
            elif "error" in data:
                err = data["error"]
                logger.error(f"{label} API错误: {err}")
                return None
            else:
                logger.error(f"{label} API响应异常: {data}")
                return None
    except Exception as e:
        logger.error(f"调用{label} API失败: {e}")
        return None


# ── DeepSeek V3.2 ──

async def chat_deepseek(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    enable_search: bool = False,
) -> Optional[str]:
    """调用 DeepSeek V3.2（LKEAP OpenAI 兼容接口）"""
    if not DEEPSEEK_ENABLED:
        return None
    return await _call_lkeap_openai(
        model=DEEPSEEK_MODEL,
        prompt=prompt,
        system=system,
        temperature=temperature,
        enable_search=enable_search,
        label="DeepSeek",
    )


async def chat_hunyuan(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    enable_search: bool = False,
) -> Optional[str]:
    """chat_deepseek 的别名，兼容旧版调用"""
    return await chat_deepseek(prompt, system, temperature, enable_search)


# ── GLM-5 ──

async def chat_glm(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
) -> Optional[str]:
    """调用 GLM-5（LKEAP OpenAI 兼容接口）"""
    if not GLM_ENABLED:
        return None
    return await _call_lkeap_openai(
        model=GLM_MODEL,
        prompt=prompt,
        system=system,
        temperature=temperature,
        label="GLM-5",
    )


# ── Kimi K2.5 ──

async def chat_kimi(
    prompt: str,
    system: str = "",
) -> Optional[str]:
    """调用 Kimi K2.5（LKEAP OpenAI 兼容接口）
    注意：Kimi K2.5 不支持 temperature / top_p 参数
    """
    if not KIMI_ENABLED:
        return None
    return await _call_lkeap_openai(
        model=KIMI_MODEL,
        prompt=prompt,
        system=system,
        temperature=None,  # Kimi K2.5 不支持
        label="Kimi-K2.5",
    )
