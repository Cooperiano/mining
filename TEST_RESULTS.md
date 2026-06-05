# 测试结果 - API Key无效

## ✅ 系统就绪

### 环境配置
- ✅ Python: 3.12.3 (系统)
- ✅ vastai CLI: 已安装 (v1.0.13) 在 ~/miniconda3/bin/vastai
- ✅ 路径配置: 已添加到PATH
- ✅ 所有脚本: 已更新

### 成本控制
✅ 正常工作
```
Current cost: $0.000/hr
Budget limit: $10.000/hr
Remaining: $10.000/hr
Utilization: 0.0%
```

---

## ❌ 问题：API Key无效

### 错误信息
```json
{"error": true, "status_code": 401, "msg": "Invalid user key"}
```

### 位置
- 文件：`/home/julian/.config/vastai/vast_api_key`
- 结尾：`...dfb5`

---

## 解决方案

### 方法1: 生成新API Key（推荐）
```bash
# 1. 访问 vast.ai 控制台
https://console.vast.ai/account/api-settings

# 2. 生成新API Key
# 点击 "Create API Key" 按钮

# 3. 更新配置
export PATH="$HOME/miniconda3/bin:$PATH"
vastai set api-key YOUR_NEW_API_KEY_HERE
```

### 方法2: 直接更新配置文件
```bash
# 编辑配置文件
vim /home/julian/.config/vastai/vast_api_key

# 替换为你的新API Key
```

---

## 验证步骤

更新API Key后，运行以下命令验证：

```bash
export PATH="$HOME/miniconda3/bin:$PATH"

# 测试用户信息
vastai show user

# 测试实例查询
vastai show instances-v1

# 测试市场扫描
cd /home/julian/projects/mining
python3 offer_discovery_cost_control.py --gpu RTX_5090 --limit 5
```

---

## 下一步

1. **获取新API Key** - 访问 https://console.vast.ai/account/api-settings
2. **更新配置** - 运行 `vastai set api-key YOUR_NEW_KEY`
3. **重新测试** - 运行上述验证命令

---

**状态**: 等待API Key更新

**最后更新**: 2026-06-03 21:54 GMT+8