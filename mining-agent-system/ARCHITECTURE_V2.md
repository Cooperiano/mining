# 多Agent专业化分工架构 V2.0

## 核心理念

**"专业分工，明确决策，简单可靠"**

- 每个Agent专注于一个明确的决策领域
- 决策空间小而精确，避免复杂判断
- 通过协调实现整体智能，而非单个Agent的复杂性

## 专业化Agent团队

### 1. 采购Agent (ProcurementAgent)
**决策空间**: BUY / SKIP / WAIT

**职责**: 智能GPU采购决策
- 实时监控Vast.ai市场价格
- 计算ROI和盈利预测
- 自动执行租赁决策

**决策依据**:
```python
if net_profit_per_hour > 0.10 and reliability > 0.95:
    return "BUY"
elif net_profit_per_hour > 0.05:
    return "WAIT"
else:
    return "SKIP"
```

### 2. 部署Agent (DeploymentAgent)
**决策空间**: DEPLOY / RETRY / SKIP

**职责**: 自动化部署和配置
- 选择最优配置参数
- 执行部署脚本
- 验证部署成功

**决策依据**:
```python
if instance_healthy and miner_installed:
    return "SKIP"  # 已部署
elif gpu_available and budget_sufficient:
    return "DEPLOY"
elif deployment_failed and retries < 3:
    return "RETRY"
else:
    return "SKIP"
```

### 3. 监控Agent (MonitoringAgent)
**决策空间**: NORMAL / WARNING / ALERT

**职责**: 7×24小时性能监控
- 实时追踪算力和收益
- 检测异常和性能下降
- 触发预警机制

**决策依据**:
```python
if hashrate_drop > 0.2 or cost_increase > 0.1:
    return "ALERT"
elif hashrate_drop > 0.1 or cost_increase > 0.05:
    return "WARNING"
else:
    return "NORMAL"
```

### 4. 维护Agent (MaintenanceAgent)
**决策空间**: REPLACE / RESTART / TERMINATE / IGNORE

**职责**: 自动维护和故障处理
- 识别不健康实例
- 执行自动修复策略
- 必要时替换实例

**决策依据**:
```python
if instance_unhealthy and profit_negative:
    return "TERMINATE"
elif instance_unhealthy and retry_count < 2:
    return "RESTART"
elif performance_degraded and better_available:
    return "REPLACE"
else:
    return "IGNORE"
```

## Agent协调系统

### 轻量级协调器 (AgentCoordinator)

**职责**: 协调各专业Agent，避免冲突
- 管理Agent间的依赖关系
- 处理资源分配冲突
- 收集和汇总决策结果

```python
class AgentCoordinator:
    def coordinate_cycle(self):
        # 1. 采购决策
        procurement_decision = procurement_agent.decide()

        # 2. 部署新采购的实例
        if procurement_decision.action == "BUY":
            deployment_agent.deploy(procurement_decision.instance_id)

        # 3. 监控所有实例
        monitoring_status = monitoring_agent.check_all_instances()

        # 4. 维护问题实例
        for status in monitoring_status:
            if status.state == "ALERT":
                maintenance_agent.handle(status.instance_id)
```

## 决策流程

### 每5分钟执行一次协调周期:

```
1. 采购Agent: 检查市场机会 → 决策: BUY/WAIT/SKIP
2. 部署Agent: 检查待部署实例 → 决策: DEPLOY/RETRY/SKIP
3. 监控Agent: 检查所有实例状态 → 决策: NORMAL/WARNING/ALERT
4. 维护Agent: 处理ALERT状态实例 → 决策: REPLACE/RESTART/TERMINATE/IGNORE
5. 协调器: 汇总所有决策，执行协调
```

## 实现优势

### vs 单Agent架构:

| 特性 | 单Agent | 多Agent分工 |
|------|---------|-------------|
| 决策复杂度 | 高 (多种决策类型) | 低 (单一决策类型) |
| 可维护性 | 困难 | 容易 |
| 可测试性 | 困难 | 容易 |
| 扩展性 | 困难 | 容易 |
| 故障隔离 | 差 | 好 |
| 并发执行 | 困难 | 容易 |

### 核心优势:

1. **简单可靠**: 每个Agent只做一件事，做好一件事
2. **易于理解**: 决策逻辑清晰，便于调试和优化
3. **独立测试**: 每个Agent可以单独测试和验证
4. **灵活扩展**: 添加新Agent不影响现有Agent
5. **故障隔离**: 一个Agent故障不影响其他Agent

## 下一步实现

1. **ProcurementAgent** - 专注于GPU采购决策
2. **DeploymentAgent** - 专注于自动部署
3. **MonitoringAgent** - 专注于性能监控
4. **MaintenanceAgent** - 专注于故障处理
5. **AgentCoordinator** - 轻量级协调器

每个Agent的代码预计在100-200行，决策逻辑简单明确。