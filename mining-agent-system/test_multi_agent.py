#!/usr/bin/env python3
"""池子维护系统测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from specialized import PoolAgent
from vast_tools import VastTools
from coordinator import PoolCoordinator
import asyncio


async def test_pool_agent():
    """测试PoolAgent的LLM决策"""
    vast = VastTools()
    agent = PoolAgent(vast)

    print("🧪 PoolAgent 空池子测试")
    decisions = await agent.decide({"instances": [], "pool_size": 5})
    for d in decisions if isinstance(decisions, list) else [decisions]:
        print(f"   {d.action}: {d.reasoning}")
        agent.record(d)
    print()

    print("🧪 PoolAgent 检查已有实例")
    instances = vast.list_instances()
    decisions = await agent.decide({"instances": instances, "pool_size": 5})
    for d in decisions if isinstance(decisions, list) else [decisions]:
        print(f"   {d.action}: {d.reasoning}")
        agent.record(d)

    s = agent.summary()
    print(f"\n📊 {s['total_decisions']}次决策 | {s['action_counts']}")


async def test_coordinator():
    """测试协调器单周期"""
    coord = PoolCoordinator(pool_size=5, max_price=0.60, dry_run=True)
    print("🧪 协调器单周期 (dry-run)")
    await coord.run_cycle()
    print()


async def main():
    print("=" * 50)
    print("🔧 池子维护系统测试")
    print("=" * 50)
    print()

    await test_pool_agent()
    print()
    await test_coordinator()


if __name__ == "__main__":
    asyncio.run(main())
