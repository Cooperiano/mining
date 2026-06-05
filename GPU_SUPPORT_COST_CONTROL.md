# GPU支持 + 成本控制 - 更新说明

## 新增GPU支持（25种）

### RTX 50系列 (Blackwell)
- RTX_5090 - 365 TH/s
- RTX_5080 - 185 TH/s
- RTX_5070_TI - 150 TH/s
- RTX_5070 - 140 TH/s

### RTX 40系列 (Ada)
- RTX_4090 - 255 TH/s
- RTX_4080 - 185 TH/s
- RTX_4070_TI - 145 TH/s
- RTX_4070 - 100 TH/s
- RTX_4060_TI - 68 TH/s
- RTX_4060 - 45 TH/s

### RTX 30系列 (Ampere)
- RTX_3090_TI - 125 TH/s
- RTX_3090 - 110 TH/s
- RTX_3080_TI - 100 TH/s
- RTX_3080 - 90 TH/s
- RTX_3070_TI - 75 TH/s
- RTX_3070 - 70 TH/s
- RTX_3060_TI - 65 TH/s
- RTX_3060 - 25 TH/s

### 数据中心卡 (Hopper/Blackwell/Ada/Ampere)
- H100 - 620 TH/s
- H200 - 650 TH/s
- B100 - 700 TH/s (Blackwell DC - 估算)
- B200 - 750 TH/s (Blackwell DC - 估算)
- A100 - 320 TH/s
- L40 - 240 TH/s
- L40S - 260 TH/s
- L4 - 120 TH/s
- RTX_6000_ADA - 230 TH/s
- RTX_A6000 - 210 TH/s
- RTX_A5000 - 180 TH/s
- RTX_A4000 - 140 TH/s

---

## 成本控制

### 限制
**MAX_TOTAL_COST_USD_HR = $10.0/小时**

### 工作原理
```python
# 实时检查当前成本
current_cost = get_current_cost()  # 从vast.ai获取running实例
remaining = $10.0 - current_cost

# 竞价前检查
if new_instance_cost + current_cost > $10.0:
    [SKIP] 跳过此竞价
else:
    [BID] 继续竞价
```

### 成本状态监控
```bash
python3 cost_control.py
```

**输出示例**:
```
============================================================
  COST CONTROL STATUS
============================================================

  Current cost: $0.000/hr
  Budget limit: $10.000/hr
  Remaining: $10.000/hr
  Utilization: 0.0%

============================================================
```

---

## 使用方法

### 查看所有GPU的bid推荐
```bash
python3 offer_discovery_cost_control.py --bid
```

### 扫描市场（自动过滤PFD < 300）
```bash
python3 offer_discovery_cost_control.py --gpu RTX_5090 --limit 10
```

### 查看成本状态
```bash
python3 offer_discovery_cost_control.py --cost-status
```

### 自动竞价（带成本控制）
```bash
# Dry-run（不实际竞价）
python3 offer_discovery_cost_control.py --auto --dry-run

# 实际竞价（仅在预算内）
python3 offer_discovery_cost_control.py --auto
```

---

## 自动竞价逻辑（带成本控制）

```python
# 1. 检查当前成本
current_cost = get_current_cost()  # 例如: $2.50/hr

# 2. 计算剩余预算
remaining = $10.0 - current_cost  # $7.50/hr

# 3. 如果剩余预算为0，停止竞价
if remaining <= 0:
    [STOP] Cost limit reached
    return

# 4. 对top offers逐一竞价
for offer in top_offers[:3]:
    optimal_bid = calculate_optimal_bid(offer['gpu'])

    # 检查是否会超预算
    allowed, current_cost, remaining = check_cost_limit(optimal_bid)

    if not allowed:
        [SKIP] {GPU} - would exceed $10/hr limit
        continue

    # 竞价
    result = place_bid(offer['id'], optimal_bid)

    # 更新成本（防止意外超支）
    current_cost = get_current_cost()
    if current_cost >= $10.0:
        [STOP] Cost limit reached
        break
```

---

## 文件结构

```
/home/julian/projects/mining/
├── cost_control.py                      # 成本控制模块
├── offer_discovery_cost_control.py      # 带成本控制的offer发现
├── manager/
│   └── vast.py                          # GPU_HASHRATES已更新（25种GPU）
├── market_history.json                  # 市场扫描历史
└── GPU_SUPPORT_COST_CONTROL.md          # 本文档
```

---

## 成本保护机制

### 多层保护
1. **竞价前检查** - `check_cost_limit()` 拒绝超预算的竞价
2. **竞价后验证** - 每次竞价后重新获取当前成本
3. **实时监控** - `cost_control.py` 显示当前成本利用率

### 告警阈值
- 🟢 < 80% 利用率 - 正常
- 🟡 80-95% 利用率 - 警告（预算快耗尽）
- 🔴 ≥ 95% 利用率 - 停止竞价

---

## 预算分配示例

| GPU数量 | GPU类型 | 单价$/hr | 总成本$/hr | 剩余预算 | 状态 |
|--------|--------|---------|-----------|---------|------|
| 2 | RTX_5090 | $0.64 | $1.28 | $8.72 | ✅ 正常 |
| 3 | RTX_4090 | $0.45 | $1.35 | $7.37 | ✅ 正常 |
| 5 | RTX_3080 | $0.16 | $0.80 | $9.20 | ✅ 正常 |
| 1 | H100 | $1.09 | $1.09 | $8.91 | ✅ 正常 |
| 10 | RTX_3060 | $0.04 | $0.40 | $9.60 | ✅ 正常 |
| **总计** | **21 GPU** | **平均** | **$4.92** | **$5.08** | ✅ **健康** |

---

## 常见问题

**Q: 为什么当前成本是$0.00/hr？**
A: 当前没有running实例。竞价成功后，成本会更新。

**Q: 成本控制会自动kill高价实例吗？**
A: 不会。成本控制只在竞价时生效。高价实例由Phase 1的`_check_costs()`处理。

**Q: 如果竞价后成本突然涨到$15/hr怎么办？**
A: 成本控制在竞价前检查，但无法防止竞价成功后价格上涨。Phase 1的cost check会kill高价实例。

**Q: 可以临时提高成本限制吗？**
A: 可以，编辑`cost_control.py`:
```python
MAX_TOTAL_COST_USD_HR = 15.0  # 临时提高到$15/hr
```

**Q: B100/B200的算力是准确的吗？**
A: 这是估算值。Blackwell DC卡的Pearl算力需要实测验证。

---

## 监控建议

### 定期检查成本
```bash
# 每小时检查一次
*/60 * * * * cd /home/julian/projects/mining && python3 cost_control.py >> cost_monitor.log
```

### 日志监控
```bash
tail -f /home/julian/projects/mining/autodeploy.log | grep -E "Cost|STOP|SKIP"
```

---

## 下一步

1. **测试dry-run竞价**
   ```bash
   python3 offer_discovery_cost_control.py --auto --dry-run
   ```

2. **观察市场扫描**
   ```bash
   python3 offer_discovery_cost_control.py --gpu RTX_5090 --limit 10
   ```

3. **安装到cron**
   ```bash
   # 编辑cron，使用成本控制版本
   crontab -e
   # 替换autodeploy_enhanced.py为offer_discovery_cost_control.py
   ```

---

**最后更新**: 2026-06-03 21:26 GMT+8
**版本**: GPU支持25种 + 成本控制$10/hr v1.0