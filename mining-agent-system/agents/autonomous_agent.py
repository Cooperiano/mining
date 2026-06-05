#!/usr/bin/env python3
"""
自主矿机运营Agent - 完全自主驱动
能够自主监控市场、做出投资决策、自动执行部署
"""

from __future__ import annotations
import json
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from vast_tools import VastTools
from profitability_tools import ProfitabilityTools

class AgentState(Enum):
    """Agent状态"""
    IDLE = "idle"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    EXECUTING = "executing"
    MONITORING = "monitoring"
    ERROR = "error"

@dataclass
class AgentDecision:
    """Agent决策记录"""
    timestamp: str
    decision_type: str
    reasoning: str
    action_taken: str
    result: str
    profit_impact: float
    confidence: float

@dataclass
class AgentConfig:
    """Agent配置"""
    max_budget_per_hour: float = 50.0
    max_instances: int = 10
    min_profitability_score: float = 60.0
    target_gpu_models: List[str] = None
    risk_tolerance: str = "medium"  # low, medium, high
    auto_approve_decisions: bool = True
    monitoring_interval_seconds: int = 300  # 5分钟
    decision_history_limit: int = 100

    def __post_init__(self):
        if self.target_gpu_models is None:
            self.target_gpu_models = ["RTX_5090", "RTX_4090"]

class AutonomousMiningAgent:
    """自主矿机运营Agent"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.state = AgentState.IDLE
        self.decision_history: List[AgentDecision] = []

        # 初始化工具
        self.vast_tools = VastTools()
        self.profit_tools = ProfitabilityTools()

        # 状态存储
        self.state_dir = Path(__file__).parent.parent / "state"
        self.state_dir.mkdir(exist_ok=True)

        # 加载上次状态
        self.load_state()

    def load_state(self):
        """加载Agent状态"""
        state_file = self.state_dir / "agent_state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                self.decision_history = [
                    AgentDecision(**d) for d in data.get("decision_history", [])
                ]
                print(f"加载了 {len(self.decision_history)} 条历史决策")
            except Exception as e:
                print(f"加载状态失败: {e}")

    def save_state(self):
        """保存Agent状态"""
        state_file = self.state_dir / "agent_state.json"
        try:
            data = {
                "decision_history": [asdict(d) for d in self.decision_history],
                "last_updated": datetime.now().isoformat()
            }
            state_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"保存状态失败: {e}")

    async def run_continuous(self, duration_hours: int = 24):
        """连续运行Agent"""
        print(f"🤖 Agent启动，将连续运行 {duration_hours} 小时")

        end_time = datetime.now() + timedelta(hours=duration_hours)
        cycle_count = 0

        while datetime.now() < end_time:
            cycle_count += 1
            print(f"\n=== 运营周期 #{cycle_count} ===")

            try:
                # 执行一次完整的决策周期
                await self.decision_cycle()

                # 等待下一个周期
                print(f"⏰ 等待 {self.config.monitoring_interval_seconds} 秒...")
                await asyncio.sleep(self.config.monitoring_interval_seconds)

            except KeyboardInterrupt:
                print("\n🛑 收到停止信号，Agent正在关闭...")
                break
            except Exception as e:
                print(f"❌ 运营周期出错: {e}")
                # 记录错误决策
                error_decision = AgentDecision(
                    timestamp=datetime.now().isoformat(),
                    decision_type="ERROR",
                    reasoning=str(e),
                    action_taken="无",
                    result="ERROR",
                    profit_impact=0.0,
                    confidence=0.0
                )
                self.decision_history.append(error_decision)
                self.save_state()

                # 等待后重试
                await asyncio.sleep(60)

        print(f"🤖 Agent运行完成，共执行 {cycle_count} 个周期")

    async def decision_cycle(self):
        """执行一次完整的决策周期"""

        # 1. 分析阶段
        self.state = AgentState.ANALYZING
        print("📊 阶段1: 分析市场和当前状态...")

        market_analysis = await self.analyze_market()
        current_status = await self.analyze_current_status()

        print(f"  - 当前实例数: {len(current_status['running_instances'])}")
        print(f"  - 当前总算力: {current_status['total_hashrate']:.1f} TH/s")
        print(f"  - 每小时净收益: ${current_status['net_profit_per_hour']:.2f}")

        # 2. 决策阶段
        self.state = AgentState.DECIDING
        print("🧠 阶段2: 做出运营决策...")

        decisions = await self.make_decisions(market_analysis, current_status)

        if not decisions:
            print("  ℹ️ 当前无需采取行动")
            self.state = AgentState.MONITORING
            return

        print(f"  📋 生成了 {len(decisions)} 个决策")

        # 3. 执行阶段
        self.state = AgentState.EXECUTING
        print("⚡ 阶段3: 执行决策...")

        for i, decision in enumerate(decisions, 1):
            print(f"  执行决策 {i}/{len(decisions)}: {decision['action']}")

            try:
                result = await self.execute_decision(decision)

                # 记录决策结果
                agent_decision = AgentDecision(
                    timestamp=datetime.now().isoformat(),
                    decision_type=decision['action'],
                    reasoning=decision['reasoning'],
                    action_taken=decision['action'],
                    result=result,
                    profit_impact=decision.get('expected_profit_impact', 0.0),
                    confidence=decision.get('confidence', 0.8)
                )

                self.decision_history.append(agent_decision)

                # 保存状态
                if len(self.decision_history) > self.config.decision_history_limit:
                    self.decision_history.pop(0)

                self.save_state()

            except Exception as e:
                print(f"  ❌ 执行决策失败: {e}")

        # 4. 监控阶段
        self.state = AgentState.MONITORING
        print("👁️ 阶段4: 监控执行结果...")

        await self.monitor_execution()

        print("✅ 决策周期完成")

    async def analyze_market(self) -> Dict[str, Any]:
        """分析市场机会"""

        market_analysis = {
            "timestamp": datetime.now().isoformat(),
            "opportunities": [],
            "market_trends": {}
        }

        # 搜索每个目标GPU型号的最优机会
        for gpu_model in self.config.target_gpu_models:
            print(f"  🔍 搜索 {gpu_model} 机会...")

            # 获取当前PRL价格
            prl_data = self.profit_tools.get_current_prl_price()
            current_prl_price = prl_data["price"]

            # 计算最高可接受价格
            max_price = self.calculate_max_acceptable_price(gpu_model, current_prl_price)

            # 搜索市场优惠
            offers = self.vast_tools.search_best_offers(
                gpu_model=gpu_model,
                max_price=max_price,
                min_reliability=0.95,
                verified_only=True
            )

            # 分析每个机会
            for offer in offers[:5]:  # 只分析前5个
                profitability = self.profit_tools.analyze_investment_opportunity(
                    gpu_model=offer.gpu_model,
                    rental_price=offer.price_per_gpu,
                    investment_hours=24
                )

                market_analysis["opportunities"].append({
                    "offer": asdict(offer),
                    "profitability": profitability
                })

        # 按盈利能力排序
        market_analysis["opportunities"].sort(
            key=lambda x: x["profitability"]["net_profit_per_hour"],
            reverse=True
        )

        return market_analysis

    async def analyze_current_status(self) -> Dict[str, Any]:
        """分析当前运营状态"""

        # 获取所有实例
        instances = self.vast_tools.list_instances()

        running_instances = []
        total_hashrate = 0.0
        total_cost = 0.0
        total_revenue = 0.0

        prl_data = self.profit_tools.get_current_prl_price()
        current_prl_price = prl_data["price"]

        for instance in instances:
            if instance.status == "running":
                # 检查实例健康状态
                health = self.vast_tools.check_instance_health(instance.instance_id)

                if health["healthy"]:
                    # 计算该实例的算力和盈利
                    profitability = self.profit_tools.calculate_profitability(
                        instance.gpu_model,
                        instance.price_per_hour,
                        current_prl_price
                    )

                    running_instances.append({
                        "instance": asdict(instance),
                        "health": health,
                        "profitability": asdict(profitability)
                    })

                    total_hashrate += profitability.expected_hashrate_th
                    total_cost += profitability.total_cost_per_hour
                    total_revenue += profitability.revenue_per_hour

        net_profit = total_revenue - total_cost

        return {
            "timestamp": datetime.now().isoformat(),
            "total_instances": len(instances),
            "running_instances": running_instances,
            "total_hashrate": total_hashrate,
            "total_cost_per_hour": total_cost,
            "total_revenue_per_hour": total_revenue,
            "net_profit_per_hour": net_profit,
            "instance_count": len(running_instances)
        }

    async def make_decisions(
        self,
        market_analysis: Dict[str, Any],
        current_status: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """做出运营决策"""

        decisions = []
        current_instances = current_status["instance_count"]

        # 决策1: 是否扩容？
        if current_instances < self.config.max_instances:
            print("  🤔 评估扩容机会...")

            # 寻找最佳扩容机会
            best_opportunity = None
            for opportunity in market_analysis["opportunities"]:
                if opportunity["profitability"]["recommendation"] == "BUY":
                    best_opportunity = opportunity
                    break

            if best_opportunity:
                expected_profit = best_opportunity["profitability"]["net_profit_per_hour"]

                if expected_profit > 0.05:  # 每小时净利润超过5美分
                    decisions.append({
                        "action": "SCALE_UP",
                        "reasoning": f"发现盈利机会: {best_opportunity['offer']['gpu_model']} @ ${best_opportunity['offer']['price_per_gpu']:.3f}/hr",
                        "offer_id": best_opportunity["offer"]["offer_id"],
                        "gpu_model": best_opportunity["offer"]["gpu_model"],
                        "max_bid": best_opportunity["offer"]["price_per_gpu"],
                        "expected_profit_per_hour": expected_profit,
                        "expected_profit_impact": expected_profit,
                        "confidence": 0.8
                    })

        # 决策2: 是否缩容？
        print("  🤔 评估缩容需求...")

        # 检查是否有不盈利的实例
        for instance_data in current_status["running_instances"]:
            profitability = instance_data["profitability"]
            if profitability["net_profit_per_hour"] < -0.05:  # 每小时净损失超过5美分
                decisions.append({
                    "action": "SCALE_DOWN",
                    "reasoning": f"实例不盈利: {instance_data['instance']['gpu_model']} @ ${instance_data['instance']['price_per_hour']:.3f}/hr",
                    "instance_id": instance_data["instance"]["instance_id"],
                    "expected_savings": abs(profitability["net_profit_per_hour"]),
                    "expected_profit_impact": abs(profitability["net_profit_per_hour"]),
                    "confidence": 0.9
                })

        # 决策3: 是否替换实例？
        print("  🤔 评估替换机会...")

        # 检查是否有更好的替换机会
        if current_status["running_instances"]:
            for instance_data in current_status["running_instances"]:
                current_instance = instance_data["instance"]
                current_profit = instance_data["profitability"]["net_profit_per_hour"]

                # 寻找更好的替代品
                for opportunity in market_analysis["opportunities"][:3]:  # 只看前3个最佳机会
                    new_profit = opportunity["profitability"]["net_profit_per_hour"]

                    # 如果新机会比当前实例好20%以上
                    if new_profit > current_profit * 1.2:
                        decisions.append({
                            "action": "REPLACE",
                            "reasoning": f"发现更好机会: 当前${current_profit:.3f}/hr -> 新${new_profit:.3f}/hr",
                            "old_instance_id": current_instance["instance_id"],
                            "new_offer_id": opportunity["offer"]["offer_id"],
                            "new_gpu_model": opportunity["offer"]["gpu_model"],
                            "new_max_bid": opportunity["offer"]["price_per_gpu"],
                            "expected_improvement": new_profit - current_profit,
                            "expected_profit_impact": new_profit - current_profit,
                            "confidence": 0.7
                        })
                        break  # 只建议一个替换

        return decisions

    async def execute_decision(self, decision: Dict[str, Any]) -> str:
        """执行决策"""

        action = decision["action"]

        if action == "SCALE_UP":
            return await self.execute_scale_up(decision)
        elif action == "SCALE_DOWN":
            return await self.execute_scale_down(decision)
        elif action == "REPLACE":
            return await self.execute_replace(decision)
        else:
            return f"未知决策类型: {action}"

    async def execute_scale_up(self, decision: Dict[str, Any]) -> str:
        """执行扩容决策"""

        print(f"    🚀 扩容: 租赁 {decision['gpu_model']}")

        result = self.vast_tools.create_instance(
            offer_id=decision["offer_id"],
            max_bid=decision["max_bid"],
            label=f"agent-deployed-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        if result["success"]:
            instance_id = result["instance_id"]
            return f"✅ 成功创建实例 {instance_id}"

            # 等待实例启动并部署矿机
            # 这里可以添加自动部署逻辑
        else:
            return f"❌ 创建实例失败: {result.get('error', 'Unknown error')}"

    async def execute_scale_down(self, decision: Dict[str, Any]) -> str:
        """执行缩容决策"""

        print(f"    🗑️ 缩容: 销毁实例 {decision['instance_id']}")

        result = self.vast_tools.destroy_instance(decision["instance_id"])

        if result["success"]:
            return f"✅ 成功销毁实例 {decision['instance_id']}"
        else:
            return f"❌ 销毁实例失败: {result.get('error', 'Unknown error')}"

    async def execute_replace(self, decision: Dict[str, Any]) -> str:
        """执行替换决策"""

        print(f"    🔄 替换: {decision['old_instance_id']} -> {decision['new_gpu_model']}")

        # 1. 创建新实例
        new_result = self.vast_tools.create_instance(
            offer_id=decision["new_offer_id"],
            max_bid=decision["new_max_bid"],
            label=f"agent-replacement-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        if not new_result["success"]:
            return f"❌ 创建新实例失败: {new_result.get('error', 'Unknown error')}"

        # 2. 等待新实例稳定（简化处理，实际应该等待和验证）
        await asyncio.sleep(60)  # 等待1分钟

        # 3. 销毁旧实例
        old_result = self.vast_tools.destroy_instance(decision["old_instance_id"])

        if old_result["success"]:
            return f"✅ 成功替换实例: {decision['old_instance_id']} -> {new_result['instance_id']}"
        else:
            return f"⚠️ 新实例已创建但旧实例销毁失败: {old_result.get('error', 'Unknown error')}"

    async def monitor_execution(self):
        """监控执行结果"""

        # 简化版本，等待一段时间让实例稳定
        print("  ⏰ 等待实例稳定...")
        await asyncio.sleep(30)

        # 这里可以添加更详细的监控逻辑
        # - 检查新实例是否正常启动
        # - 验证矿机是否运行
        # - 检查算力是否达标

    def calculate_max_acceptable_price(self, gpu_model: str, prl_price: float) -> float:
        """计算最高可接受价格"""

        profitability = self.profit_tools.calculate_profitability(
            gpu_model,
            0.0,  # 先用0价格计算盈亏平衡点
            prl_price
        )

        # 盈亏平衡价格就是最高可接受价格
        break_even_price = profitability.revenue_per_hour - profitability.electricity_cost_per_hour

        # 为了保险，留20%的利润空间
        max_acceptable = break_even_price * 0.8

        return max(0, max_acceptable)

    def get_decision_summary(self) -> Dict[str, Any]:
        """获取决策摘要"""

        if not self.decision_history:
            return {"message": "暂无决策历史"}

        # 统计决策类型
        decision_counts = {}
        total_profit_impact = 0.0

        for decision in self.decision_history:
            decision_type = decision.decision_type
            decision_counts[decision_type] = decision_counts.get(decision_type, 0) + 1
            total_profit_impact += decision.profit_impact

        # 成功率统计
        successful_decisions = [d for d in self.decision_history if d.result != "ERROR"]
        success_rate = len(successful_decisions) / len(self.decision_history) if self.decision_history else 0

        return {
            "total_decisions": len(self.decision_history),
            "decision_counts": decision_counts,
            "total_profit_impact": total_profit_impact,
            "success_rate": success_rate,
            "recent_decisions": [asdict(d) for d in self.decision_history[-10:]]
        }

# 主程序
async def main():
    """主程序"""

    # 创建Agent配置
    config = AgentConfig(
        max_budget_per_hour=50.0,
        max_instances=5,
        min_profitability_score=60.0,
        target_gpu_models=["RTX_5090", "RTX_4090"],
        risk_tolerance="medium",
        auto_approve_decisions=True,
        monitoring_interval_seconds=300  # 5分钟
    )

    # 创建Agent
    agent = AutonomousMiningAgent(config)

    # 开始连续运行
    await agent.run_continuous(duration_hours=24)  # 运行24小时

if __name__ == "__main__":
    asyncio.run(main())