# P2/P3 问题台账（2026-09-13 实战审计批）

> **本文件定位**：AGENTS.md 第六部分是问题索引，本文件是 P2/P3 逐条**可执行详情**——
> 每条写清：现象是什么、问题出在哪个文件哪一行、根因是什么、影响谁、怎么修、
> 修完怎么验收。接手者无需考古即可动手。
> 分级口径沿用用户给定四级表：P0 致命 / P1 严重 / P2 一般（有绕行，排期修）/ P3 轻微（backlog）。
> P0/P1 已在 2026-09-13 当日处理完毕（见文末「本批已闭环」），此处只留活口。

---

## P2（排期修复）

### P2-1 cryptography CVE ×3 —— 上游阻塞
- **现象**：pip-audit 报 `cryptography 48.0.1` 命中 PYSEC-2026-3552/3553/3554，修复版 49.0.0/50.0.0。
- **位置**：Runtime venv 依赖图；唯一使用方 `nonebot-adapter-qq 1.7.2`（已钉死 `cryptography<49.0.0,>=43.0.3`）。
- **根因**：适配器上游版本约束与安全修复版本互斥；PyPI 上 1.7.2 已是最新（无放宽约束的版本）。
- **影响**：QQ 适配器的密码学路径。CVE 细节以 pip-audit 数据库为准；bot 场景（QQ 适配器本地签名/token）暴露面有限。
- **修法**：等 nonebot-adapter-qq 放宽到 `>=49` 后 `pip install -U cryptography`；或换用维护中的适配器分支。**禁止**无视钉死强升（2026-09-13 已试装 50.0.1 即遭 pip 依赖冲突，已回滚 48.0.1 并以 `pip check` 验证零冲突）。
- **验收**：升级后 `pip check` 零冲突 + 重跑文末 CVE 复审命令，cryptography 行消失。

### P2-2 aiosmtplib CVE ×2 —— 上游阻塞
- **现象**：pip-audit 报 `aiosmtplib 3.0.2` 命中 PYSEC-2026-2338/3805，修复版 5.1.1/5.1.2。
- **位置**：唯一使用方 `nonebot-adapter-mail 1.0.0a7`（metadata 钉死 `aiosmtplib~=3.0`）。
- **根因**：同 P2-1，跨两个大版本的修复与适配器约束互斥。
- **影响**：SMTP 客户端路径；SMTP 服务器是用户自配的可信端点，实际暴露面有限。
- **修法**：等 nonebot-adapter-mail 出支持 `aiosmtplib>=5.1.2` 的版本。
- **验收**：同 P2-1。

### P2-3 渲染 Phase 2 并发/预算解锁
- **现象**：渲染等待预算与并发框架已落地但**缺省关闭**（字节级等价安全位），真实收益未生效。
- **位置**：`plugins/bot_unified_runtime/output/render_backends.py`（`:213 max_concurrency: int = 1`、`:319/:391 wait_budget_ms` 消费点、`:453` 实例化点）；规格 `docs/design/render-pipeline-optimization-spec.md`；执行清单 `docs/perf-optimization-plan.md`。
- **根因**：Phase-1 刻意只落框架不动缺省（等重启实测后再解锁）。
- **影响**：多卡并发时渲染串行排队；固定 sleep 等待地板未消除。
- **修法**：按 perf-optimization-plan 的 Phase 2 清单接线配置键并灰度。
- **验收**：见 perf-optimization-plan §验收。

### P2-4 U14 反注入护栏文案（产品裁决）
- **现象**：触发反注入护栏时，回复文案向触发者**明示**「系统提示/密钥/本机文件」存在。
- **位置**：`plugins/bot_unified_runtime/capabilities/chat.py:2150` 一带（护栏 body）。
- **根因**：威慑设计与攻击面提示之争，属产品裁决非文字问题（q1-inventory U14）。
- **影响**：恶意用户可从文案反推防御焦点；普通用户无感。
- **修法（二选一，等用户裁定）**：①保留威慑版；②改极简版「我不能聊这些，换个话题吧」。
- **验收**：改后跑 chat 反注入相关测试 + 人工发一条注入样例看回复。

### P2-5 help Mica 卡两栏排版
- **现象**：help 深度页四要素连排在 Mica 卡上单栏过长。
- **位置**：`docs/rendering-contract.md` 口径下的 help 卡模板/`_split_facets` 消费链（F13 残余）。
- **影响**：纯观感，信息完整。
- **修法**：卡模板两栏 CSS（遵守渲染契约：无 viewport、body 透明、动画在 .card 内）。
- **验收**：契约测试全绿 + 真机卡面人工过目（§6.6）。

### P2-6 f-string 直拼卡 DOM 统一
- **现象**：4 处 f-string 直拼卡未走 Jinja 模板共享壳，改 UI 需多处同改。
- **位置**：规格已成文 `docs/design/fstring-card-dom-spec.md`（Python 侧共享 mica 壳方案），**未实施**。
- **影响**：维护成本；不构成线上缺陷。
- **修法**：按 spec 实施（成文在先原则已满足）。
- **验收**：`test_mica_builders_contract.py` + 相关卡测试全绿。

### P2-7 cron/调度用系统本地时区
- **现象**：每日通讯 21:30、提醒投递等调度按宿主机本地时区算。
- **位置**：调度器族（`__init__._register_digest_push_scheduler` 等，台账 #3/#6 同源）。
- **影响**：异时区机器迁移后安静时间/推送时刻口径偏移。
- **修法**：调度统一改 `zoneinfo` 显式时区（配置键注入）。
- **验收**：改时区环境变量后断言触发时刻不变（新增单测）。

### P2-8 SQLite 限流路径不支持热改 + 调度器装配期 config 快照
- **现象**：`/bot runtime set` 热改限流参数对 SQLite 限流路径不生效；G-DIGEST 等调度器在装配期快照 config，当夜热改不生效。
- **位置**：policy/gate 限流实现 + 各调度器注册点（台账 #3 原文）。
- **影响**：管理员改参数需重启才全量生效（当前重启本来就要做，暂无实际损害）。
- **修法**：统一改造为「运行时读 config 现值」模式——架构级改动，单列排期。
- **验收**：热改后不重启，限流/推送行为随之变化（集成测试）。

### P2-9 触发词三语全量普查残余
- **现象**：简/繁/英触发词已按 T-Spec 收口 52 词/13 topic + tra49 批，但「全量」普查（逐词反查路由正则 vs help 注册）未建立机械门。
- **位置**：`tests/test_trigger_spec.py` 棘轮 + `scripts/extract_trigger_words.py`。
- **影响**：未来新增能力可能再现「路由有、help 搜不到」（求籤 即此类漏登实例）。
- **修法**：给 `_HELP_ALIAS_MAP` ↔ 各能力 `_COMMAND_RE` 建双向机械比对门（能力侧词表为真值源）。
- **验收**：故意删一个别名时门禁红；全量绿。

---

## 已裁定/已定性（无需动作，防重复考古）

| 项 | 裁定/定性 | 证据 |
|---|---|---|
| 10 个死配置键 | **有意设计非误留**（4 个休眠预留模块，docstring 写明），保留不加标注 | R65（final-report-draft.md）|
| route-matrix 覆盖门子串匹配偏弱（M-2） | **已修**：`tests/test_documentation_consistency.py` 改 `\b{kind}\b` 词边界，MARKET 不再撞 STOCK_MARKET | 2026-09-13 实改+测试绿 |
| `zb` 拼音归属 | **设计裁定：永不启用**（bz/zb/sz/sm 四缩写真冲突，divination.py 词表注释钉死）+ 测试锁 `test_conflict_initials_stay_disabled` | 2026-09-13 实改 |
| `求籤` 触发词 | **已另立**：入 `_ICHING_RE`+`_DIVINATION_COMMAND_RE` 双正则 + echo aliases/META 注册 + help 搜索可命中 + 回归锁 | 2026-09-13 实改 |
| qx.json 三次消失 | **根治**：随包入库（.gitignore 例外早已就位，文件本体 2026-09-13 提交后由 git 兜底） | 提交哈希见提交批 ⑥ |
| 根目录 `.mypy_cache` | 历史裸跑 mypy 残留（dev.ps1 本身已正确外置 cache 到 Runtime），已清 | dev.ps1:325 `--cache-dir` |
| `.claude/.codex/.grok` 未跟踪目录 | 本地工具配置，已加入 .gitignore | 2026-09-13 实改 |
| curl-cffi 0.14.0 CVE | **已升** 0.16.3（无反向依赖），CVE 清零 | pip-audit 复审 |

---

## P3（backlog）

| # | 问题 | 位置 | 修法 | 影响面 |
|---|---|---|---|---|
| P3-1 | bot 头像页脚用「守」字圆点 | `.env` BOT_PERSONA_AVATAR_URL 为空 | 用户提供头像图路径后配置 | 纯观感 |
| P3-2 | F6 meme 心情驱动主动发 | capabilities/meme_library.py | 需完整防骚扰门（概率×心情×冷却×NSFW×白名单），有意不做半吊子 | 主动社交体验 |
| P3-3 | F7 随机 cos 照片 | 等用户提供 gs_kuro_cos 插件+油猴脚本 | 借鉴其接口做 xhs/推特 cos 图随机发 | 新功能 |
| P3-4 | Ghost Downloader aria2 RPC 集成 | sources/downloader.py | 用户开 RPC+确认端口/token 后自动委托（装 aria2 即可） | 下载提速（可选） |
| P3-5 | 23:00 性能收尾批 | 见 `docs/perf-optimization-plan.md` | 定时任务自动执行 | Phase 2 解锁+五链路实测 |
| P3-6 | TG 正文嵌套块级元素早停（罕见残余）；social_v2 同函数 channel_title/bio 未改 | sources/parsers/social_v2 | 有实据再修 | 罕见 |

---

## CVE 复审命令（可复跑）

```bash
# 生成生产依赖快照（只读，不动 Runtime venv）：
"C:/…/ChatBot_Runtime/venv/Scripts/python.exe" -m pip freeze --all | grep -v '@ file:\|-e ' > req-freeze.txt
# 临时 venv 审计（不污染生产 venv）：
python -m venv %TEMP%/pa-venv && %TEMP%/pa-venv/Scripts/python.exe -m pip install pip-audit
%TEMP%/pa-venv/Scripts/python.exe -m pip_audit -r req-freeze.txt --progress-spinner off
```
2026-09-13 实跑基线：curl-cffi 已清零；剩 cryptography ×3 + aiosmtplib ×2（均为上游阻塞，见 P2-1/P2-2）。
