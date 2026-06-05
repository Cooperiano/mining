#!/usr/bin/env python3
"""
Agent演示程序 - 展示Agent的决策过程
"""

import asyncio
import sys
from pathlib import Path

# 确保路径正确
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from autonomous_agent import AutonomousMiningAgent, AgentConfig

async def demo_single_cycle():
    """演示单个决策周期"""

    print("🤖 自主Agent决策周期演示")
    print("=" * 60)
    print()

    # 创建保守配置用于演示
    config = AgentConfig(
        max_budget_per_hour=5.0,
        max_instances=2,
        min_profitability_score=60.0,
        target_gpu_models=["RTX_4090"],
        risk_tolerance="low",
        auto_approve_decisions=False,  # 演示模式不自动执行
        monitoring_interval_seconds=60
    )

    agent = AutonomousMiningAgent(config)

    print("📋 Agent配置:")
    print(f"   - 最大预算: ${config.max_budget_per_hour}/hr")
    print(f"   - 最大实例: {config.max_instances}")
    print(f"   - 目标GPU: {config.target_gpu_models}")
    print(f"   - 风险偏好: {config.risk_tolerance}")
    print()

    # 执行一个决策周期
    print("🔄 开始决策周期...")
    print("=" * 60)
    print()

    try:
        await agent.decision_cycle()

        print()
        print("=" * 60)
        print("✅ 决策周期完成")
        print()

        # 显示决策摘要
        if agent.decision_history:
            print("📋 本周期决策摘要:")
            print("-" * 60)

            for i, decision in enumerate(agent.decision_history, 1):
                print(f"{i}. {decision.decision_type}")
                print(f"   理由: {decision.reasoning}")
                print(f"   结果: {decision.result}")
                print(f"   收益影响: ${decision.profit_impact:.2f}/hr")
                print(f"   置信度: {decision.confidence:.1%}")
                print()

        else:
            print("ℹ️ 本周期无需采取任何行动")
            print("   - 未发现盈利机会")
            print("   - 当前实例运行正常")

    except Exception as e:
        print(f"❌ 决策周期失败: {e}")
        import traceback
        traceback.print_exc()

async def demo_market_analysis():
    """演示市场分析能力"""

    print("🔍 市场分析演示")
    print("=" * 60)
    print()

    config = AgentConfig(
        max_budget_per_hour=10.0,
        max_instances=5,
        target_gpu_models=["RTX_4090", "RTX_5090"]
    )

    agent = AutonomousMiningAgent(config)

    print("🌐 分析市场机会...")
    print()

    market_analysis = await agent.analyze_market()

    print(f"📊 发现 {len(market_analysis['opportunities'])} 个市场机会")
    print()

    if market_analysis['opportunities']:
        print("前5个最佳机会:")
        print("-" * 60)

        for i, opp in enumerate(market_analysis['opportunities'][:5], 1):
            offer = opp['offer']
            profit = opp['profitability']

            print(f"{i}. {offer['gpu_model']} @ ${offer['price_per_gpu']:.3f}/hr")
            print(f"   可靠性: {offer['reliability']:.1%}")
            print(f"   预期收益: ${profit['net_profit_per_hour']:.2f}/hr")
            print(f"   建议: {profit['recommendation']}")
            print(f"   风险: {profit['risk_assessment']['level']}")
            print()

    else:
        print("   未发现合适的市场机会")

async def demo_status_analysis():
    """演示状态分析能力"""

    print("📈 状态分析演示")
    print("=" * 60)
    print()

    config = AgentConfig(
        max_budget_per_hour=10.0,
        max_instances=5,
        target_gpu_models=["RTX_4090"]
    )

    agent = AutonomousMiningAgent(config)

    print("🔍 分析当前运营状态...")
    print()

    current_status = await agent.analyze_current_status()

    print("📊 当前运营状态:")
    print("-" * 60)
    print(f"总实例数: {current_status['total_instances']}")
    print(f"运行实例: {current_status['instance_count']}")
    print(f"总算力: {current_status['total_hashrate']:.1f} TH/s")
    print(f"每小时收益: ${current_status['total_revenue_per_hour']:.2f}")
    print(f"每小时成本: ${current_status['total_cost_per_hour']:.2f}")
    print(f"每小时净收益: ${current_status['net_profit_per_hour']:.2f}")

    if current_status['running_instances']:
        print()
        print("运行实例详情:")
        print("-" * 60)

        for i, instance in enumerate(current_status['running_instances'], 1):
            inst = instance['instance']
            profit = instance['profitability']

            print(f"{i}. 实例 {inst['instance_id']}")
            print(f"   GPU: {inst['gpu_model']}")
            print(f"   成本: ${inst['price_per_hour']:.3f}/hr")
            print(f"   算力: {profit['expected_hashrate_th']:.1f} TH/s")
            print(f"   净收益: ${profit['net_profit_per_hour']:.2f}/hr")
            print()

async def main():
    """主程序"""

    print("🎭 自主Agent能力演示")
    print("=" * 60)
    print()

    try:
        # 演示1: 市场分析
        await demo_market_analysis()

        print()
        print("⏸️ 按Enter继续到下一个演示...")
        input()

        # 演示2: 状态分析
        await demo_status_analysis()

        print()
        print("⏸️ 按Enter继续到下一个演示...")
        input()

        # 演示3: 完整决策周期
        await demo_single_cycle()

    except KeyboardInterrupt:
        print("\n🛑 演示已停止")

if __name__ == "__main__":
    asyncio.run(main())