# /// script
# dependencies = ["anthropic"]
# ///
"""
Agent基类 - 定义所有专业化Agent的基础接口
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Decision:
    """Agent决策"""
    agent: str
    action: str
    reasoning: str
    target: str | None
    confidence: float
    data: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def noop(agent: str, reasoning: str = "无需操作") -> "Decision":
        return Decision(agent=agent, action="NOOP", reasoning=reasoning, target=None, confidence=1.0)


@dataclass
class DecisionRecord:
    """决策记录（持久化用）"""
    timestamp: str
    decision: dict


class BaseAgent(ABC):
    """Agent基类"""

    def __init__(self, name: str):
        self.name = name
        self.history: list[DecisionRecord] = []

    @abstractmethod
    async def decide(self, context: dict) -> Decision | list[Decision]:
        """根据上下文做出决策（异步），可返回单个或多个"""
        ...

    def record(self, decision: Decision):
        """记录决策"""
        self.history.append(DecisionRecord(
            timestamp=datetime.now().isoformat(),
            decision=decision.to_dict()
        ))

    def latest(self) -> Decision | None:
        """最近一次决策"""
        if not self.history:
            return None
        d = self.history[-1].decision
        return Decision(**d)

    def summary(self) -> dict:
        """决策摘要"""
        counts: dict[str, int] = {}
        for r in self.history:
            d = r.decision
            counts[d["action"]] = counts.get(d["action"], 0) + 1
        return {
            "agent": self.name,
            "total_decisions": len(self.history),
            "action_counts": counts,
        }