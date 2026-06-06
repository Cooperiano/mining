# Pearl Miner 自动修复、Fallback 与依赖审计

更新日期：2026-06-04

## 1. 当前结论

Pearl Miner 目前不是一个完全独立的 `.app`，而是一个 Electron 控制台，加上项目根目录中的 Python、Shell 脚本和本机命令行工具。

当前已经存在自动管理行为：

- Dashboard 每 5 秒刷新矿池数据。
- Instances 列表约每 15 秒刷新，健康检查约每 60 秒执行。
- Electron 主进程每 60 秒无条件执行 `./manage.sh deploy`。
- `manage.sh deploy` 会调用 `autodeploy_cron.py`。
- 自动部署周期会检查价格、检查部分低算力 5090、销毁不符合条件的实例，并部署尚未部署的 running 实例。

因此，正常情况下不需要手动点击每个新实例的 Deploy。但是当前自动管理缺少明确总开关、失败重试上限、冷却期和完整审计，自动销毁策略也需要进一步加保护。

## 2. Electron App 当前依赖

### 2.1 App 内已打包文件

`package.json` 当前只把以下主要文件打进 `.app`：

- `main.js`
- `preload.js`
- `renderer.js`
- `index.html`
- `styles.css`
- `pool.js`
- `profit-engine.js`
- `session-store.js`
- `vast.js`
- `price.js`
- `gpu.js`
- 初始 `state/`

Node 运行时依赖只有 Electron 自带模块和 Node 标准库。`electron` 与 `electron-builder` 是构建依赖。

### 2.2 App 外部项目文件依赖

打包后的 App 仍使用硬编码路径：

`/Users/juliancooper/Desktop/projects/mining`

运行时直接调用：

- `deploy_one.py`
- `manager/vast.py`
- `manager/deploy.py`
- `manage.sh`
- `autodeploy_cron.py`
- `.vast_deployed`
- `.vast_bad`
- `.vast_blacklist`
- `/tmp/autodeploy.log`

如果项目目录被移动、删除或换到另一台电脑，Instances、Deploy、Autodeploy 和部分状态功能会失败。

### 2.3 本机程序依赖

当前机器已经安装：

- `/opt/homebrew/bin/python3`
- `/opt/homebrew/bin/vastai`
- `/usr/bin/ssh`
- `/usr/bin/curl`

本机还需要：

- Vast.ai CLI 已登录并持有有效 API Key。
- 网络可以访问 Vast.ai、AlphaPool 和 GitHub Release。
- SSH 可以访问 Vast 实例。

### 2.4 外部网络服务依赖

- Vast.ai CLI/API：实例列表、SSH 地址、账单、销毁实例。
- `pearl.alphapool.tech`：钱包、worker、矿池统计。
- `eu1/eu2/us1/us2/sg1.alphapool.tech:5566`：挖矿连接和节点选择。
- GitHub Release：远程实例下载 `alpha-miner v1.7.6-beta`。
- SafeTrade、Gate.io、MEXC、CoinGecko：PRL 价格。

### 2.5 远程实例依赖

远程 Vast 实例需要提供：

- Linux root SSH 权限。
- NVIDIA 驱动与 `nvidia-smi`。
- `bash`、`timeout`、`curl`、`base64`、`pkill`、`pgrep`、`nohup`。
- Python 3，用于 TCP 延迟测试。

## 3. 当前发现的风险

### P0：自动销毁缺少保护开关

Electron 启动后每分钟执行自动部署周期。该周期可能因为价格过高或低算力而销毁实例。

建议增加：

- `automation_enabled`
- `auto_deploy_enabled`
- `auto_repair_enabled`
- `auto_destroy_enabled`，默认关闭
- `dry_run`
- 每小时最大销毁数量
- 销毁前连续异常次数
- 新实例保护期

### P0：Config 面板与 Python 自动部署读取不同配置

Electron App 保存配置到：

`~/Library/Application Support/pearl-miner/state/config.json`

但 `manager/vast.py` 当前读取：

`electron-app/state/config.json`

这意味着在 Config 面板修改价格和阈值后，Python 自动部署可能继续使用旧配置。

建议让 Electron 启动 Python 时传入统一的状态目录环境变量，例如：

`PEARL_STATE_DIR=~/Library/Application Support/pearl-miner/state`

Python 只从该目录读取配置和状态。

### P0：`.app` 不独立

Python 和 Shell 脚本没有打包进 `.app`，并且 `MINING_DIR` 是用户目录硬编码路径。

建议将运行时脚本放进 `Resources/runtime/`，通过 `process.resourcesPath` 定位；用户状态只写入 `app.getPath('userData')`。

### P1：状态存在两套来源

当前同时存在：

- 根目录 `.vast_deployed`、`.vast_bad`、`.vast_blacklist`
- Electron User Data 中的 `deployed.json`、`bad.json`、`sessions.json`

建议建立单一状态存储，至少确保所有写操作原子化，并记录更新时间、原因和执行者。

### P1：健康判断可能受矿池延迟数据影响

矿池 worker 数据可能滞后。实例本地 Miner 已停止时，矿池仍可能暂时显示算力。

建议优先级：

1. 本地 SSH 检查 Miner、GPU 和日志。
2. 矿池数据作为外部确认。
3. 两者冲突时标记 `DEGRADED`，不要立即销毁。

### P1：自动部署和手动 Deploy 可能并发

用户点击 Deploy 时，后台每分钟自动部署周期也可能部署同一个实例。

建议为每个 instance 建立操作锁，并建立全局 autodeploy 单实例锁。

### P1：部分 Config 字段目前只保存、不生效

当前自动部署间隔仍在 `main.js` 中硬编码为 60 秒。以下 Config 字段没有接入主要自动部署流程，或者只在未使用的辅助模块中出现：

- `autodeploy_interval_sec`
- `kill_on_bad_network`
- `vast_max_price`
- `vastai_disk_gb`
- `vast_search_gpu`
- `vast_search_min_gpus`
- `vast_verified_only`
- `min_th_4090`
- `min_th_4060ti`
- `kill_threshold_gpu_count`

Config 面板应明确显示字段是否生效，未接入的字段不应让用户误以为已控制自动化行为。

### P1：Autodeploy Log 路径不一致

Electron 和 `manage.sh log` 读取 `/tmp/autodeploy.log`，但 `autodeploy.sh` 实际写入项目根目录的 `autodeploy.log`。这会导致 Autodeploy 面板日志为空或过期。

建议所有进程写入统一的 User Data 日志目录，并由 Electron 主进程直接转发自动部署周期输出。

## 4. 建议的实例状态模型

每个实例只允许处于一个主状态：

| 状态 | 含义 | 自动动作 |
|---|---|---|
| `UNAVAILABLE` | loading、created、exited 等不可访问状态 | 等待，不部署 |
| `PENDING` | running，但尚未部署 | 自动部署或等待人工确认 |
| `DEPLOYING` | 部署执行中 | 禁止重复操作 |
| `HEALTHY` | Miner、GPU、本地算力、矿池数据正常 | 仅监控 |
| `DEGRADED` | 部分信号异常，但仍可能在工作 | 自动诊断和有限修复 |
| `REPAIRING` | 自动修复执行中 | 禁止重复修复 |
| `QUARANTINED` | 连续失败，暂停自动动作 | 等待人工处理 |
| `DESTROY_CANDIDATE` | 满足销毁条件，但尚未销毁 | 等待保护期或人工确认 |

每次状态变化都应写入事件记录：

- 时间
- instance ID
- 原状态和新状态
- 触发原因
- 检测证据
- 自动执行的动作
- 动作结果

## 5. 自动修复策略

### 5.1 Miner 不运行

检测条件：

- SSH 可用。
- `alpha-miner` 进程不存在。

自动修复：

1. 检查 `/root/mining/alpha-miner` 和 `mine.sh` 是否存在。
2. 存在时只重启 Miner。
3. 重启失败后重新部署。
4. 连续 3 次失败后进入 `QUARANTINED`。

不要因为第一次失败直接销毁实例。

### 5.2 GPU 负载过低或没有本地算力

自动修复：

1. 连续检测 3 次，避免启动期误判。
2. 记录 `nvidia-smi`、Miner 日志和显存。
3. 重启 Miner 一次。
4. 仍异常则重新部署一次。
5. 仍异常则进入 `QUARANTINED` 或 `DESTROY_CANDIDATE`。

### 5.3 矿池离线，但本地算力正常

自动修复：

1. 测试所有 AlphaPool 节点 TCP 5566。
2. 切换到可连接且延迟最低的节点。
3. 重启 Miner。
4. 等待至少 2 至 5 分钟再判断矿池 worker。

### 5.4 SSH 不可用，但矿池在线

状态设为 `DEGRADED`。

- 不重部署。
- 不销毁。
- 延长检查间隔并持续观察矿池算力。
- 只有矿池也离线并连续多次失败后，才进入人工处理或销毁候选。

### 5.5 成本超过阈值

不建议立即销毁。建议：

1. 连续超过阈值至少 10 分钟。
2. 使用真实 PRL 价格、实际池算力和实例总成本计算利润。
3. 留出可配置安全边际。
4. 标记 `DESTROY_CANDIDATE`。
5. 只有 `auto_destroy_enabled=true` 时才自动销毁。

## 6. Fallback 设计

### 6.1 数据源 Fallback

- Vast 列表失败：保留最后一次成功结果，并显示数据年龄。
- 矿池 API 失败：保留缓存，不把所有 worker 立即判定为离线。
- PRL 价格失败：依次使用交易所缓存、手动价格、默认价格，并显示来源。
- SSH 失败：结合矿池在线状态，不立即判定实例死亡。

### 6.2 部署 Fallback

- 最优矿池不可用时按固定顺序尝试其他节点。
- GitHub 下载失败时使用本地缓存的、经过校验的 Miner 文件。
- 新版本 Miner 启动失败时回退到上一已验证版本。
- 重部署前保留旧 `mine.sh` 和最近日志。

### 6.3 自动化 Fallback

出现以下情况时，自动切换为只监控模式：

- Vast API/CLI 连续失败。
- 配置无法读取或校验失败。
- 状态文件损坏。
- 单小时修复或销毁次数超过上限。
- 多个实例同时异常，疑似矿池或网络公共故障。

只监控模式下禁止部署和销毁，只继续采集数据并显示告警。

## 7. 推荐实施顺序

### 第一阶段：先保证不会误操作

1. 增加自动化总开关和 `auto_destroy_enabled=false`。
2. 修复 Config 与 Python 的统一配置路径。
3. 增加 instance 操作锁、重试次数和冷却时间。
4. 为所有自动动作写入审计事件。

### 第二阶段：自动修复

1. 实现 Miner restart。
2. 实现 pool switch。
3. 实现有限次数 redeploy。
4. 实现 `QUARANTINED` 和人工解除。

### 第三阶段：独立打包

1. 将 Python/Shell runtime 打进 `.app`。
2. 移除硬编码项目路径。
3. 启动时检查 `python3`、`vastai`、SSH 和 Vast 登录状态。
4. 增加 Dependencies/Diagnostics 面板。

### 第四阶段：受保护的无人值守

1. 利润驱动的销毁候选。
2. 多次确认和保护期。
3. 自动销毁和替换实例。
4. 通知、日报和异常汇总。

## 8. 建议最终管理原则

- 自动监控可以积极执行。
- 自动重启和切换矿池可以有限重试。
- 自动重新部署需要冷却期和次数限制。
- 自动销毁必须默认关闭，并且需要多信号、多次确认。
- 当公共依赖异常时，系统必须退回只监控模式。
- 所有自动动作必须可解释、可追踪、可人工覆盖。
