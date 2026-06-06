# Mining Skills — 实例检查部署 & 自动部署

> 整合自：SKILLS/instance-inspect-deploy.md、SKILLS/mining-autodeploy.skill.md
>
> 最后更新：2026-06-06

---

## 1. 实例检查与部署 (Instance Inspect & Deploy)

### 触发场景

- 检查新实例的 IP、GPU 等信息
- 连接 / SSH 到实例
- 部署挖矿软件到指定实例
- 获取实例 SSH/IP 详情
- 检查新租 vast.ai 机器状态

### 可用命令

所有命令从 `mining/` 项目根目录运行：

| 命令 | 用途 |
|------|------|
| `python3 minerctl.py list` | 列出所有矿机 (自有 + vast.ai) |
| `python3 minerctl.py vast list` | 仅列出 vast.ai 实例 |
| `python3 minerctl.py vast ssh <id>` | 获取 vast.ai 实例 SSH URL |
| `python3 minerctl.py vast wait <id>` | 等待实例进入 running 状态 |
| `python3 minerctl.py vast deploy <id>` | 部署 Pearl miner |
| `python3 minerctl.py vast kill <id> [reason]` | 销毁 vast.ai 实例 |
| `python3 minerctl.py vast autodeploy` | 执行一次自动部署扫描 |
| `python3 cost_report.py` | 利润/成本报告 |
| `python3 minerctl.py dashboard [-w SEC]` | 实时挖矿面板 |

### 新实例处理流程

#### Step 1: 检查实例状态

```bash
python3 minerctl.py vast list
# 或 JSON 格式：
vastai show instances --raw | python3 -m json.tool
```

#### Step 2: 获取连接信息

```bash
python3 minerctl.py vast ssh <INSTANCE_ID>
```

#### Step 3: 检查实例规格

```bash
vastai ssh-url <INSTANCE_ID>
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@<IP> -p <PORT> "nvidia-smi"
```

完整检查：

```bash
ssh -o StrictHostKeyChecking=no root@<IP> -p <PORT> \
  "echo '=== CPU ===' && nproc && \
   echo '=== RAM ===' && free -h && \
   echo '=== GPUs ===' && nvidia-smi && \
   echo '=== Disk ===' && df -h /workspace && \
   echo '=== Network ===' && curl -s --connect-timeout 3 https://api.ipify.org"
```

#### Step 4: 部署 Pearl Miner

```bash
python3 minerctl.py vast deploy <INSTANCE_ID>
```

自动执行：
1. 获取 SSH URL
2. 验证出站网络
3. 检测 GPU 数量和类型
4. Ping 所有矿池节点，选最低延迟
5. 生成部署脚本 (via `manager/deploy.py`)
6. 通过 SSH 管道执行脚本，下载 alpha-miner v1.7.6
7. nohup 启动 miner

#### Step 5: 快速 SSH 会话

```bash
vastai ssh-url <INSTANCE_ID> | xargs -I {} sh -c 'ssh -o StrictHostKeyChecking=no "{}"'
```

---

## 2. 自动部署 (Mining Autodeploy)

### 用法

```
/mining-autodeploy
```

### 自动部署周期

每 5 分钟通过 OpenClaw cron (`spearl-autodeploy`) 在隔离 session 中运行。

#### 周期步骤：

1. **成本检查** — 销毁价格/GPU 超过型号特定阈值的实例
2. **低效检查** — 销毁 GPU worker 低于阈值（含热身保护：1h 平均 < 阈值 30% 时跳过）
3. **部署新实例** — 自动部署到未部署、非黑名单的实例

### 阈值计算 (按 GPU 型号)

| GPU | 参考算力 | At $0.78/PRL |
|-----|---------|--------------|
| RTX 5090 | 365 TH/s | $1.10/GPU |
| RTX 4090 | 255 TH/s | $0.77/GPU |
| RTX 5080 | 185 TH/s | $0.56/GPU |
| RTX 5070 Ti | 150 TH/s | $0.45/GPU |
| RTX 3080 | 90 TH/s | $0.27/GPU |
| RTX 3060 Ti | 65 TH/s | $0.20/GPU |

公式：`(expected_th / 1000) × 3.226 × prl_price × 1.2`

PRL 价格从 `electron-app/state/config.json` 的 `prl_price` 字段读取。

### 杀机阈值 (低效 worker 销毁)

来自 `electron-app/state/config.json`：

| GPU | 最低 TH/s |
|-----|----------|
| RTX 5090 | 250 |
| RTX 4090 | 180 |
| RTX 4060 Ti | 48 |
| H100 | 430 |

低效检查有**热身缓冲**：当 1h 平均算力 < 阈值的 30% 时跳过（刚部署，还没有积累矿池数据）。

### 定价模型

- **所有实例必须是中断型 (bid)** — 不使用 on-demand
- 价格通过 vast.ai 竞价系统设置
- `.vast_saved` 记录已知好机器和最高竞价
- `re_rent.py` 以竞价价格重新租用保存的机器

---

## 3. 利润计算参考

### 核心公式

```
Earnings ($/hr) = (th_s / 1000) × earn_rate × prl_price
Net Profit ($/hr) = Earnings - Rental_Cost - Electricity_Cost
Break-even TH/s = (cost_per_hour / prl_price) × 1000 / earn_rate
```

| 参数 | 值 | 来源 |
|------|-----|------|
| `earn_rate` | 3.226 PRL/hr per PH/s | AlphaPool |
| `prl_price` | $0.78 | `config.json` (手动) |
| `electricity_price` | $0.085/kWh | `config.json` |
| `owned_total_watts` | 500W | `config.json` (station + lab1 + laptop) |

### 自有硬件

| 机器 | GPU(s) | 功耗 | 预计算力 |
|------|--------|------|---------|
| station | RTX 3080 | 320W | ~90 TH/s |
| lab1 | 2× RTX 4060 Ti | 320W | ~135 TH/s |
| laptop | RTX 3060 | 95W | ~25 TH/s |
| **合计** | | **500W** | **~250 TH/s** |

自有设备电费：`(500/1000) × $0.085 = $0.043/hr`

### Session P&L 跟踪

Electron app (`profit-engine.js` + `session-store.js`) 跟踪每次租赁：

1. 生命周期：Created → Searching → Renting → Deploying → Mining → Completed/Killed
2. 每条 session 记录：worker_name、gpu_type、rental_cost_per_hour、electricity_cost_per_hour、hashrate_samples (最多 1000)
3. 历史数据持久化在 `state/sessions.json`
4. Dashboard 的 History tab 展示每条 session 的 P&L

---

## 4. 故障排查

| 问题 | 检查 |
|------|------|
| 实例无法 SSH | `minerctl.py vast wait <id>` — 可能还在启动 |
| 部署失败 (网络) | 实例无出站网络 — 销毁：`minerctl.py vast kill <id> "no network"` |
| Miner 不在 dashboard | SSH 进入：`tail -50 /root/mining/miner.log` |
| 低算力 | 自动销毁（5090 低于 250 TH/s），有热身缓冲 |
| Worker 名称错误 | 格式：`{gpu_type}x{gpu_count}-{last4_of_instance_id}.gpuN` |

---

## 5. 状态文件

| 文件 | 用途 |
|------|------|
| `electron-app/state/config.json` | 用户配置 |
| `electron-app/state/sessions.json` | Session 历史 (P&L) |
| `electron-app/state/price_cache.json` | 缓存的交易所价格 |
| `.vast_deployed` | 已部署 miner 的实例 ID |
| `.vast_bad` | 失败或已销毁的实例 ID |
| `.vast_saved` | 已知好机器（用于重新租用） |
| `.vast_blacklist` | 问题主机黑名单 |

---

## 6. 配置参考

| Key | 当前值 | 说明 |
|-----|--------|------|
| `prl_price` | 0.78 | PRL 价格 |
| `electricity_price_usd_kwh` | 0.085 | 电价 |
| `owned_total_watts` | 500 | 自有设备总功耗 |
| `min_th_5090` | 250 | 5090 杀机阈值 |
| `min_th_4090` | 180 | 4090 杀机阈值 |
| `min_th_4060_ti` | 48 | 4060Ti 杀机阈值 |
| `kill_threshold_gpu_count` | 2 | 低于阈值的 GPU 数触发销毁 |
| `earn_rate` | 3.226 | 矿池收益系数 |
| `api_url` | https://pearl.alphapool.tech/api/miner/ | 矿池 API |
| `automation_enabled` | true | 自动化总开关 |
| `auto_deploy_enabled` | true | 自动部署 |
| `auto_destroy_enabled` | false | 自动销毁 (默认关闭) |
| `dry_run` | false | 只记录不执行 |
| `max_destroys_per_hour` | 2 | 每小时最大销毁数 |
| `consecutive_failures_before_destroy` | 3 | 连续失败阈值 |
| `new_instance_protection_minutes` | 15 | 新实例保护期 |
