# /// script
# dependencies = ["anthropic"]
# ///
"""
LLM客户端 — 通过Anthropic SDK调用LLM代理，为Agent提供决策能力

配置方式（优先级从高到低）：
1. 环境变量 (ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, ANTHROPIC_DEFAULT_SONNET_MODEL)
2. config.json 中 env_preset_id → 从 ~/.claude/envs.json 加载对应 preset
3. 硬编码默认值（DeepSeek）
"""

from __future__ import annotations
import json
import os
import re
from pathlib import Path
from anthropic import AsyncAnthropic


def _load_env_from_preset(preset_id: str) -> dict:
    """从 ~/.claude/envs.json 加载指定 preset 的环境变量"""
    envs_path = Path.home() / ".claude" / "envs.json"
    if not envs_path.exists():
        return {}
    try:
        presets = json.loads(envs_path.read_text()).get("presets", [])
        for p in presets:
            if p.get("id") == preset_id:
                return p.get("env", {})
    except Exception:
        pass
    return {}


class LLMClient:
    """轻量LLM客户端，单例模式，复用连接"""

    _instance: LLMClient | None = None

    def __new__(cls) -> LLMClient:
        if cls._instance is None:
            self = super().__new__(cls)

            # 1. 先加载 config.json 中指定的 preset
            config_path = Path(__file__).parent.parent / "config.json"
            preset_id = ""
            try:
                preset_id = json.loads(config_path.read_text()).get("env_preset_id", "")
            except Exception:
                pass

            preset_env = _load_env_from_preset(preset_id) if preset_id else {}

            def _env(key: str, fallback: str = "") -> str:
                return os.environ.get(key) or preset_env.get(key, "") or fallback

            self.api_key = _env("ANTHROPIC_AUTH_TOKEN")
            self.base_url = _env("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
            self.model = _env("ANTHROPIC_DEFAULT_SONNET_MODEL", "deepseek-v4-pro")
            self.client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)
            cls._instance = self
        return cls._instance

    async def decide(self, system_prompt: str, user_prompt: str) -> dict | None:
        """异步调用LLM，返回解析后的JSON决策"""
        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            # 兼容 ThinkingBlock（DeepSeek代理返回的思维链）
            text = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    text = block.text
                    break
            if not text:
                print("  [LLM] 响应无文本内容")
                return None
            # 从回复中提取第一个JSON对象
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group())
            return None
        except Exception as e:
            print(f"  [LLM] 调用失败: {e}")
            return None
