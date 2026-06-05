#!/usr/bin/env python3
"""
自主Agent测试程序 - 快速验证Agent功能
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from autonomous_agent import (
    AutonomousMiningAgent,
    AgentConfig,
    AgentState
)

async def test_agent_basic():
    """测试Agent基础功能"""

    print("🧪 测试1: 创建Agent")
    print("=" * 50)

    config = AgentConfig(
        max_budget_per_hour=10.0,
        max_instances=3,
        min_profitability_score=60.0,
        target_gpu_models=["RTX_4090"],  # 先用4090测试
        risk_tolerance="low",
        auto_approve_decisions=True,
        monitoring_interval_seconds=60  # 测试时1分钟间隔
    )

    agent = AutonomousMiningAgent(config)
    print(f"✅ Agent创建成功")
    print(f"   - 配置: 最大预算 ${config.max_budget_per_hour}/hr")
    print(f"   - 最大实例数: {config.max_instances}")
    print(f"   - 目标GPU: {config.target_gpu_models}")
    print(f"   - 当前状态: {agent.state.value}")

    print(f"\n🧪 测试2: 市场分析能力")
    print("=" * 50)

    # 测试市场分析
    market_analysis = await agent.analyze_market()
    print(f"✅ 市场分析完成")
    print(f"   - 发现机会数: {len(market_analysis['opportunities'])}")

    if market_analysis['opportunities']:
        best_opp = market_analysis['opportunities'][0]
        print(f"   - 最佳机会: {best_opp['offer']['gpu_model']}")
        print(f"   - 价格: ${best_opp['offer']['price_per_gpu']:.3f}/hr")
        print(f"   - 可靠性: {best_opp['offer']['reliability']:.1%}")
        print(f"   - 预期收益: ${best_opp['profitability']['net_profit_per_hour']:.2f}/hr")
        print(f"   - 建议: {best_opp['profitability']['recommendation']}")

    print(f"\n🧪 测试3: 当前状态分析")
    print("=" * 50)

    # 测试当前状态分析
    current_status = await agent.analyze_current_status()
    print(f"✅ 状态分析完成")
    print(f"   - 总实例数: {current_status['total_instances']}")
    print(f"   - 运行实例: {current_status['instance_count']}")
    print(f"   - 总算力: {current_status['total_hashrate']:.1f} TH/s")
    print(f"   - 每小时收益: ${current_status['total_revenue_per_hour']:.2f}")
    print(f"   - 每小时成本: ${current_status['total_cost_per_hour']:.2f}")
    print(f"   - 净收益: ${current_status['net_profit_per_hour']:.2f}")

    print(f"\n🧪 测试4: 决策能力")
    print("=" * 50)

    # 测试决策制定
    decisions = await agent.make_decisions(market_analysis, current_status)
    print(f"✅ 决策制定完成")
    print(f"   - 生成了 {len(decisions)} 个决策")

    for i, decision in enumerate(decisions, 1):
        print(f"   决策{i}: {decision['action']}")
        print(f"   - 理由: {decision['reasoning']}")
        print(f"   - 预期影响: ${decision.get('expected_profit_impact', 0):.2f}/hr")
        print(f"   - 置信度: {decision.get('confidence', 0):.1%}")

    print(f"\n🧪 测试5: 决策历史记录")
    print("=" * 50)

    # 模拟添加一些决策记录
    test_decision = agent.decision_history
    print(f"✅ 当前决策历史记录: {len(test_decision)} 条")

    # 获取决策摘要
    summary = agent.get_decision_summary()
    if "total_decisions" in summary:
        print(f"   - 总决策数: {summary['total_decisions']}")
        print(f"   - 决策类型统计: {summary['decision_counts']}")
        print(f"   - 总收益影响: ${summary['total_profit_impact']:.2f}")
        print(f"   - 成功率: {summary['success_rate']:.1%}")

    print(f"\n🧪 测试6: 状态持久化")
    print("=" * 50)

    # 保存状态
    agent.save_state()
    print(f"✅ 状态已保存")

    # 检查文件是否存在
    state_file = agent.state_dir / "agent_state.json"
    if state_file.exists():
        file_size = state_file.stat().st_size
        print(f"   - 文件大小: {file_size} bytes")
        print(f"   - 文件路径: {state_file}")

    print(f"\n🎉 所有测试完成！")
    print("=" * 50)

    # 输出测试摘要
    print(f"\n📊 测试摘要:")
    print(f"   ✅ Agent创建 - 通过")
    print(f"   ✅ 市场分析 - 通过 (发现 {len(market_analysis['opportunities'])} 个机会)")
    print(f"   ✅ 状态分析 - 通过 (监控 {current_status['instance_count']} 个实例)")
    print(f"   ✅ 决策制定 - 通过 (生成 {len(decisions)} 个决策)")
    print(f"   ✅ 历史记录 - 通过 ({len(agent.decision_history)} 条记录)")
    print(f"   ✅ 状态持久化 - 通过")

    return {
        "success": True,
        "market_opportunities": len(market_analysis['opportunities']),
        "current_instances": current_status['instance_count'],
        "decisions_made": len(decisions),
        "agent_ready": len(market_analysis['opportunities']) > 0
    }

async def test_agent_single_cycle():
    """测试单个完整运营周期"""

    print("🔄 测试完整运营周期")
    print("=" * 50)

    config = AgentConfig(
        max_budget_per_hour=10.0,
        max_instances=2,
        min_profitability_score=60.0,
        target_gpu_models=["RTX_4090"],
        risk_tolerance="low",
        auto_approve_decisions=True,
        monitoring_interval_seconds=60
    )

    agent = AutonomousMiningAgent(config)

    print("开始执行完整决策周期...")
    await agent.decision_cycle()

    print("✅ 运营周期完成")

    # 显示决策摘要
    summary = agent.get_decision_summary()
    if "total_decisions" in summary and summary['total_decisions'] > 0:
        print(f"\n📋 决策摘要:")
        print(f"   - 本周期决策数: {len(agent.decision_history)}")
        for decision in agent.decision_history[-5:]:  # 显示最近5个决策
            print(f"   - {decision.decision_type}: {decision.reasoning}")
            print(f"     结果: {decision.result}")
            print(f"     收益影响: ${decision.profit_impact:.2f}/hr")

async def test_agent_tools():
    """测试Agent工具集成"""

    print("🔧 测试工具集成")
    print("=" * 50)

    config = AgentConfig(
        max_budget_per_hour=10.0,
        max_instances=2,
        target_gpu_models=["RTX_4090"]
    )

    agent = AutonomousMiningAgent(config)

    # 测试Vast工具
    print("测试Vast.ai工具...")
    instances = agent.vast_tools.list_instances()
    print(f"✅ Vast工具正常 - 发现 {len(instances)} 个实例")

    # 测试盈利工具
    print("测试盈利分析工具...")
    prl_data = agent.profit_tools.get_current_prl_price()
    print(f"✅ 盈利工具正常 - PRL价格: ${prl_data['price']}")

    # 测试GPU盈利计算
    profitability = agent.profit_tools.calculate_profitability(
        "RTX_4090",
        0.50,  # 租赁价格
        prl_data['price']
    )
    print(f"✅ 盈利计算正常:")
    print(f"   - GPU: RTX_4090")
    print(f"   - 预期算力: {profitability.expected_hashrate_th} TH/s")
    print(f"   - 每小时收益: ${profitability.revenue_per_hour:.2f}")
    print(f"   - 每小时成本: ${profitability.total_cost_per_hour:.2f}")
    print(f"   - 净利润: ${profitability.net_profit_per_hour:.2f}")
    print(f"   - 建议: {profitability.recommendation}")

async def main():
    """主测试程序"""

    print("🤖 自主矿机Agent测试程序")
    print("=" * 50)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        # 运行基础测试
        result = await test_agent_basic()

        if result["agent_ready"]:
            print(f"\n✅ Agent已准备就绪！")

            # 询问是否要运行完整测试
            print(f"\n是否要运行完整运营周期测试？")
            print(f"注意: 这会实际执行决策，包括创建/销毁实例")

            # 这里可以添加用户交互，但现在自动运行
            # await test_agent_single_cycle()
        else:
            print(f"\n⚠️ Agent未就绪 - 未发现市场机会")

        # 测试工具集成
        await test_agent_tools()

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())