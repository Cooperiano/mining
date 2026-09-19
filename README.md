# Pearl Miner Ops — GPU 算力运营系统

一个自驱动的 GPU 算力运营系统：实时扫描 [vast.ai](https://vast.ai) 算力市场，按利润率自动租用实例、部署矿机、监控健康度、动态调价、淘汰亏损实例。核心是一个 **multi-agent 决策层** + **利润感知控制器**，外加 Electron 桌面端和 FastAPI Web Dashboard 两套 UI。

> 这套系统是为真实运营写的，不是 demo。下面所有逻辑（成本控制、动态竞价、kill 决策、审计）都在生产中实际跑过，处理过真实的宕机、抢占、价格波动。

---

## 为什么这个项目

把一个大模型 Agent 放到**有真实金钱后果**的环境里跑——每个决策（部署、提价、淘汰）都直接对应花出去的钱或赚到的收益。它逼着你把"LLM 输出一段 JSON"这种玩具，变成一个有兜底、有审计、有降级的工程系统。下面这些设计都是从这个约束长出来的。

---

## 系统能力

| 能力 | 实现 |
|------|------|
| **Multi-agent 决策** | `PoolAgent`（运维：KILL/KEEP 决策）+ `AutonomousAgent`（状态机：IDLE→ANALYZING→DECIDING→EXECUTING→MONITORING）+ `PoolCoordinator`（周期调度） |
| **LLM 结构化输出** | Agent 输出严格 JSON 决策数组（`action / reasoning / confidence`），不是自由文本 |
| **利润感知控制器** | `earnings/hr - cost/hr` 实时计算 margin，按 SAFE/WATCH/NO_CHASE/REPLACE 四档分级处理 |
| **动态竞价** | 抢占式实例上自动提价保命 / 降价省成本，带 cooldown + hysteresis 防抖 |
| **成本控制** | 预算上限、`max_destroys_per_hour` 限流、DLPerf/$ 质量门、`dry_run` 只记录不执行 |
| **审计** | 每次 kill/deploy/bid 动作落盘 `cycle_log`、`bid_history`，可回溯每次决策的 reasoning |
| **可观测** | Electron dashboard 或 FastAPI Web UI，实时看实例池、margin、收益、成本 |
| **桌面端打包** | Electron + electron-builder，产出 macOS DMG |

---

## 架构

```
mining/
├── manager/                       # Python 后端 — 运营核心逻辑
│   ├── vast.py                    # 核心循环：autodeploy / check-and-kill / 实例管理
│   ├── bid_manager.py             # 动态竞价 V1（margin 分级 + 提价/降价）
│   ├── instance_manager.py        # 实例生命周期：running/bid/kill 状态机
│   ├── audit.py                   # 审计日志
│   ├── orchestrator_main.py       # 编排器主循环
│   └── dashboard.py               # 数据聚合
│
├── mining-agent-system/           # Multi-agent 决策层
│   ├── coordinator.py             # PoolCoordinator — 周期调度，维持目标实例池规模
│   ├── agents/
│   │   ├── base.py                # BaseAgent + Decision 数据类
│   │   ├── specialized.py         # PoolAgent — LLM 驱动的 KILL/KEEP 运维决策
│   │   └── autonomous_agent.py    # AutonomousAgent — 完整状态机，自驱部署
│   ├── tools/
│   │   ├── vast_tools.py          # vast.ai API 封装（实例/offer/健康检查）
│   │   └── profitability_tools.py # 利润率计算
│   └── agents/llm_client.py       # LLM 客户端（Anthropic SDK，可切 DeepSeek/OpenAI）
│
├── web/                           # FastAPI Web Dashboard（Electron 的替代 UI）
│   ├── app.py                     # FastAPI 工厂 + 后台 poll 循环
│   ├── routes_dashboard.py        # 实时大盘 + 收益
│   ├── routes_config.py           # 配置读写
│   ├── routes_records.py          # 历史记录
│   └── routes_providers.py        # 多 provider
│
├── electron-app/                  # Electron 桌面端
│   ├── main.js                    # 主进程（spawn Python 后端 + IPC）
│   ├── renderer.js                # 全部 UI 渲染（vanilla JS）
│   ├── profit-engine.js           # 利润计算引擎
│   ├── gpu.js                     # GPU 型号注册表
│   └── package.json               # electron-builder → DMG
│
└── deploy.sh                      # 在 vast.ai 实例上执行的部署脚本
```

**通信**：Electron 主进程通过 `child_process.spawn` 拉起 Python 后端，Renderer ↔ Main 走 IPC。Web 版则是 FastAPI 直接暴露 REST。

---

## Multi-agent 决策层

这是项目里最值得讲的部分。

### PoolCoordinator（编排）
维护一个目标规模的实例池，每个周期：
1. 列出当前所有实例
2. 交给 `PoolAgent` 做健康判定
3. 淘汰不健康的，缺额时机械补一个

### PoolAgent（LLM 运维决策）
读取每个实例的健康指标（SSH 通不通、`nvidia-smi`、GPU 利用率/温度、miner 进程），喂给 LLM，**强制输出 JSON 决策**：

```json
[
  {"instance_id": "39134972", "action": "KILL", "reasoning": "GPU 利用率 3%，miner 进程已死", "confidence": 0.95},
  {"instance_id": "39136623", "action": "KEEP", "reasoning": "利用 88%，温度 64°C，正常", "confidence": 0.9}
]
```

约束硬编码在 system prompt 里（失联必杀、利用率<10%可杀、温度>85°C可杀、否则 KEEP），不靠模型自觉。

### AutonomousAgent（状态机）
完整自驱循环：`IDLE → ANALYZING → DECIDING → EXECUTING → MONITORING → ERROR`。带预算上限、最大实例数、最低利润分门槛。

---

## 利润模型与动态竞价

### 核心公式
```
earnings_per_hour = (h1_th / 1000) × EARN_RATE × PRL_PRICE
margin_per_hour   = earnings_per_hour - cost_per_hour
```

`h1_th` 用池子报的**1 小时平均算力**（live 算力波动太大，会误杀）。

### Kill 决策
```
if avg_h1 < min_threshold:           → KILL
if avg_h1 < min_threshold × 0.3:     → SKIP（刚启动预热保护）
```

### 动态竞价 V1（margin 分级）
| 档位 | margin/hr | 动作 |
|------|-----------|------|
| SAFE | > $0.10 | 被抢占过就提价保命；稳定就降价省成本 |
| WATCH | $0.03–$0.10 | 半速提价，封顶 max_bid×0.9 |
| NO_CHASE | $0–$0.03 | 只记录不动 |
| REPLACE | < $0 | 留给 V2 自动换机 |

**硬约束**：`max_bid = earnings/hr − min_margin/hr` 是唯一天花板；`dry_run=true` 绝不调 `vastai change bid`；DLPerf/$ 低于门槛的实例永不提价；cooldown + 连续读数防抖。

---

## 配置

配置中心是 `electron-app/state/config.json`（运行时状态，**不入库**）。模板见 [`electron-app/state/config.example.json`](electron-app/state/config.example.json)。

关键配置项：
- **利润**：`prl_price`、`earn_rate`、`electricity_price_usd_kwh`
- **每型号算力门槛**：`min_th_5090`、`min_th_4090`、`min_th_4060_ti`…
- **自动化**：`automation_enabled`、`auto_deploy_enabled`、`dry_run`、`max_destroys_per_hour`
- **动态竞价**：`dynamic_bid_enabled`、`bid_min_margin_hr`、`bid_raise_max_pct`、`bid_consecutive_before_adjust`
- **质量门**：`reject_dlperf_per_dollar`、`min_dlperf_per_dollar`、`preferred_dlperf_per_dollar`

---

## 运行

### Web Dashboard
```bash
python3 web/app.py
# 打开 http://localhost:8000
```

### Electron 桌面端
```bash
cd electron-app
npm install
npm start          # 开发
npm run build      # 打 DMG
```

### Agent 后端（autodeploy 循环）
```bash
python3 mining-agent-system/start_agent.py
# 或 CLI
python3 -m manager.minerctl vast autodeploy
```

> 需要设置 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL`（或切 DeepSeek/OpenAI）、vast.ai API key（`~/.config/vastai/vast_api_key`）。`dry_run: true` 时全程只记录不操作。

---

## 技术栈

- **后端**：Python（asyncio）、FastAPI
- **Agent**：Anthropic SDK（兼容 DeepSeek/OpenAI），结构化 JSON 输出
- **桌面**：Electron + electron-builder（DMG）
- **前端**：Vanilla JS（无框架，DOM 直操）
- **外部 API**：vast.ai（算力市场）、AlphaPool（矿池）

---

## 项目状态

V1 已稳定运行。Roadmap：margin 驱动自动 kill（替代纯算力门槛）、动态 token 价格、V2 自动换机、按历史 margin 选型、多矿池 failover。

---

## 安全说明

本仓库已脱敏：钱包地址、收益数据、真实实例 ID、本地路径均已替换为占位符。运行时配置与状态文件不入库（见 `.gitignore`）。

## License

[MIT](LICENSE).
