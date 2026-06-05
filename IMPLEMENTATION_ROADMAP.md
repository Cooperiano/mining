# 三阶段实施方案总结

## 当前状态（Phase 1 ✅ 完成）

### 已实现功能
- ✅ 实例状态监控（每分钟检查）
- ✅ 自动部署矿工到running实例
- ✅ 成本检查（自动杀高价实例）
- ✅ 性能检查（API监控，杀低算力）
- ✅ 黑名单机制
- ✅ 实时监控仪表盘

### 核心文件
```
manager/
  ├── vast.py                 # 实例管理核心
  └── deploy.py               # 部署脚本生成
autodeploy_cron.py            # Cron入口
autodeploy.sh                 # Bash包装
cost_report.py                # 成本报表
hashrate_report.py            # 算力监控
dashboard.sh                  # 可视化仪表盘
```

---

## Phase 2 实现 ✅

### 新增功能
- ✅ 市场扫描与评分
- ✅ 最优bid计算
- ✅ 自动竞价（top 3 offers）
- ✅ 历史记录追踪

### 核心文件
```
offer_discovery.py            # 市场智能
autodeploy_enhanced.py        # 增强版autodeploy（Phase 1 + 2）
market_history.json           # 历史数据
```

### 使用方法
```bash
# 查看最优bid推荐
python3 offer_discovery.py --bid

# 扫描市场
python3 offer_discovery.py --gpu RTX_5090

# 自动竞价（dry-run）
python3 offer_discovery.py --auto --dry-run

# 增强版autodeploy（整合管理+发现）
python3 autodeploy_enhanced.py
```

---

## Phase 3 整合 ✅

### 新增功能
- ✅ 实时盈利性分析
- ✅ 自动参数优化
- ✅ 全自动循环（发现+管理+优化）

### 核心文件
```
automated_profit_system.py    # 全自动盈利系统
autodeploy_phase3.sh          # Phase 3 cron脚本
.profit_state                 # 盈利状态
.optimization_state           # 优化参数
```

### 使用方法
```bash
# 盈利性报告
python3 automated_profit_system.py --report

# 参数优化
python3 automated_profit_system.py --optimize

# 全自动循环
python3 automated_profit_system.py

# Cron安装
crontab -e
*/2 * * * * /home/julian/projects/mining/autodeploy_phase3.sh
```

---

## 推荐部署路径

### 立即行动（今天）

1. **替换现有cron**:
   ```bash
   # 备份当前cron
   crontab -l > crontab_backup.txt

   # 编辑cron，替换为Phase 3
   crontab -e
   # 删除旧的 */1 * * * * ... autodeploy.sh
   # 添加:
   */2 * * * * /home/julian/projects/mining/autodeploy_phase3.sh
   ```

2. **测试盈利性报告**:
   ```bash
   python3 automated_profit_system.py --report
   ```

3. **首次手动运行（dry-run）**:
   ```bash
   python3 automated_profit_system.py --dry-run
   ```

---

### 短期优化（1-3天）

1. **调整竞价策略**:
   ```bash
   # 编辑.optimization_state
   vim /home/julian/projects/mining/.optimization_state
   # 调整bid_aggression (0.4-0.9)
   # 调整min_profit_margin (0.1-0.3)
   ```

2. **监控日志**:
   ```bash
   tail -f /home/julian/projects/mining/autodeploy.log
   ```

3. **手动触发市场扫描**:
   ```bash
   python3 offer_discovery.py --auto
   ```

---

### 中期优化（1-2周）

1. **分析历史数据**:
   ```bash
   python3 << 'EOF'
   import json
   with open("/home/julian/projects/mining/market_history.json") as f:
       data = json.load(f)
       # 分析成功率、盈利趋势
       print(f"Total scans: {len(data.get('history', []))}")
   EOF
   ```

2. **调整目标GPU列表**:
   ```bash
   # 编辑offer_discovery.py
   vim /home/julian/projects/mining/offer_discovery.py
   # 修改TARGET_GPUS列表
   ```

3. **优化cron频率**:
   ```bash
   # interruptible多 → 频率高
   */1 * * * * ...  # 每分钟
   # interruptible少 → 频率低
   */5 * * * * ...  # 每5分钟
   ```

---

## 关键指标

### Phase 1 成功指标
- ✅ 部署成功率 > 90%
- ✅ 平均部署时间 < 60秒
- ✅ 坏实例检出率 > 95%

### Phase 2 成功指标
- 📊 市场扫描频率：每小时
- 📊 竞价成功率：待测
- 📊 平均盈利margin：待测

### Phase 3 成功指标
- 📊 净利润 > $0.10/GPU/hr
- 📊 利润margin > 15%
- 📊 机队利用率 > 50%

---

## 故障排查

### 问题：市场扫描返回空结果
**原因**: 当前没有低于盈亏平衡的offer
**解决**: 这是正常的，系统会自动等待

### 问题：竞价失败
**原因**: vast.ai账户余额不足
**解决**: 检查账户余额，充值后重试

### 问题：盈利性报告显示错误
**原因**: 无法连接到AlphaPool API
**解决**: 检查网络连接，矿池API状态

---

## 下一步

1. **立即**: 安装Phase 3 cron
2. **监控**: 观察24小时日志和盈利性
3. **优化**: 根据实际数据调整参数
4. **扩展**: 添加更多GPU类型到目标列表

---

## 联系与支持

- AlphaPool文档: https://pearl.alphapool.tech
- vast.ai文档: https://console.vast.ai/docs
- 项目路径: /home/julian/projects/mining/

---

**最后更新**: 2026-06-03 21:10 GMT+8
**版本**: Phase 3 完整实现 ✅