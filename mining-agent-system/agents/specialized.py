"""
专业化Agent — 池子维护

一个Agent足矣。池子里的实例，跑得好就留着，跌出limits就杀。
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from base import BaseAgent, Decision
from vast_tools import VastTools
from llm_client import LLMClient


SYSTEM_PROMPT = """你是一个GPU矿池**运维Agent**。你的职责是维护一个实例池子。

对**每个实例**，你需要判断是 KILL 还是 KEEP：
- KILL：实例有问题，立即终止（失联、GPU故障、miner挂了、利用率极低等）
- KEEP：实例运行正常，留着

约束：
- 实例失联（SSH连不上、nvidia-smi超时）→ 必须KILL
- GPU利用率 < 10% → 可以KILL（矿机没在干活）
- Miner进程挂了且重启无效 → 必须KILL
- GPU温度 > 85°C → 可以KILL
- 一切正常 → KEEP

输出格式必须是JSON数组，每个实例一条：
[{"instance_id": "...", "action": "KILL|KEEP", "reasoning": "简要理由（中文）", "confidence": 0.0~1.0}]"""


class PoolAgent(BaseAgent):
    """运维Agent — 决策: KILL / KEEP"""

    def __init__(self, vast: VastTools):
        super().__init__("PoolAgent")
        self.vast = vast
        self._killed: set[str] = set()

    async def decide(self, context: dict) -> list[Decision]:
        """检查所有实例，返回决策列表"""
        instances = context.get("instances") or self.vast.list_instances()
        if not instances:
            return [Decision.noop(self.name, "池子为空")]

        # 构建每个实例的健康检查上下文
        lines = [f"池子目标大小: {context.get('pool_size', 'N/A')}", f"当前实例数: {len(instances)}", ""]
        for inst in instances:
            lines.append(f"实例#{inst.instance_id} | {inst.gpu_model} | ${inst.price_per_hour:.3f}/hr | 状态: {inst.status}")
            health = self.vast.check_instance_health(inst.instance_id)
            if health["healthy"]:
                for g in health.get("gpus", []):
                    lines.append(f"  GPU {g['name']} | 利用率{g['utilization']}% | 温度{g['temperature']}°C")
                miner = "运行中" if health.get("miner_running") else "已停止"
                lines.append(f"  Miner: {miner}")
            else:
                lines.append(f"  不健康: {health.get('reason', '未知')}")
            lines.append("")

        llm = LLMClient()
        result = await llm.decide(SYSTEM_PROMPT, "\n".join(lines))

        if not result or not isinstance(result, list):
            return [Decision.noop(self.name, "LLM决策失败，跳过本轮")]

        decisions = []
        for item in result:
            iid = item.get("instance_id", "")
            action = item.get("action", "KEEP")

            if action == "KILL":
                self.vast.destroy_instance(iid)
                self._killed.add(iid)
                decisions.append(Decision(
                    self.name, "KILL",
                    item.get("reasoning", f"终止实例{iid}"),
                    target=iid,
                    confidence=item.get("confidence", 0.8),
                ))
            else:
                decisions.append(Decision(
                    self.name, "KEEP",
                    item.get("reasoning", f"实例{iid}运行正常"),
                    target=iid,
                    confidence=item.get("confidence", 0.9),
                ))

        return decisions

    @property
    def killed_count(self) -> int:
        return len(self._killed)
