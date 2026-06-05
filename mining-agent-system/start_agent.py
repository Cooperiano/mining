#!/usr/bin/env python3
"""
自主矿机Agent启动脚本
快速启动完全自主的矿机运营Agent
"""

import asyncio
import sys
from pathlib import Path

# 确保路径正确
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from autonomous_agent import AutonomousMiningAgent, AgentConfig

async def main():
    """主程序"""

    print("🚀 启动自主矿机运营Agent")
    print("=" * 50)
    print()

    # 创建Agent配置
    config = AgentConfig(
        max_budget_per_hour=20.0,        # 每小时最大预算$20
        max_instances=5,                 # 最多5个实例
        min_profitability_score=60.0,    # 最低盈利评分60分
        target_gpu_models=["RTX_4090", "RTX_5090"],  # 目标GPU型号
        risk_tolerance="medium",          # 风险偏好: low, medium, high
        auto_approve_decisions=True,     # 自动批准决策
        monitoring_interval_seconds=300   # 每5分钟检查一次
    )

    print("📋 Agent配置:")
    print(f"   - 最大预算: ${config.max_budget_per_hour}/hr")
    print(f"   - 最大实例数: {config.max_instances}")
    print(f"   - 目标GPU: {config.target_gpu_models}")
    print(f"   - 风险偏好: {config.risk_tolerance}")
    print(f"   - 监控间隔: {config.monitoring_interval_seconds}秒")
    print(f"   - 自动决策: {'是' if config.auto_approve_decisions else '否'}")
    print()

    # 创建Agent
    print("🤖 创建Agent...")
    agent = AutonomousMiningAgent(config)
    print("✅ Agent创建成功")
    print()

    # 开始连续运行
    print("⏰ 开始连续运行24小时...")
    print("   (按Ctrl+C停止)")
    print()

    try:
        await agent.run_continuous(duration_hours=24)
    except KeyboardInterrupt:
        print("\n🛑 收到停止信号，Agent正在关闭...")

        # 显示最终统计
        summary = agent.get_decision_summary()
        if "total_decisions" in summary and summary['total_decisions'] > 0:
            print(f"\n📊 最终统计:")
            print(f"   - 总决策数: {summary['total_decisions']}")
            print(f"   - 决策类型: {summary['decision_counts']}")
            print(f"   - 总收益影响: ${summary['total_profit_impact']:.2f}")
            print(f"   - 成功率: {summary['success_rate']:.1%}")

        print("\n👋 Agent已停止")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
        sys.exit(0)