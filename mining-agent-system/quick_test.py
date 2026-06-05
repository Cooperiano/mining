#!/usr/bin/env python3
"""
快速测试Agent系统基础功能
"""

import sys
from pathlib import Path

# 确保路径正确
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent / "agents"))

def test_imports():
    """测试导入"""
    print("🧪 测试1: 导入测试")
    print("=" * 50)

    try:
        from vast_tools import VastTools, GPUOffer, InstanceInfo
        print("✅ VastTools导入成功")
    except Exception as e:
        print(f"❌ VastTools导入失败: {e}")
        return False

    try:
        from profitability_tools import ProfitabilityTools, ProfitabilityMetrics
        print("✅ ProfitabilityTools导入成功")
    except Exception as e:
        print(f"❌ ProfitabilityTools导入失败: {e}")
        return False

    try:
        from autonomous_agent import AutonomousMiningAgent, AgentConfig, AgentState
        print("✅ AutonomousAgent导入成功")
    except Exception as e:
        print(f"❌ AutonomousAgent导入失败: {e}")
        return False

    return True

def test_agent_creation():
    """测试Agent创建"""
    print("\n🧪 测试2: Agent创建")
    print("=" * 50)

    try:
        from autonomous_agent import AgentConfig, AutonomousMiningAgent

        config = AgentConfig(
            max_budget_per_hour=10.0,
            max_instances=2,
            target_gpu_models=["RTX_4090"],
            risk_tolerance="low",
            monitoring_interval_seconds=60
        )

        agent = AutonomousMiningAgent(config)

        print(f"✅ Agent创建成功")
        print(f"   - 状态: {agent.state.value}")
        print(f"   - 最大预算: ${config.max_budget_per_hour}/hr")
        print(f"   - 最大实例: {config.max_instances}")
        print(f"   - 目标GPU: {config.target_gpu_models}")

        return True
    except Exception as e:
        print(f"❌ Agent创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_vast_tools():
    """测试Vast工具"""
    print("\n🧪 测试3: Vast工具")
    print("=" * 50)

    try:
        from vast_tools import VastTools

        vast_tools = VastTools()

        # 测试列出实例
        instances = vast_tools.list_instances()
        print(f"✅ Vast工具正常")
        print(f"   - 当前实例数: {len(instances)}")

        if instances:
            for instance in instances[:3]:
                print(f"   - 实例 {instance.instance_id}: {instance.gpu_model} ({instance.status})")

        return True
    except Exception as e:
        print(f"❌ Vast工具测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_profitability_tools():
    """测试盈利工具"""
    print("\n🧪 测试4: 盈利工具")
    print("=" * 50)

    try:
        from profitability_tools import ProfitabilityTools

        profit_tools = ProfitabilityTools()

        # 测试获取PRL价格
        prl_data = profit_tools.get_current_prl_price()
        print(f"✅ 盈利工具正常")
        print(f"   - PRL价格: ${prl_data['price']}")

        # 测试盈利计算
        profitability = profit_tools.calculate_profitability(
            "RTX_4090",
            0.50,
            prl_data['price']
        )

        print(f"   - RTX_4090盈利分析:")
        print(f"     预期算力: {profitability.expected_hashrate_th} TH/s")
        print(f"     每小时收益: ${profitability.revenue_per_hour:.2f}")
        print(f"     每小时成本: ${profitability.total_cost_per_hour:.2f}")
        print(f"     净利润: ${profitability.net_profit_per_hour:.2f}")
        print(f"     建议: {profitability.recommendation}")

        return True
    except Exception as e:
        print(f"❌ 盈利工具测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_agent_analysis():
    """测试Agent分析能力"""
    print("\n🧪 测试5: Agent分析能力")
    print("=" * 50)

    try:
        from autonomous_agent import AutonomousMiningAgent, AgentConfig
        import asyncio

        config = AgentConfig(
            max_budget_per_hour=10.0,
            max_instances=2,
            target_gpu_models=["RTX_4090"],
            monitoring_interval_seconds=60
        )

        agent = AutonomousMiningAgent(config)

        # 测试当前状态分析
        print("   分析当前状态...")
        current_status = asyncio.run(agent.analyze_current_status())

        print(f"✅ 状态分析完成")
        print(f"   - 总实例数: {current_status['total_instances']}")
        print(f"   - 运行实例: {current_status['instance_count']}")
        print(f"   - 总算力: {current_status['total_hashrate']:.1f} TH/s")
        print(f"   - 净收益: ${current_status['net_profit_per_hour']:.2f}/hr")

        return True
    except Exception as e:
        print(f"❌ 状态分析失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试程序"""
    print("🤖 自主Agent系统快速测试")
    print("=" * 50)
    print()

    results = []

    # 运行所有测试
    results.append(("导入测试", test_imports()))
    results.append(("Agent创建", test_agent_creation()))
    results.append(("Vast工具", test_vast_tools()))
    results.append(("盈利工具", test_profitability_tools()))
    results.append(("Agent分析", test_agent_analysis()))

    # 显示结果摘要
    print("\n📊 测试结果摘要")
    print("=" * 50)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("🎉 所有测试通过！Agent系统准备就绪。")
        return True
    else:
        print("⚠️ 部分测试失败，需要修复。")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)