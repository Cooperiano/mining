# /// script
# dependencies = ["anthropic"]
# ///
"""
池子协调器 — 维护GPU实例池

每个周期：
  1. 检查池子所有实例
  2. 不行的杀 → 行的留
  3. 池子不够 → 补
"""

from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from base import Decision
from specialized import PoolAgent
from vast_tools import VastTools


class PoolCoordinator:
    """池子协调器"""

    def __init__(self, pool_size: int = 5, max_price: float = 0.60, dry_run: bool = False):
        self.vast = VastTools()
        self.agent = PoolAgent(self.vast)
        self.pool_size = pool_size
        self.max_price = max_price
        self.dry_run = dry_run
        self.log_path = Path(__file__).parent / "state" / "cycle_log.json"
        self.log_path.parent.mkdir(exist_ok=True)

    def _log(self, entry: dict):
        logs = []
        if self.log_path.exists():
            logs = json.loads(self.log_path.read_text())
        logs.append({"timestamp": datetime.now().isoformat(), **entry})
        self.log_path.write_text(json.dumps(logs[-200:], indent=2, ensure_ascii=False))

    def _deploy_to_fill(self):
        """池子缺实例时，机械地补一个"""
        instances = self.vast.list_instances()
        shortage = self.pool_size - len(instances)
        if shortage <= 0:
            return None

        print(f"  池子缺{shortage}个实例，尝试部署...")
        for gpu in ["RTX_4090", "RTX_5090"]:
            offers = self.vast.search_best_offers(
                gpu_model=gpu,
                max_price=self.max_price,
                min_reliability=0.9,
                verified_only=False,
            )
            if offers:
                best = offers[0]
                print(f"  找到 {gpu} offer#{best.offer_id} @ ${best.total_price:.3f}/hr")

                if self.dry_run:
                    print(f"  [dry-run] 跳过实际部署")
                    return f"dry-{best.offer_id}"

                result = self.vast.create_instance(
                    offer_id=best.offer_id,
                    label=f"pool-{gpu[:7]}",
                )
                if result["success"]:
                    print(f"  ✅ 部署成功: {result['instance_id']}")
                    return result["instance_id"]
                print(f"  ❌ 部署失败: {result.get('error', '未知')}")
        return None

    async def run_cycle(self) -> dict:
        """一次运营周期"""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n{'='*50}")
        print(f"🔄 [{ts}] 池子维护周期")
        print(f"{'='*50}")

        instances = self.vast.list_instances()
        print(f"\n当前池子: {len(instances)}/{self.pool_size} 实例")

        if not instances:
            print("  池子为空")
            self._deploy_to_fill()
            pool_after = len(self.vast.list_instances())
            self._log({"pool_before": 0, "pool_after": pool_after, "killed": [], "deployed": True})
            return {"pool_size": 0, "action": "deploy_to_fill"}

        # 刚部署还在 loading 的实例跳过检查
        running = [i for i in instances if i.status not in ("loading", "stopped")]
        loading = [i for i in instances if i.status in ("loading", "stopped")]
        if loading:
            print(f"  ⏳ {len(loading)}个实例启动中，跳过检查")

        if not running:
            shortage = self.pool_size - len(instances)
            if shortage > 0:
                self._deploy_to_fill()
            pool_after = len(self.vast.list_instances())
            self._log({"pool_before": len(instances), "pool_after": pool_after, "killed": [], "deployed": True})
            print(f"\n✅ 周期结束 | 池子: {pool_after}/{self.pool_size}")
            return {"pool_before": len(instances), "pool_after": pool_after, "killed": []}

        # ── 让LLM看每个实例，决定杀不杀 ──
        print(f"  PoolAgent 检查 {len(running)}个运行中实例...")
        decisions = await self.agent.decide({"instances": running, "pool_size": self.pool_size})

        killed = []
        for d in decisions if isinstance(decisions, list) else [decisions]:
            self.agent.record(d)
            if d.action == "KILL":
                killed.append(d.target)
                print(f"  💀 {d.action}: {d.reasoning}")
            elif d.action == "KEEP":
                print(f"  ✅ {d.action}: {d.reasoning}")

        # ── 补实例 ──
        deployed = self._deploy_to_fill()
        pool_after = len(self.vast.list_instances())

        self._log({
            "pool_before": len(instances),
            "pool_after": pool_after,
            "killed": killed,
            "deployed": bool(deployed),
        })

        print(f"\n✅ 周期结束 | 池子: {pool_after}/{self.pool_size}")
        return {"pool_before": len(instances), "pool_after": pool_after, "killed": killed}

    async def run_continuous(self, interval_seconds: int = 300, max_cycles: int | None = None):
        """连续运行"""
        print(f"🚀 池子协调器启动")
        print(f"   目标池大小: {self.pool_size}")
        print(f"   最大单价: ${self.max_price:.2f}/hr")
        if self.dry_run:
            print(f"   模式: dry-run (不实际部署)")
        print(f"   检查间隔: {interval_seconds}s")
        print(f"   按 Ctrl+C 停止\n")

        cycle = 0
        try:
            while max_cycles is None or cycle < max_cycles:
                cycle += 1
                await self.run_cycle()
                if max_cycles and cycle >= max_cycles:
                    break
                print(f"\n⏰ {interval_seconds}s 后下一轮...")
                await asyncio.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n🛑 停止")

        s = self.agent.summary()
        print(f"\n📊 总决策: {s['total_decisions']}次 | 动作: {s['action_counts']} | 累计杀: {self.agent.killed_count}")


if __name__ == "__main__":
    coord = PoolCoordinator(pool_size=5, max_price=0.60, dry_run=False)
    asyncio.run(coord.run_continuous(interval_seconds=300))
