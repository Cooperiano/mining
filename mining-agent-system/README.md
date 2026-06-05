# 自主矿机运营Agent系统

## 🚀 核心特性

这是一个**完全自主驱动**的矿机运营和管理系统，能够：

- **🧠 智能决策**: 自主分析市场机会，做出投资决策
- **⚡ 自动执行**: 自动创建/销毁实例，无需人工干预
- **📊 实时监控**: 7×24小时监控算力、成本、收益
- **🔄 持续优化**: 自动替换低效实例，优化盈利能力
- **💾 状态持久化**: 所有决策历史完整记录，支持恢复

## 🛠️ 快速开始

### 1. 测试系统

```bash
# 快速验证系统功能
python mining-agent-system/quick_test.py
```

### 2. 启动Agent

```bash
# 启动自主Agent（连续运行24小时）
python mining-agent-system/start_agent.py
```

### 3. 监控运行

Agent会自动：
- 每5分钟分析一次市场机会
- 实时监控所有运行中的实例
- 根据盈利能力自动扩容/缩容
- 记录所有决策到日志文件

## 📁 系统架构

```
mining-agent-system/
├── agents/
│   ├── autonomous_agent.py    # 核心自主Agent
│   └── __init__.py
├── tools/
│   ├── vast_tools.py          # Vast.ai集成
│   ├── profitability_tools.py # 盈利分析
│   └── __init__.py
├── state/
│   └── agent_state.json       # Agent状态存储
├── start_agent.py             # 启动脚本
├── quick_test.py              # 快速测试
└── README.md                  # 本文档
```

## 🤖 Agent工作流程

### 决策周期（每5分钟执行一次）

1. **📊 分析阶段**
   - 搜索Vast.ai市场最佳GPU优惠
   - 分析每个机会的盈利能力
   - 检查当前运行实例状态

2. **🧠 决策阶段**
   - 评估是否扩容（发现盈利机会）
   - 评估是否缩容（实例不盈利）
   - 评估是否替换（发现更好机会）

3. **⚡ 执行阶段**
   - 自动创建盈利实例
   - 自动销毁亏损实例
   - 自动替换低效实例

4. **👁️ 监控阶段**
   - 验证实例正常运行
   - 检查算力和收益
   - 记录决策结果

## ⚙️ 配置选项

```python
config = AgentConfig(
    max_budget_per_hour=20.0,        # 每小时最大预算
    max_instances=5,                 # 最大实例数量
    min_profitability_score=60.0,    # 最低盈利评分
    target_gpu_models=["RTX_4090"], # 目标GPU型号
    risk_tolerance="medium",          # 风险偏好
    auto_approve_decisions=True,     # 自动批准决策
    monitoring_interval_seconds=300   # 监控间隔（秒）
)
```

## 📊 决策历史

Agent会将所有决策保存到 `state/agent_state.json`:

```json
{
  "decision_history": [
    {
      "timestamp": "2026-06-04T10:30:00",
      "decision_type": "SCALE_UP",
      "reasoning": "发现盈利机会: RTX_4090 @ $0.45/hr",
      "action_taken": "SCALE_UP",
      "result": "✅ 成功创建实例 12345",
      "profit_impact": 0.12,
      "confidence": 0.8
    }
  ],
  "last_updated": "2026-06-04T10:30:00"
}
```

## 🔧 集成现有系统

### Vast.ai工具

```python
from tools.vast_tools import VastTools

vast = VastTools()

# 搜索最优优惠
offers = vast.search_best_offers(
    gpu_model="RTX_4090",
    max_price=0.50,
    min_reliability=0.95
)

# 创建实例
result = vast.create_instance(
    offer_id="12345",
    max_bid=0.45,
    label="agent-deployed"
)

# 检查实例健康
health = vast.check_instance_health(instance_id="12345")
```

### 盈利分析工具

```python
from tools.profitability_tools import ProfitabilityTools

profit = ProfitabilityTools()

# 分析投资机会
analysis = profit.analyze_investment_opportunity(
    gpu_model="RTX_4090",
    rental_price=0.45,
    investment_hours=24
)

print(f"预期净收益: ${analysis['net_profit_per_hour']:.2f}/hr")
print(f"建议: {analysis['recommendation']}")
```

## 🚦 下一步

当前实现的是完整的单Agent系统。未来可以扩展为：

1. **多Agent协调**: 添加专业化的采购、部署、监控、维护Agent
2. **战略决策层**: 添加长期投资策略Agent
3. **Temporal集成**: 添加长期运行保障机制
4. **人类监督界面**: 添加Web Dashboard和移动监控

## 📞 使用帮助

```bash
# 查看Agent状态
python -c "from agents.autonomous_agent import AutonomousMiningAgent; ..."

# 运行测试
python mining-agent-system/quick_test.py

# 查看日志
tail -f mining-agent-system/state/agent_state.json
```

## ⚠️ 重要提醒

1. **预算控制**: Agent会严格遵守 `max_budget_per_hour` 限制
2. **风险控制**: 所有决策都有风险评估和置信度评分
3. **可随时停止**: 按 `Ctrl+C` 可随时停止Agent
4. **决策可追溯**: 所有决策都有完整记录和理由

---

**现在就开始使用完全自主的Agent驱动系统！**