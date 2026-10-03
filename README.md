# 守岸人 Bot（WuWa Character Bot）

以游戏《鸣潮》角色「守岸人」为人格的 QQ 聊天机器人：NoneBot2 + OneBot V11（SnowLuma）构建，
角色扮演对话之外内置行情查询、链接解析、订阅推送、媒体归档等 29+ 项日常能力，
回复统一渲染为「釉瑚云母」卡片样式（视觉值册以 `theme_tokens` 为单一事实源）；另附带 Telegram / Mail / Console 适配器。

> AI 协作者请从 [AGENTS.md](AGENTS.md) 进入（工作区规则 + 项目全貌，自动加载）；
> 新接手 AI 读 [HANDOFF-NEXT.md](HANDOFF-NEXT.md)。

## 能力全景

| 分类 | 能力 | 触发示例 |
|---|---|---|
| 人格对话 | 守岸人人格（人设+心情+怪癖+称谓偏好）、好感度 v5（8 档温和态度连续过渡）、六级角色权限、会话记忆+夜间反思+时间窗总结 | @bot 说话 |
| 提醒与笔记 | 自然语言定时提醒、Markdown 笔记、时间授时校准 | `12点提醒我…` |
| 金融行情 | 全球股指（18 指数）、个股行情（9 家科技巨头 OHLCV/市值/KDJ）、汇率（11 币种）、大宗商品、国债收益率、北向资金 | `行情` / `英伟达股价` / `美元兑人民币` |
| 生活查询 | 天气与预警、快报、百科、占卜等（全集与逐项细节以机器册 `docs/command-catalog.md` 为准） | `天气 城市` / `快报` / `塔罗` |
| 娱乐 | 点歌（5 供应商+真实榜单候选卡）、随机图、表情包、菜谱图库、戳一戳 | `点歌` / `随机图` |
| 媒体与解析 | 37+ 平台链接解析（引用/语音/转发全通）、订阅推送（B站/YT/小红书/推特/微博）、媒体归档（VLM 判类）、识图、搜图 | 直接发链接 / `/订阅` / `收藏` |
| 运维与诊断 | 每日 21:30 群通讯总结、统一错误报告卡（故障自动生成云母诊断卡）、文件出站、控制面/LLM 计费账本（默认关） | 自动 |

命令全集见 [COMMANDS.md](COMMANDS.md)（与 `/bot help` 同口径）；逐问法路由见
[docs/route-matrix.md](docs/route-matrix.md)；自动生成的逐参数教程见 [docs/command-catalog.md](docs/command-catalog.md)。

管理后端 WebUI（**在制，未验收**）：AxonHub 设计系统衍生的单文件前端，挂控制面 127.0.0.1:8742 `/ui`（Bearer 认证）；
Phase A=总览/调用统计/Token/延迟/好感度榜/日志尾流，知识库/插件/记忆图谱在二期规格。
详见 [docs/design/webui-axonhub-adoption.md](docs/design/webui-axonhub-adoption.md)。

## 快速上手

环境要求：Windows + Python 3.10+（`pyproject.toml` 锁定 `>=3.10, <4.0`）；venv 由
`scripts\dev.ps1` 自动定位到 `ChatBot_Runtime\venv`，勿手工搬动。QQ 侧需先跑 SnowLuma
（正向 WS 127.0.0.1:3001，配置见 [docs/snowluma-setup.md](docs/snowluma-setup.md)）。

启动顺序：**先 SnowLuma，后 bot.py（管理员权限）**。生产进程常驻且提权启动，只有用户能重启；
改代码必须重启 bot 才生效（铁律）。

```powershell
Set-Location 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'

# 统一任务入口（test / lint / typecheck / sync / run / console …全部任务用 help 查看）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task help"

# 离线控制台对话（不连 QQ，快速体验人格链路）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task console"

# 四门禁（每轮交付前全绿；结果以本次实跑输出为准，不在文档手写数字）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"            # 全量回归（全离线 mock）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"            # ruff
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"       # mypy
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"  # 源码树/边界体检

# 重启生产 bot 前的一键预检（已落地 051261d；7 项检查，无 FAIL 再动手）
python scripts/pre_restart_check.py
```

真机验收（bot 重启并在线后向白名单群真发能力矩阵，默认 DRY-RUN）：

```powershell
python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute
```

真实 LLM 参数与密钥只放本地 `.env`（gitignored），不写入文档/日志/Git。
绕开 dev.ps1 直跑 python/pytest 必须加 `PYTHONDONTWRITEBYTECODE=1`，临时目录指到源码树外。

## 架构极简图

```mermaid
flowchart LR
    QQ["SnowLuma（WS 3001）"] <-- forward-WS --> bot["bot.py（崩溃守卫，webhook 8080）"]
    bot --> ingest["摄取：段归一/引用反查/语音预转码"]
    ingest --> route["路由 base_router ‖ decision 影子"]
    route --> gate["门禁：黑白名单/安静时间/限流/幂等"]
    gate --> pipe["RuntimePipeline（offload 线程池）"]
    pipe --> caps["capabilities 29+ 能力"]
    caps --> render["输出治理：说人话/脱敏 → 釉瑚云母卡片渲染"]
    render --> queue["SendQueue：part 幂等/断点续发"]
    queue --> out["QQ / Telegram / Mail"]
```

完整链路与 LLM 子链路说明见 [AGENTS.md](AGENTS.md) 第三部分。

## 目录导览

```text
MyWorkspace\ChatBot\
├─ ChatBot\          唯一代码区（本工作区）：bot.py + plugins/ + personas/ + scripts/ + tests/ + docs/
├─ ChatBot_Runtime\  运行数据：venv、SQLite 库群（26 原有+media_archive/notes/web_intent_telemetry 等，实况 32，清单唯 docs/db-owners.md）、cookie、日志、缓存、头像（不可删改，默认不扫描）
└─ ChatBot_Archive\  历史归档：按日期目录压缩包 + manifest
```

代码中的 `data/...` 相对路径经 `scripts/runtime_paths.py` 全部重映射到 Runtime，
源码树永不被写（`tests/test_datafix_runtime_paths.py` 锁定）；因此不要为清理工作区
删除或压缩活动中的 SQLite、向量嵌入、记忆、Cookie、订阅和媒体库。
归档规程见 [docs/workspace-archive-policy.md](docs/workspace-archive-policy.md)。

## 文档指引

| 文档 | 定位 |
|---|---|
| [AGENTS.md](AGENTS.md) | AI 向全景（工作区规则 + 架构图 + 功能×子模块清单 + 已知问题台账），LLM 自动加载唯一入口 |
| [docs/HANDBOOK.md](docs/HANDBOOK.md) | 单一活文档（族谱/现行事实/总账/全史） |
| [docs/acceptance-manual.md](docs/acceptance-manual.md) | 验收手册（含 §6.6 重启验收清单族） |
| [HANDOFF-NEXT.md](HANDOFF-NEXT.md) | 新接手 AI 唯一交接入口（一句话现状/硬规矩/开工三步） |
| [docs/config-catalog-full.md](docs/config-catalog-full.md) | 全量配置键目录（A1-A26 分域 + 同步门禁） |
| [COMMANDS.md](COMMANDS.md) | 命令手册人读版（与 `/bot help` 同口径） |
| [docs/README.md](docs/README.md) | docs 全量索引 |

## 人格与红线

- **人格**：守岸人（《鸣潮》角色，泰缇斯系统第二实例，非 AI 设定）；人格源在
  `personas/shorekeeper/`，话术改动必须维持守岸人语气（去 AI 味）。
- **创造者**：澜汐与霞月是守岸人的创造者与唤醒者（也是生产环境的超管），这份联系写入人设
  （`personas/shorekeeper/identity.md`）。
- **红线**：好感度任何档位都不攻击、不强硬、不 R-18（红线写死在 `character/affinity.py` 态度文本）。
- **隐私与脱敏**：真实密钥只在 `.env`（gitignored），配置以 `env:变量名` 引用；出站前统一脱敏
  （盘符路径 / `BOT_XXX=` / `sk-` 形态自动打码，见 `output/plain_text.py` 的
  `redact_local_secrets`），不要绕过。
