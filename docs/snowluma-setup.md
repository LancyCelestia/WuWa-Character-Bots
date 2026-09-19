# SnowLuma + NoneBot 连接 QQ 配置指南

> 现行协议端为 **SnowLuma**（2026-09-18 起）。NapCat 未卸载，保留作回滚路径，
> 其配置与操作见 [napcat-setup.md](napcat-setup.md)。
> 本文件记录迁移后的真实配置面；改动前先读 §1 的差异表和 §2 的令牌规则。

---

## 1. 现状事实

| 项 | 值 |
|---|---|
| 安装路径 | `C:\Software\SnowLuma`（v1.14.17，自带 `node.exe`，无外部 Node 依赖） |
| 启动 | 双击 `launcher.bat`（内部 `node .\index.mjs`） |
| WebUI | http://127.0.0.1:5099 （初始密码在启动日志里，仅首次显示） |
| 配置落盘 | `config\runtime.json`（`webuiPort` 等）、`config\webui.json`、`config\ui.json` |
| 日志 | `logs\snowluma-YYYY-MM-DD.log` |
| 注入组件 | `native\snowluma-win32-x64.dll` / `.node`、`native\websocket-win32-x64.node`、`native\ffmpeg\ffmpegAddon.win32.x64.node`（语音转码单点，见 §6） |
| 许可 | 源码可见**非商业**许可，非 OSI 开源；二进制另受 `EULA.md` 约束 |

### 与 NapCat 的关键差异

| | NapCat | SnowLuma |
|---|---|---|
| 注入时机 | **启动时**：`launcher-win10-user.bat` 用 `NapCatWinBootMain.exe` 拉起并注入被修补的 QQ | **运行期**：QQ 以正常方式启动后，在 WebUI「进程」页对指定 `QQ.exe` 点「加载」注入 |
| 注入对象探测 | 由启动器从注册表定位 QQ 安装路径 | 自行轮询 `tasklist /fi "imagename eq QQ.exe"`，列出所有候选主进程 |
| 卸载注入 | 结束 QQ 进程即可 | WebUI 提供「卸载」，会断开当前会话 |
| 多账号 | 每账号一个实例（本机有 `NapCat` 与 `NapCat-school` 两套） | 单实例可挂多个 QQ 账号，各自维护会话与网络配置 |
| OneBot 配置项 | `onebot11_<QQ号>.json` 的 `network.websocketServers[]` | WebUI「配置」页的 `wsServers`（另有 `httpServers` / `httpClients` / `wsClients`） |

> **同一时刻一个 QQ 进程只能被一个 hook 接管**，且 `127.0.0.1:3001` / `:3002` 只能有一个监听者——
> 迁移时必须先把 NapCat 整条链停干净，再用干净的 QQ 走 SnowLuma。

> **运维习惯差异（必读）**：SnowLuma 默认 `hookAutoLoad=false`，属**手动注入**模式——
> QQ 客户端每次退出或重启后，都要回 WebUI「进程」页对新进程重新点一次「加载」，
> 否则 OneBot 会话随 QQ 关闭而终止，节点停止监听 3001，bot 侧表现为
> `ConnectionRefusedError [WinError 1225] 远程计算机拒绝网络连接`。
> 该开关在 `config\runtime.json`，语义为「发现 QQ 进程即自动注入」（`autoLoadOnDiscovery`）；
> 但本机同时挂着日常 QQ 时，开启它存在把日常 QQ 一并注入的风险，故保持关闭更稳妥。

### 协议端能力边界（实测，2026-09-20）

写在这里是因为这几条会直接改变 bot 侧的行为设计，不是排障项：

| 项 | 实况 | bot 侧口径 |
|---|---|---|
| **主动贴表情只支持群消息**（修法=不发） | SnowLuma 对非群消息直接抛 `emoji reactions are not supported on private messages`（`index.mjs` 三处 `if (!meta.isGroup) throw`，实测该报错 36 次）。QQ 侧本就不存在私聊表情回应通道（OIDB `0x9082` 只有群消息形态），**不是换协议端造成的退化**，也不是需要兜的异常 | `domains/meme/reactions/engine.py` 的 `maybe_react_on_message` 在 `enabled/mid` 判定之后、进入五层门**之前**按 `_is_group_session(session_key)`（只认 `group_<gid>_<uid>`）拒掉私聊：绝不出 `set_msg_emoji_like`，不占每消息去重登记、不刷失败日志。锁死用例：`tests/test_reactions.py::test_private_session_never_calls_set_msg_emoji_like` |
| 合并转发拉取会空返回 | 日志见 `[Bridge.Action] get_forward_msg failed: download forward message payload is empty`（实测 5 次） | 拉不到就当拉不到，既有降级路径不变；重复出现再评估是否要退到本地消息库 |
| 戳一戳可用 | `[Bridge.Action] group_poke params=group_id=… user_id=…` 正常下发 | 无需改动 |
| 单实例多账号 | 一个 SnowLuma 实例可挂多个号，但**每个号的默认节点端口会互相撞车**：新号自动生成 `http-default@3000` + `ws-default@3001`，与主号同名同端口 → `EADDRINUSE`，该号 OneBot 网络层起不来 | 给第二个号建节点时必须手工改端口（学校号用 3002）并删掉冗余的 `http-default`；只点「加载」不够 |

---

## 2. 令牌（Access Token）规则

SnowLuma 对 `accessToken` 有强制校验（`assessAccessToken` → `@zxcvbn-ts/core`），**不满足直接拒绝保存**：

1. 长度 **< 16 字符** → 判 `too-short`；
2. 通过后走 zxcvbn 打分，**score < 3** → 判 `guessable`。

其 zxcvbn 只挂两张字典：`diceware-common`（EFF 7776 词）与 `passwords-common`（常见密码表），
外加键盘邻接图；userInputs 固定含 `SnowLuma`、`OneBot`。

**因此旧 token 必须更换**：`ShoreKeeper`（11 位 / score 2）与 `CampusKeeper`（12 位 / score 2）均不达标。

| 端口 | 用途 | 令牌值 |
|---|---|---|
| 3001 | 主号 | 见 `.env.prod` 的 `ONEBOT_WS_URLS`（≥16 位英文短语式） |
| 3002 | 学校号 | 见 `.env.prod` 注释行（同上规则） |

> 明文只存在于两处：`.env.prod`（gitignored）与 SnowLuma 配置。**不要写进本文档或提交。**

### 更换 token 时先本地验证

无需联网、无需 npm 装包——SnowLuma 的 `server-*.js` 第 6105–11627 行是自包含的 zxcvbn core + 词表 + checker 实例，
可截取后用 `new Function` 离线复现官方评分：

```javascript
const lines = require("fs").readFileSync("C:/Software/SnowLuma/server-CLw7fwOG.js", "utf8").split("\n");
const a = lines.findIndex(l => l.includes("@zxcvbn-ts+core@4.1.2"));
const b = lines.findIndex(l => l.includes("return [...unique].slice(0, 24);"));
const { checker, normalizeUserInputs } =
  new Function(lines.slice(a, b + 2).join("\n") + "\nreturn {checker, normalizeUserInputs};")();
console.log(checker.check("候选token", normalizeUserInputs([])));
```

用 SnowLuma 自带的 node 执行：`C:\Software\SnowLuma\node.exe <脚本>`。
分数对照：`score >= 3` 可用；`ShoreKeeper` 一类 11–12 位词组合只有 2 分。

---

## 3. 迁移步骤

### 3.1 准备

1. 生成/确认新 token（§2 规则），并本地验证通过。
2. 备份现状：
   ```powershell
   Copy-Item "C:\Software\NapCat\config\onebot11_3958874605.json" "$env:TEMP\onebot11.bak.json"
   Copy-Item "<仓库>\.env.prod" "$env:TEMP\env.prod.bak"
   ```

### 3.2 停掉 NapCat 整条链（管理员 PowerShell）

> **注意：本机可能同时跑着多个 QQ 实例**（日常主号 + 机器人小号）。
> `Stop-Process -Name QQ` 或 `KillQQ.bat` 会把它们**全部**关掉。
> 推荐用下面的精准法——判断依据是**谁占着 3001**：NapCat 注入的那个 QQ 进程
> 同时监听 6099（NapCat WebUI）与 3001（OneBot），按 PID 定位不会误伤其他实例。

```powershell
$p = (Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue).OwningProcess
"占用 3001 的 QQ PID: $p"
Stop-Process -Id $p -Force
Stop-Process -Name NapCatWinBootMain -Force -ErrorAction SilentlyContinue
netstat -ano | findstr ":3001"     # 应当无输出
```

确需连日常 QQ 一起清掉时，才用粗暴法：`Stop-Process -Name QQ -Force`
（等价于 NapCat 目录下的 `KillQQ.bat`，其内容就是 `taskkill /f /im QQ.exe`）。

### 3.3 干净启动 QQ，再从 SnowLuma 注入

1. 启动 SnowLuma：`C:\Software\SnowLuma\launcher.bat`（WebUI 起在 5099）。
2. **用普通快捷方式启动 QQ**（不要用 NapCat 的 `launcher-win10-user.bat`），登录机器人小号。
3. 打开 http://127.0.0.1:5099 → **「进程」页** → 找到 QQ 主进程，状态为「可加载」时点「加载」，
   等状态走到「已在线」。

> 换注入框架后 QQ 的快速登录态**不一定**能沿用，首启可能需要重新扫码一次。

### 3.4 配置 OneBot 连接（默认节点已自动生成，通常是"改"而不是"新建"）

**注入成功且 QQ 登录后，SnowLuma 会为该账号自动创建一组默认节点**，落盘于
`config\onebot_<QQ号>.json`（文件内 `mode: "snapshot"`）：

| 自动生成的节点 | 监听 | 处理方式 |
|---|---|---|
| `http-default` | `127.0.0.1:3000` | 本项目用不到；仅本机回环，保留无害，也可删除 |
| `ws-default` | `127.0.0.1:3001` | **本项目要用的就是它**——但令牌是自动生成的 40 位随机串，必须替换 |

所以在 WebUI 的**「节点配置」**页编辑 `ws-default`（端口本来就是对的，主要改令牌）：

| 字段 | 值 | 对应 NapCat |
|---|---|---|
| 端口 | `3001` | `port` |
| Access Token | §2 的令牌（**务必替换掉自动生成的随机串**） | `token` |
| 消息格式 | `array` | `messagePostFormat: "array"` |
| 上报自身消息 | **开** | `reportSelfMessage: true` |

> `reportSelfMessage` 默认是**关**。保持关闭时机器人收不到自己发出消息的事件；
> NapCat 侧原配置为 `true`，迁移时应保持一致，不要顺手改变行为。

学校号（3002）在同一实例里另建一个节点即可（该实例会自动带 `http-default` + 各自的 `ws-*`），
`Access Token` 用另一个令牌。

> 改完令牌后，协议端即就绪：`netstat -ano | findstr ":3001"` 应显示 **SnowLuma 的 node 进程**在监听，
> 而不是 QQ.exe。

### 3.5 改 `.env.prod` 并启动 bot

```env
ONEBOT_WS_URLS=["ws://127.0.0.1:3001/?access_token=<主号令牌>"]
```

顺序不变：**先协议端，后 bot**。

```
<ChatBot_Runtime>\venv\Scripts\python bot.py
```

> 两侧令牌必须逐字一致（含大小写）。配置改动只有重启 bot 才生效。

### 3.6 验收

- 启动日志出现 OneBot V11 适配器加载且连接 3001 成功；
- `python scripts/pre_restart_check.py` —— 其中 `napcat` 项按 `.env` 的 `ONEBOT_WS_URLS`
  解析出**全部**端点逐个探（两号即 3001+3002），应显示「N 个端点全部可达」；
- QQ 里发 `/bot status`、`岸宝 你好`；
- 群聊里验证卡片渲染与合并转发（`get_forward_msg` 走的是 SnowLuma 的实现）。

---

## 4. 回滚到 NapCat

NapCat 目录与配置**未被修改**，回滚只需三步：

1. 停 QQ（同 §3.2）；
2. `.env.prod` 的 `access_token` 换回旧值，并用 `C:\Software\NapCat\launcher-win10-user.bat` 启动 NapCat，
   确认「网络配置」里 3001 的 WebSocket 服务器仍在运行；
3. 重新启动 bot。

> 若回滚后连不上，优先核对 `.env.prod` 的 token 与 NapCat `onebot11_<QQ号>.json` 里的 `token` 是否一致。

---

## 5. 排查

| 现象 | 先查 |
|---|---|
| WebUI 保存令牌被拒 | 长度是否 ≥16、zxcvbn 是否 ≥3（用 §2 的脚本先验） |
| 「进程」页看不到 QQ | QQ 是否真的在跑、是否以管理员/同权限启动、SnowLuma 是否以管理员启动 |
| 注入后一直「等待登录」 | QQ 侧登录是否完成；必要时在「进程」页先「卸载」再重「加载」 |
| bot 连不上 3001 | 先看 SnowLuma「日志」页 OneBot 是否有连接；再核对 token 逐字一致 |
| 日志每 3 秒刷 `rejected unauthorized WebSocket upgrade` | 客户端令牌与节点令牌不一致：最常见是 `ws-default` 仍是自动生成的随机串，而 bot 用的是 `.env.prod` 里的旧值（改令牌前 bot 未重启、或节点令牌没改）。两边对齐后重启 bot 即消失 |
| 端口被占 | `netstat -ano \| findstr ":3001"` 反查 PID，确认残留的 NapCat / 旧 QQ 进程已退出 |
| 日志出现 `[Bridge] session closed` → `[OneBot] session closed`，随后 QQ 进程消失 | QQ 被腾讯踢下线或客户端退出，见下方「被踢下线」 |

### 被踢下线（腾讯风控）

症状链：SnowLuma 日志 `[Bridge] session closed: UIN=…` → `[Bridge.Action] Action ingress quiesced` →
`[OneBot] session closed`，随后该 QQ 进程从 `tasklist` 消失；bot 侧表现为
`ConnectionRefusedError [WinError 1225] 远程计算机拒绝网络连接`（因为节点随会话停止监听 3001）。
**这与协议端选型无关**，NapCat 时期同样会遇到（见 [napcat-setup.md](napcat-setup.md) §1.1）。

处理：

1. 重新启动 QQ 并登录（多数情况快速登录即可恢复）；
2. SnowLuma「进程」页对新出现的 QQ 主进程重新点「加载」，等「已在线」——节点配置无需重配，会自动恢复监听；
3. 若登录时提示安全中心 / 涉嫌违规：停用数小时，保持**同一网络与出口 IP** 再登；必要时换一个小号。

降低触发概率：

- 不要短时间内反复重启 QQ、反复「加载 / 卸载」注入——迁移与调试尽量一次配好；
- 机器人账号长期挂在同一设备、同一出口 IP 上更稳；
- 被踢后不要立刻反复重登，间隔开更安全。

---

## 6. 语音出站与 silk 转码（M-66 依赖面）

bot 侧语音出站（TTS 产物 wav → QQ 语音条）**零自有转码**：wav→silk 全部由 SnowLuma 自带能力完成
（`index.mjs` 的 `encodeSilk → convertToNTSilkTct`，走 `native\ffmpeg\ffmpegAddon.win32.x64.node` 原生件），
再经 highway 上传。这是一个**未声明的外部单点依赖**（审计项 M-66），本节即其登记面（2026-09-20 收口，T103）。

### 依赖实况（T101 只读探针，2026-09-20）

| 项 | 值 |
|---|---|
| addon 文件 | `C:\Software\SnowLuma\native\ffmpeg\ffmpegAddon.win32.x64.node` |
| 体量 / 时间戳 | 6,511,104 B（≈6.5 MB），mtime 2026-09-15 |
| 文件头 | `4d 5a`（MZ，PE/Windows DLL，与 win32.x64 命名一致） |
| 内嵌版本串 | `Lavc61.19` / `Lavf61.7` ⇒ **FFmpeg 7.1 系库**（libavcodec 61.x），全量 ffmpeg_src 构建 |
| dlopen 实证 | **待真机补证**：文件在位 ≠ 加载成功（VC 运行库/架构匹配未验证）。补证动作=真机发一条语音，验收挂 [acceptance-manual.md](acceptance-manual.md) §6.6.11 的 E/R 项（R1 形态即同时判定） |

### 单点性质（T97 终态核验 + T46 读码）

- **挂 = 语音出站整体灭**：addon 装载/转码任一环节失败，所有 wav 语音（命令式 `说 X`、自动配音）全部失败，
  不是降级成纯文本；mixed（文字+语音）**整条一起失败**（原子失败语义：`buildSendElems` 循环零 try/catch，
  媒体上传发生在文本发包之前）。
- 失败**不静默**：SnowLuma 装载失败即 throw 并缓存错误（源码自书 "don't silently fall back"），与旧 NapCat
  「`pye` 吞异常→静默摘段+谎报送达」形态**相反**；bot 收到 `status:"failed"` + retcode（SnowLuma 全集
  `{100, 1200, 1400, 1404}`）+ **`wording`** 字段（注意不是 `message`/`msg`）。
- 纯 silk 文件（`#!SILK` 头）不经转码直发——所以「有时能发」不代表 addon 健康。

### 运维提示

| 症状 | 归因 | 处置 |
|---|---|---|
| 语音命令整条不发 / 整条 failed，SnowLuma 日志见 `record` 相关 throw | addon 缺失/损坏/dlopen 失败（坏 record 段=fatal 整条不发） | 核对上表文件在位与体量；该文件只随 SnowLuma 安装目录走，与 QQ 升级无关 |
| 排障时按旧 NapCat 文档找「被摘掉的段」 | 形态已变：无静默摘段，失败=整条+retcode 可观测 | 改看 SnowLuma `logs\` 与 bot 侧 failed 回执的 `wording` 根因 |

> 协议契约补充：record 段入站只消费 `file/url/path/media` 四者之一（bot 只送 `file` 本地绝对路径）；
> `duration`/`file_size` 字段被**结构性忽略**（SnowLuma 从实际字节自算时长与体积）。

---

## 7. 相关文档

- [napcat-setup.md](napcat-setup.md) —— 旧协议端（回滚路径）
- [acceptance-manual.md](acceptance-manual.md) —— 验收与接入手册
- [external-runtime-access.md](external-runtime-access.md) —— 外部运行时与工作区边界
