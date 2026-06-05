# PFLOPS/$ 质量过滤 - 更新说明

## 核心变更

### 新增阈值
- **MIN_PFD = 300** - 最小可接受的 PFLOPS/$
- **OPTIMAL_PFD = 400** - 最优/目标 PFLOPS/$

### 评分逻辑更新
```
旧逻辑：
  - dlperf_usd 线性加分（0-100分）

新逻辑：
  - PFD < 300 → 直接拒绝（score = 0）
  - PFD 300-400 → 基础分 50-100
  - PFD > 400 → 高分（100+），优先竞价
```

---

## 显示更新

### Bid表格新增列
```
  GPU               Break-even   Base Bid   Market    Optimal   Max    PFD    Quality    Exp Profit   TH/s
  ───────────────   ───────────  ──────────  ────────  ─────────  ─────  ─────   ────────   ───────────  ──────
  RTX_5090          $    0.918   $  0.643    N/A       $  0.643   $1.102  N/A     POOR        $  0.299     365
```

**Quality列颜色编码**:
- 🟢 **EXCELLENT** - PFD > 400（最优）
- 🟡 **GOOD** - PFD 300-400（可接受）
- 🔴 **POOR** - PFD < 300（拒绝）

---

## 自动竞价影响

### 旧逻辑
- 扫描所有offers
- 仅按价格比率过滤

### 新逻辑
```python
quality_offers = [o for o in offers if o["dlperf_usd"] >= MIN_PFD]

if quality_offers:
    # 只在高质量offers中竞价
    avg_price = sum(o["min_bid"] for o in quality_offers[:5]) / len(quality_offers)
else:
    # 无高质量offers → 不竞价
    return ...
```

---

## 当前状态

### 市场扫描结果（2026-06-03 21:19）
- 所有GPU显示 **POOR** 质量
- 原因：当前市场无 PFD > 300 的offers
- **这是正常的** - 系统会自动过滤低质量offers

### 解决方案
1. 等待市场出现高质量offers（周期性）
2. 或临时调整阈值（不建议 - 可能导致低盈利）

---

## 配置调整

### 修改PFLOPS/$阈值
编辑 `/home/julian/projects/mining/offer_discovery.py`:

```python
# Line ~47-48
MIN_PFD = 300.0   # 最小可接受
OPTIMAL_PFD = 400.0  # 最优目标

# 调整示例（更严格）:
# MIN_PFD = 350.0
# OPTIMAL_PFD = 450.0
```

---

## 验证

### 测试bid推荐
```bash
cd /home/julian/projects/mining
python3 offer_discovery.py --bid
```

### 查看市场扫描（带PFD过滤）
```bash
python3 offer_discovery.py --gpu RTX_5090 --limit 10
```

### 查看高质量offers
```bash
python3 << 'EOF'
import json
from offer_discovery import scan_market
offers = scan_market()
high_quality = [o for o in offers if o['dlperf_usd'] >= 300]
print(f"Total: {len(offers)} | High quality (PFD>300): {len(high_quality)}")
for o in high_quality[:5]:
    print(f"{o['gpu_name']:12} | PFD={o['dlperf_usd']:6.1f} | ${o['min_bid']:.3f}/hr")
EOF
```

---

## 监控建议

### 日志监控
```bash
tail -f /home/julian/projects/mining/autodeploy.log | grep -E "PFD|quality|EXCELLENT"
```

### 定期检查
```bash
# 每小时检查一次市场质量
*/60 * * * * cd /home/julian/projects/mining && python3 offer_discovery.py --bid >> market_quality.log
```

---

## 为什么PFLOPS/$很重要？

### PFLOPS/$ 定义
```
PFLOPS/$ = (GPU浮点运算能力) / (每小时租赁成本)
```

### 影响
- **PFD < 300** → 成本过高，盈利空间小
- **PFD 300-400** → 可接受，盈利合理
- **PFD > 400** → 高性价比，利润最大化

### 算力与成本关系
| GPU | 预期TH/s | 盈亏平衡$/hr | 需要PFD | 实际市场 |
|-----|---------|-------------|--------|---------|
| RTX 5090 | 365 | $0.92 | > 397 | 待观察 |
| H100 | 620 | $1.56 | > 398 | 待观察 |

---

## 常见问题

**Q: 为什么所有GPU都显示POOR？**
A: 当前市场无高质量offers，正常现象。系统会自动等待。

**Q: 可以临时降低PFD阈值吗？**
A: 可以，但不建议。低PFD可能导致低盈利甚至亏损。

**Q: PFD > 400 一定会盈利吗？**
A: 不一定，还需考虑：网络延迟、矿池费用、PRL价格波动。

**Q: 如何找到PFD > 400的offers？**
A: 等待市场扫描自动发现，或手动运行：
```bash
python3 offer_discovery.py --auto --dry-run
```

---

**最后更新**: 2026-06-03 21:19 GMT+8
**版本**: PFLOPS/$ 质量过滤 v1.0