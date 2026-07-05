# QMT 测试账号接入指南

## 账号信息

| 项目 | 内容 |
|------|------|
| 券商 | 国金证券 |
| 账号类型 | 模拟交易测试账号 |
| 资金账号 | **86001853** |
| 登录密码 | **753367** |
| QMT版本 | XtItClient_x64 2.1.19.0 |

## Mac无法直接运行QMT

QMT客户端是Windows .exe程序，核心模块(xtquant)依赖Windows .pyd/.dll文件，
**无法在macOS上直接运行**。需要Windows PC或CrossOver。

## 方案一：Windows PC + 桥接服务（推荐）

### 步骤1：安装QMT（在Windows PC上）

1. 将 `/Users/guan/WorkBuddy/QuantTradingSystem/qmt/gjzqqmt_ceshi/XtItClient_x64_国金证券QMT模拟_模拟_2.1.19.0.exe`
   复制到Windows PC（U盘/局域网共享/微信发送）

2. 双击安装，记下安装目录（如 `D:\国金证券QMT模拟交易端`）

### 步骤2：启动MiniQMT模式

1. 打开QMT客户端，输入：
   - 资金账号：86001853
   - 交易密码：753367
2. **选择「极简模式」登录**（不是完整模式）
3. 登录成功后，MiniQMT窗口只显示下单功能，这就是我们需要的

### 步骤3：启动桥接服务

在Windows PC上打开终端（PowerShell或CMD），执行：

```bash
# 1. 安装依赖
pip install xtquant fastapi uvicorn requests

# 2. 修改 qmt_bridge_server.py 中的 QMT_PATH 为实际安装路径
#    默认是 D:\国金证券QMT模拟交易端

# 3. 启动桥接
python qmt_bridge_server.py --port 8580
```

看到 `QMT连接成功` 和 `Uvicorn running on http://0.0.0.0:8580` 就成功了。

### 步骤4：从Mac连接测试

```bash
# 设置桥接地址（替换为Windows PC的实际IP）
export QMT_BRIDGE_URL=http://192.168.x.x:8580

# 测试连接
python qmt_client.py health

# 查询账户
python qmt_client.py account

# 查询行情
python qmt_client.py quote 000001.SZ
```

### Windows防火墙设置

确保Windows防火墙允许端口8580：
```
设置 → 防火墙 → 入站规则 → 新建规则 → 端口 → TCP 8580 → 允许
```

## 方案二：CrossOver on Mac（可选）

如果想在Mac上直接跑QMT，需要CrossOver：

```bash
# 安装CrossOver（付费软件，https://www.codeweavers.com/crossover）
brew install --cask crossover

# 在CrossOver中：
# 1. 创建Windows 10 Bottle
# 2. 安装 Python 3.12 (www.python.org)
# 3. 安装 xtquant (pip install xtquant)
# 4. 安装并运行QMT客户端
# 5. 使用 'wine python qmt_bridge_server.py' 启动服务
```

⚠️ CrossOver方案较复杂，推荐先用Windows PC方案验证。

## QTS集成

QTS已配置好 MiniQMT 凭据（`.env`文件）：
```
MINIQMT_USER=86001853
MINIQMT_PASSWORD=753367
```

桥接就绪后，QTS的 `miniqmt_connector.py` 可以通过桥接客户端调用真实交易。

## 文件位置

| 文件 | 路径 |
|------|------|
| QMT安装包 | Claw/qmt/gjzqqmt_ceshi.rar (236MB) |
| 桥接服务端 | Claw/qmt/qmt_bridge_server.py (Windows上运行) |
| 桥接客户端 | Claw/qmt/qmt_client.py (Mac上运行) |
| QTS凭据 | QuantTradingSystem/.env |
