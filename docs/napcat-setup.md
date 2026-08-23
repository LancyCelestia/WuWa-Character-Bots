# NoneBot + NapCat 连接 QQ 配置指南

目标：机器人（NoneBot2，本项目）通过 NapCat（QQ 客户端协议端）接入 QQ，
只在本机运行，不碰第三方框架账号。

## 1. 安装与启动 NapCat

NapCat 官方文档：https://napneko.github.io/

1. 下载 NapCat（NapCatQQ）——推荐 **NapCat.Win 一键包**（Windows）或
   按官方文档用「QQ9 一键修补」方式启动。
2. 用你自己的 QQ 小号（不要用主号，有风控风险）扫码登录 NapCat。
3. 打开 NapCat WebUI（默认 http://127.0.0.1:6099）。

### 1.1 扫码登录（被踢下线后重新登录也走这里）

1. 启动 NapCat（一键包 launcher 或 QQ9 修补启动），留意启动日志里的 WebUI 地址：
   `[info] [NapCat] [WebUi] WebUi User Panel Url: http://127.0.0.1:6099/webui?token=xxxx`
   （token 也可在 NapCat 配置目录的 `webui.json` 里找到）。
2. 浏览器打开该地址 → 进入「QQ 登录」→ 点「QRCode」二维码登录。
3. 用手机 QQ 扫二维码并确认；如手机提示「下次登录无需手机确认」建议勾选。
4. 登录成功后按提示修改一次 WebUI 密码；再去「网络配置」确认 3001 的 WebSocket 服务器还在运行（配置按 QQ 号存在 `onebot11_<QQ号>.json`，重登一般不会丢）。

- 小掉线（凭证仍有效）：重新打开 NapCat → 上面第 2-3 步重新扫码即可。
- 凭证失效/风控：只能重新扫码；若提示「安全中心/涉嫌违规」先停用几小时，保持同一网络/IP 再登，必要时换一个 QQ 小号。

## 2. NapCat 侧：开一个带 token 的 WebSocket 服务器

在 NapCat WebUI →「网络配置」→「新建」：

- 类型：**WebSocket 服务器**（NapCat 当服务端，NoneBot 主动连）
- Host：`127.0.0.1`
- 端口：`3001`
- Access Token：填一个只有你知道的 token（例如 `<你的token>`，请自行保管）
- 保存后确认状态为运行中

> 本项目用「反向 WS」模式：NoneBot 作为客户端连接 NapCat 的 WS 服务。
> 好处：NapCat 无需知道机器人地址；重启机器人不会影响 NapCat。
> token 必须与下面 `.env.prod` 中的 `access_token` 完全一致。

## 3. 本项目侧：配置并启动

`.env.prod` 已配置好（该文件在 .gitignore 中，勿提交到 git）：

```env
DRIVER=~fastapi+~httpx+~websockets
ONEBOT_WS_URLS=["ws://127.0.0.1:3001/?access_token=<与NapCat一致的token>"]
LOCALSTORE_USE_CWD=true
```

> 把 `<与NapCat一致的token>` 换成第 2 步填写的真实 token。
> 真实 token 只存在于本地 `.env.prod`，不要写进文档、提交或日志。

首次运行前先初始化 ORM 数据库（PostgreSQL + asyncpg，本机安装在 C:\Software\PostgreSQL\17，服务名 postgresql-x64-17）：

```powershell
cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot
.venv\Scripts\nb orm upgrade
.venv\Scripts\nb orm check   # 应提示：没有检测到新的升级操作
```

启动方式二选一：

```powershell
# A. 用 nb-cli（首次先 pip install nb-cli）
cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot
.venv\Scripts\python -m pip install nb-cli
.venv\Scripts\nb run

# B. 直接跑（bot.py 已注册 OneBot V11 适配器）
.venv\Scripts\python bot.py
```

> nb-cli 1.7 已移除 `--env-file` 选项；直接运行 `nb run` 即可，
> NoneBot 会默认加载 `.env` + `.env.prod`，不要给 `nb run` 再加 `--env-file` 参数。

看到日志里有 `OneBot V11` 适配器加载、连接 3001 成功即完成。
然后在 QQ 里给机器人小号发消息（或拉进群）测试：`/bot status`、`/bot logs`、`岸宝 你好`。

## 4. 驱动与适配器选型（结论）

| 组件 | 需要吗 | 说明 |
|---|---|---|
| 驱动器 `~fastapi+~httpx+~websockets` | ✅ 装 | 反向 WS 客户端 + HTTP 服务（文件托管/健康检查用） |
| 适配器 `nonebot-adapter-onebot` | ✅ 已配 | NapCat 就是 OneBot V11 协议，**不需要** adapter-qq |
| `nonebot-adapter-qq` | ❌ 不装 | 那是 QQ 官方 API（频道/开放平台，需申请 credentials），NapCat 路线用不到 |
| `nonebot-adapter-mail` | ⏸ 暂不装 | 未来要发邮件再加（pyproject 已预留，装了才激活） |
| 驱动器 Quart / 其他 | ❌ 不装 | FastAPI 已够用 |
| `nonebot-plugin-orm[postgresql]` + `asyncpg` | ✅ 装 | PostgreSQL ORM 底座（Windows 用 asyncpg 驱动）；启动前执行 `nb orm upgrade` |

NapCat 的「驱动器」是它自己面板里的插件类型（如 LLOneBot 插件），
与 NoneBot 的驱动器是两回事：**NapCat 面板里默认插件即可，不用额外装**。
