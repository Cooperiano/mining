# Pearl Mining 运维手册

> 整合自：MINING_NOTES.md、REPORT.md、vast.ai.md、commandlist.md
>
> 最后更新：2026-06-06

---

## 1. 系统概览

### 基本配置

- **钱包**: `prl1pyvv3nzlvyahzgdhsg4c4sm3z6ukv9zcc39genld24yw4thmet6asevn44h`
- **矿池**: AlphaPool (`pearl.alphapool.tech`)
- **挖矿软件**: alpha-miner v1.7.6-beta
- **API**: `curl -s https://pearl.alphapool.tech/api/miner/WALLET`

### 流水线

```
vast.ai rent → autodeploy.sh → deploy → alpha-miner → API → dashboard.sh
                    ↓ bad instance? → kill
```

### 关键文件

| 文件 | 用途 |
|------|------|
| `dashboard.sh` | 实时监控面板 (矿池 API，无需 SSH) |
| `autodeploy.sh` | Cron 任务：部署新实例 + 销毁低效实例 |
| `manage.sh` | 管理入口脚本 |
| `check_instance.py` | 手动利润计算器 |
| `mine_pearl.sh` | 本地启动器 (最低延迟优先矿池切换) |
| `deploy_one.py` | 单实例部署 |
| `cost_report.py` | 利润/成本报告 |
| `hashrate_report.py` | 算力报告 |
| `mining_calculator.py` | 挖矿收益计算器 |
| `parallel_deploy.py` | 并行部署 |
| `re_rent.py` | 重租保存的机器 |

### 快速命令

```bash
./dashboard.sh -w 10                  # 实时监控
bash autodeploy.sh                     # 手动触发部署
tail -f autodeploy.log                 # 查看 cron 活动
python3 check_instance.py --th 300 --price 0.56  # 利润检查
python3 minerctl.py dashboard [-w SEC] # Live mining dashboard
```

---

## 2. 利润公式

```
Earnings($/hr) = (hashrate_th / 1000) × 3.226 × $PRL_PRICE
Net Profit     = Earnings - Rental Cost - Electricity Cost
Break-even TH  = (cost_per_hour / prl_price) × 1000 / 3.226
```

| 参数 | 值 | 来源 |
|------|-----|------|
| `earn_rate` | 3.226 PRL/hr per PH/s | AlphaPool |
| `prl_price` | $0.78 | `config.json` (手动更新) |
| `electricity_price` | $0.085/kWh | `config.json` |

### 动态成本阈值

```
break_even($/hr) = (gpu_th / 1000) × 3.226 × prl_price
max_price($/hr)  = break_even × 1.2  (20% buffer)
```

**当前 PRL=$0.78 时：**

| GPU | 参考算力 | 盈亏平衡 | 杀机价 |
|-----|---------|----------|--------|
| RTX 5090 | 365 TH/s | $0.92/hr | **$1.10/hr** |
| RTX 4090 | 255 TH/s | $0.64/hr | **$0.77/hr** |
| RTX 5080 | 185 TH/s | $0.47/hr | **$0.56/hr** |
| RTX 5070 Ti | 150 TH/s | $0.38/hr | **$0.45/hr** |
| RTX 3080 | 90 TH/s | $0.23/hr | **$0.27/hr** |
| RTX 3060 Ti | 65 TH/s | $0.16/hr | **$0.20/hr** |

---

## 3. Alpha-Miner 算力基准

**数据日期:** 2026-06-02 | **来源:** 实机运行 alpha-miner 对接 live pool

### 实测算力范围

| GPU | 实测算力 (TH/s) | 架构 | VRAM |
|-----|----------------|------|------|
| RTX 5090 | 345 – 365 | Blackwell SM_120 | 32 GB |
| RTX 5080 | 175 – 185 | Blackwell SM_120 | 16 GB |
| RTX 5070 Ti | 145 – 155 | Blackwell SM_120 | 16 GB |
| RTX 4090 | 245 – 255 | Ada SM_89 | 24 GB |
| RTX 3090 | 100 – 110 | Ampere SM_86 | 24 GB |
| RTX 3070 | 65 – 75 | Ampere SM_86 | 8 GB |
| RTX 3060 Ti | 60 – 70 | Ampere SM_86 | 8 GB |
| H100 | 610 – 620 | Hopper SM_90 | 80 GB |

### 架构性能对比

| 架构 | SM 版本 | 算力范围 | 特点 |
|------|---------|---------|------|
| Blackwell | SM_120 | 145 – 365 TH/s | 顶级消费级架构，Scaling 优秀 |
| Ada | SM_89 | 245 – 255 TH/s | 代际提升显著 |
| Hopper | SM_90 | 610 – 620 TH/s | 数据中心天花板 |
| Ampere | SM_86 | 60 – 110 TH/s | 在 3060 Ti 上 3-5× 优势 |

> 完整算力参考表见 [GPU_HASHRATE_REFERENCE.md](GPU_HASHRATE_REFERENCE.md)

---

## 4. Vast.ai 管道

### Cron 自动任务

```bash
*/5 * * * * ~/projects/mining/autodeploy.sh >> ~/projects/mining/autodeploy.log 2>&1
```

每 5 分钟自动执行：
- **新实例** → 部署 alpha-miner
- **无网络** → `vastai destroy`
- **≥2 GPU 低于阈值** → `vastai destroy`
- **已销毁** → 跳过（记录在 `.vast_bad`）

### 部署流程 (deploy)

自动处理：
1. 下载 alpha-miner v1.7.6
2. Ping 所有 5 个矿池节点 → 选最低延迟
3. 自动检测 GPU 数量（不硬编码设备列表）
4. 静态难度 d=1048576 (5090)
5. 3 节点故障转移 (primary + us1 + sg1)

### 常见实例故障 (60%+ 的中断租赁)

| 症状 | 原因 | 处理 |
|------|------|------|
| `connect() failed` | 无出站网络 | Cron 自动销毁 |
| `stratum connection closed` | 矿池拒绝 IP 段 | 手动销毁 |
| `CUDA_ERROR_INVALID_DEVICE` | GPU 数量错误 | 已修复：自动检测 |
| SSH 无法连接 / key denied | 实例不稳定 | Web 控制台销毁 |
| <250 TH/s (5090) | PCIe 瓶颈 / 功耗限制 | Cron 自动销毁 |

### 矿池节点

| 区域 | 地址 | 端口 |
|------|------|------|
| Europe 1 | eu1.alphapool.tech | 5566 |
| Europe 2 | eu2.alphapool.tech | 5566 |
| US East | us1.alphapool.tech | 5566 |
| US West | us2.alphapool.tech | 5566 |
| Asia | sg1.alphapool.tech | 5566 |

---

## 5. Vast.ai CLI 速查

> API Key 存储在 `~/.config/vastai/vast_api_key`
>
> 全局参数：`--raw` (JSON)、`--explain` (API 映射)、`--curl` (curl 等价)

### 5.1 快速检查

```bash
vastai show instances                                          # 列出所有实例
vastai show instance INSTANCE_ID                               # 单实例详情
vastai execute INSTANCE_ID "nvidia-smi"                        # 远程检查 GPU
vastai execute INSTANCE_ID "ps aux | grep alpha-miner"         # 检查挖矿进程
```

### 5.2 搜索 GPU

```bash
# 最便宜的 RTX 5090
vastai search offers 'gpu_name=RTX_5090 rentable=true verified=true' -o 'min_bid_usd'

# 按性能/价格排序
vastai search offers 'gpu_name=RTX_5090 rentable=true' -o 'dlperf_usd-'

# 价格上限搜索
vastai search offers 'gpu_name=RTX_5090 rentable=true min_bid_usd<=0.56' -o 'total_flops_usd-'

# 备选 RTX 4090
vastai search offers 'gpu_name=RTX_4090 rentable=true verified=true' -o 'min_bid_usd'

# 多 GPU
vastai search offers 'gpu_name=RTX_4090 num_gpus>=2 rentable=true' -o 'total_flops_usd-'
```

**常用过滤字段：** `gpu_name`, `num_gpus`, `min_bid_usd`, `dlperf_usd`, `direct_port_count`, `inet_up/down`, `geolocation`, `reliability2`, `rentable`, `verified`

**排序 (`-o`)：** 加 `-` 降序。如 `dlperf_usd-` (性价比最高)、`min_bid_usd` (最便宜)

### 5.3 实例生命周期

```bash
# 创建实例 (on-demand)
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct

# 创建中断型实例 (竞价)
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct --min-bid 0.56

# 带部署脚本创建
vastai create instance OFFER_ID \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct \
  --onstart-cmd "curl -L -o alpha-miner https://pearl.alphapool.tech/downloads/alpha-miner && chmod +x alpha-miner && ./alpha-miner --pool stratum+tcp://us1.alphapool.tech:5566 --address WALLET --worker vast-$(hostname)"

# 自动选择最优 offer
vastai launch instance 'gpu_name=RTX_5090 rentable=true verified=true min_bid_usd<=0.56' \
  --image pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime \
  --disk 30 --ssh --direct

# 停止/启动/重启/销毁
vastai stop instance INSTANCE_ID
vastai start instance INSTANCE_ID
vastai reboot instance INSTANCE_ID
vastai destroy instance INSTANCE_ID

# 竞价调整
vastai change bid INSTANCE_ID --price 0.50

# 接受主机涨价
vastai accept price-increase INSTANCE_ID

# 回收 (销毁+重建)
vastai recycle instance INSTANCE_ID
```

### 5.4 SSH 管理

```bash
vastai create ssh-key ~/.ssh/id_ed25519.pub    # 注册 SSH key
vastai show ssh-keys                            # 列出 keys
vastai ssh-url INSTANCE_ID                      # 获取 SSH 地址
vastai scp-url INSTANCE_ID                      # 获取 SCP 地址
vastai attach ssh INSTANCE_ID KEY_ID            # 附加 key 到运行中实例
```

### 5.5 数据传输

```bash
vastai copy local:./alpha-miner INSTANCE_ID:/root/       # 上传
vastai copy INSTANCE_ID:/var/log/mining.log local:./logs/ # 下载
vastai copy INSTANCE_A:/workspace/ INSTANCE_B:/workspace/ # 实例间复制
vastai cancel copy DST_INSTANCE_ID                        # 取消传输
```

### 5.6 日志与调试

```bash
vastai logs INSTANCE_ID                                    # 实例日志
vastai execute INSTANCE_ID "nvidia-smi"                    # 远程命令
vastai execute INSTANCE_ID "tail -50 /var/log/mining.log"  # 查看挖矿日志
vastai show audit-logs                                     # 审计日志
```

### 5.7 账单

```bash
vastai show user                           # 账户信息 (余额等)
vastai show invoices-v1                    # 账单历史
vastai show invoices-v1 --start "$(date -v-7d +%Y-%m-%d)"  # 最近 7 天
vastai show deposit INSTANCE_ID            # 实例押金
vastai transfer credit USER_ID --amount 25 # 转账
```

### 5.8 市场信息

```bash
vastai metrics gpu            # GPU 市场定价
vastai metrics gpu-trends     # 市场趋势
vastai metrics gpu-locations  # 区域可用性
```

### 5.9 中断型 vs On-Demand

| 类型 | 参数 | 定价 | 风险 | 适用场景 |
|------|------|------|------|----------|
| On-demand | (默认) | 固定 $/hr | 低 | 正式挖矿 |
| Interruptible | `--min-bid 0.56` | 竞价 | 高 (可能被抢占) | 测试/溢出容量 |

### 5.10 批量操作

```bash
vastai create instances ID1 ID2 --image ... --disk 30 --ssh --direct
vastai destroy instances ID1 ID2 ID3
vastai stop instances ID1 ID2
vastai start instances ID1 ID2
```

### 5.11 模板

```bash
vastai create template my-pearl-5090 --image ... --disk 30 --ssh --direct --onstart-cmd "..."
vastai search templates 'pearl'
vastai update template TEMPLATE_ID --disk 40
vastai delete template TEMPLATE_ID
```

### 5.12 环境变量

```bash
vastai create env-var PEARL_WALLET <wallet_address>
vastai create env-var PEARL_POOL us1.alphapool.tech:5566
vastai show env-vars
vastai update env-var ENV_VAR_ID --value new_value
vastai delete env-var ENV_VAR_ID
```

---

## 6. 自有硬件运维

| 机器 | GPU | 功耗 | 管理 |
|------|-----|------|------|
| station | RTX 3080 | 320W | `systemctl --user restart pearl-miner` |
| lab1 | 2× RTX 4060 Ti | 320W | `systemctl --user restart pearl-miner` |
| laptop | RTX 3060 | 95W | Docker `pearl-miner` (restart=always) |

### 服务管理

```bash
# station & lab1: systemd
systemctl --user status pearl-miner
systemctl --user restart pearl-miner
journalctl --user -fu pearl-miner

# laptop: Docker
ssh Julian-laptop "docker logs -f pearl-miner"
ssh Julian-laptop "docker restart pearl-miner"
```

---

## 7. 快速利润检查 (手动)

```bash
# 1. 搜索当前最优 5090 价格
vastai search offers 'gpu_name=RTX_5090 rentable=true verified=true' -o 'min_bid_usd' --raw | head -5

# 2. 估算收益 (300 TH/s):
#    Earnings/hr = 300 / 1000 * 3.226 * $0.78 = ~$0.75/hr

# 3. 利润 = 收益 - 租金
#    如 $0.75 - $0.56 = $0.19/hr per 5090

# 4. 查看所有运行实例成本
vastai show instances --raw | python3 -c "
import json,sys
data=json.load(sys.stdin)
for i in data.get('instances',[]):
    print(f\"{i['id']}: {i.get('gpu_name','?')} @ \${i.get('min_bid',i.get('dph_total',0))}/hr status={i['status']}\")
"
```

---

## 8. 实例状态参考

| Status | 含义 |
|--------|------|
| `loading` | 正在拉取 Docker 镜像 (1-5 min) |
| `running` | 就绪 |
| `stopped` | 已暂停 (磁盘计费继续，GPU 停止) |
| `exited` | 容器崩溃 (查日志) |
| `offline` | 主机断联 (销毁+重试) |
| `unknown` | 主机无心跳 (销毁+重试) |
