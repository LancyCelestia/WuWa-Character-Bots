# 统一收尾全面审计 · 总汇总（U1–U24 波次）

> **性质**：合并者汇编，非新增审计。把 21 份分单元报告压成一份可执行台账；每条结论都带**席位编号 + 文件坐标**，冲突处并列标注，不替任何一席圆场。
> **对象**：`plugins/bot_unified_runtime/` 后端全树，2026-09-20 口径快照（v21r5，全部未 commit / 未重启 / 未部署）。
> **波次中断说明**：本波 24 个只读子代理并行开工，于**本地钟 2026-09-19 16:55:42** 被服务端按 sessionId 封禁（`406 provider_error / Session blocked`，不可重试）而腰斩。后果：U8/U24 取消、U11a/U14 未落盘、U20/U21/U22/U23 只剩空骨架。**这不是代码缺陷，是取证通道断了**，但直接造成本汇总有约 1/3 覆盖面为空。
> **时间口径**：多份报告文件名写 `20260920`，而席内实读 `date` 为 `2026-09-19 16:0x–16:5x`（U1/U23 明确自陈此错位）。本汇总按**文件名口径**引用席位，按**席内实读**标注时刻。
> **`✅` 的含义**：合并者本人在当前树上重新核对过该条坐标与结论，不是转述。未打 `✅` 的是各席自报，采信前请按需下钻原报告。
>
> **修订记录 2026-09-19（汇编者二次核查）**：本汇总的覆盖面**仅限后端波 `22bb78f8`**。归档时发现同一 mandate 被用户按域拆成了**三个并行会话**——后端（`22bb78f8`）、TTS 专项（`3b50fe67`，31 份报告 / 1.2 MB）、补跑+修复波（`b0a268b2`，已覆写 U20/U23、新建 U24、完成 F1 修复）。故本文 §0 表中「U20/U23 空骨架」「U24 取消」「TTS 无人审」三处**已被后续波次推翻**，§7.1 已就地标注修订。三波全景与归属见 **`HANDOFF-SESSIONS-unify-audit-20260919.md`**。

---

## §0 覆盖度与可信度（先读这张表）

| 席位 | 主题 | 报告行数 | P0 | P1 | 可信度 |
|---|---|---:|---:|---:|---|
| U1-invest | 入站摄取归一 | 673 | 0 | 6 | 采信（含分派矩阵骨架） |
| U2-proto | 协议契约 | 261 | **1** | 5 | 采信 |
| U3-outbound | 出站发送 | 453 | 0 | 3 | 采信 |
| U4-dispatch | 中央分发门禁 | 240 | 0 | 3(High) | 采信，**但条目数不自洽**（见 §7.2） |
| U5-arch | 架构/垫片/分层 | 1529 | **2** | 6 | 采信（附扫描器全文，可复算） |
| U6-config | 配置变量 | 402 | 0 | 13 | 采信 |
| U7-command | 命令参数 | 293 | 0 | 2 | 采信 |
| U9-function | 函数重复实现 | 310 | 0 | 4 | 采信 |
| U10-gate | 四门禁真值复跑 | 212 | **5(宣称不成立)** | 5 | 采信（唯一跑全量门禁的席） |
| U11b-sec | 后端安全咽喉 | 337 | 0 | 9 | 采信；**本席未跑任何 pytest** |
| U12-llm | 模型链路与计价 | 329 | 0 | 6 | 采信 |
| U13-db | 数据层与持久化 | 242 | 0 | 7 | 采信 |
| U15-output | 输出管线 | 222 | 0 | 2(Critical) | 采信 |
| U16-green | 机器门真伪（假绿） | 215 | **1** | 8 | 采信（负样本未注入树上，等价性有折扣） |
| U17-campus-wire | campus 收编 | 108 | 0 | 0 | **施工日志前半段**：§0 取证扎实，§1 起全空 |
| U18-persona | 人格与上下文注入 | 227 | 0 | 5 | 部分采信：**D3/D4 两大重点节未做**，发现总表未回填 |
| U19-correct | 逐能力业务正确性 | 215 | 0 | 0 | 部分采信：**C3–C6 四节未开始**，仅金融/天气两域有结论 |
| U20-cp | 控制面 | 66 | 0 | 0 | **不可采信**：纯骨架，六节全「待填」，零实跑 |
| U21-conc | 并发与资源生命周期 | 80 | 0 | 0 | **不可采信**：未开工；仅引用他席，且引用了同样未开工的 U22 |
| U22-sandbox | 测试沙箱与树卫生 | 43 | 0 | 0 | **不可采信**：未开工，**且开工基线快照三条全未勾**（事后无法自证未污染） |
| U23-adapter | 多适配器对等 | 79 | 0 | 0 | 无原创发现；**§0.1 引用表可当他席结论索引使用** |
| — U8 | TTS 语音链路 | 未落盘 | — | — | 取消（席位在飞面） |
| — U11a | 后端安全（前席） | 未落盘 | — | — | 仅 U11b 落盘，**U11a 的覆盖面未知** |
| — U14 | （任务书未留档） | 未落盘 | — | — | 无产物 |
| — U24 | 中央……（截断） | 未落盘 | — | — | 取消 |

**净结论**：18 席有实质内容，4 席空骨架，3 席无产物。**并发面（U21）、测试污染面（U22）本次等于没审**；控制面（U20）与适配器面（U23）已由后续补跑波覆写，中央决策引擎落差（U24）已新建报告——见 `HANDOFF-SESSIONS-unify-audit-20260919.md` §3.3。

---

## §1 总裁决（6 条）

1. **「一切经中央统一处理后再分发」的 mandate 未达成**。不是没有中央入口，而是**入口存在、生产主链旁边另有并列入口**。至少六个独立面同时命中：出站（U3）、分发（U4）、命令（U7）、文本加工（U15）、人格装配（U18）、脱敏（U11b）。
2. **「已统一」的门只验登记、不验可达与真身 ⇒ 恒真门与结构性假绿**。U16 实测：默认测试入口自动 `--write` 洗绿三条基线；坐标锁断言对象是冻结快照字符串而非源码；AST 扫描对包级 from-import 系统性失明。
3. **最恶性的「双真身互抄漂移」实测为 0**（U5：同名对 164、双非垫片 0、sha 复制 0）。问题不在内容分叉，在**垫片通路没剪干净**（反向 import 413 边 / 117 文件）+ **一处真双账本**（divination 双 DrawStore）。
4. **安全面无 P0，但 P1 密集且同源**：SSRF 咽喉挂在调用点而非取数层（U11b 6 条 + U9 + U1 共 8 处出口）、出站打码无咽喉（32 条路由仅 1 支遮）、**被封禁管理员在四条旁路 matcher 上仍全权**（鉴权绕过）。
5. **一条功能已经死了，且测试全绿**：群摘要读键 `group:<gid>` 与摄取写键 `group_<gid>_<uid>` 永不相交 ⇒ 群上下文恒空 + 21:30 推送恒静默空转。三席独立复现（U1-05 / U18-D2-2 / U23 §0.1 转引）。
6. **流程债重于代码债**：宣称与实跑不符（U10 判 12 条不成立）、提交漂移 837→876 文件、`.tmp-test/` 489MB 未 ignore 导致 ruff 结果不可复现、`%TEMP%` 字面量目录在树内。

---

## §2 P0 台账（5 条，全部 ✅ 或双席同坐标）

> 七要素：严重度｜坐标｜锚点｜根因｜改法｜验证｜回归锁。改法照抄原席，合并者不改判。

---

#### P0-1 `sources.web_search` 僵尸 import = 运行期 ImportError 地雷 ✅

- **坐标**：`plugins/bot_unified_runtime/runtime/capability_protocols.py:1273-1275`
- **锚点**：`from plugins.bot_unified_runtime.sources import (` ＋ 注释 `# RET2B-PREP: web_search 垫片挂起（control_plane/api 消费），维持旧路径`
- **合并者复核**：`ls plugins/bot_unified_runtime/sources/` **确无 `web_search.py`**；注释宣称「垫片挂起」与事实相反。
- **同坐标三席**：U2-P0-1（唯一 P0）、U5-F-02（判为 09-19 P0-2 **同坐标复发**）、U10-C-5（判「RET2b 已退役、AST 零残余」宣称不实）。**U1 §9 判「已消解」——应撤回**（U10 明确点名）。
- **根因**：包级 `from X import (name,)` 是 AST 扫描盲区（U16 实测纯集合成员式命中 0，而 `find_spec` 返回 None）；垫片退役时只改了 `:1128` 与字符串引用，漏了函数体内的 deferred import。
- **改法**：一行改指 `domains.core.search`，并删失真注释（U5 方案）。**配 U16 §2.4 的四轨常驻化门**（成员式 ∪ 别名拼接式 ∪ mypy  逐模块 find_spec），否则同类第 6 次复发。
- **验证**：`mypy` 单文件归零（当前它是**全树唯一 typecheck 红错**）；`importlib` 探针不再 ImportError；`test_v21_s10_protocols.py`。
- **回归锁**：descriptor 完整性门已是锁，勿拆；缺的是「注释宣称 ↔ 文件实存」一致性门。

---

#### P0-2 `qx.json` 从未入库，第四次毁档风险窗全开 ✅

- **坐标**：`plugins/bot_unified_runtime/domains/weather/assets/qx.json`（362,774 B）＋ `.gitignore:33`
- **锚点**：`.gitignore:33` = `!plugins/bot_unified_runtime/sources/data/qx.json`（**指向已删除的旧路径**）
- **合并者复核**：`git ls-files --error-unmatch` → `did not match any file(s) known to git`；`git status --porcelain` → `?? `（未跟踪）。**负规则确实仍钉旧路径。**
- **同坐标两席**：U5-F-01、U10-C-7（判「随包入库 + 否定规则已同步新径」宣称不成立）。
- **根因**：迁移只做了文件系统层，新址从未 `git add`；`git clean -fdx` 一次即可毁掉，且这是**第四次**（09-19 台账 P0-3 已在案）。
- **改法**：逐文件显式 `git add`（**属用户 git 动作，合并者与审计者均不代做**）；`.gitignore` 负规则改指 `assets/`；旧 D 态随 commit 波登记。
- **验证**：`git ls-files --error-unmatch <新路径>` 返回 0；`git check-ignore -v` 不再命中旧规则。
- **连带**：U19-F-U19-07 证明**此文件一旦缺失即整链静默塌向 Open-Meteo**（零外呼 NMC、预警段消失、无任何标注）。即 P0-2 与「静默降级不可见」是同一条风险的两端。

---

#### P0-3 默认测试入口自动洗绿三条基线 ✅

- **坐标**：`scripts/dev.ps1:246`、`tests/conftest.py:46-50 / :192`
- **锚点**：`if (-not (Test-Path env:BOT_AUTOSYNC)) { $env:BOT_AUTOSYNC = "1" }`、`_AUTOSYNC_STEPS: tuple[...]`
- **合并者复核**：`dev.ps1:242` 自带注释承认「BOT_AUTOSYNC=0 会被这里改回 1，conftest 失败时自动 --write 重录预期」；显式设 0 才透传。**AGENTS 四条标准命令均不带 `BOT_AUTOSYNC=0`** ⇒ 常规路径恒为「失败即重录」，门禁结构上不可能红。
- **被洗的三条基线**：`command-catalog.md` / `auto-facts.md` / `render_hashes.json`。`dev.ps1 -Task verify` 继承同 env；`cross_validate.py` 不清 env ⇒ **双引擎共谋洗绿**。
- **同题**：U10-C-3 另证 `tests/render_hashes.json` mtime 15:39:17 = **窗口内被 `--write` 重录**，「0 DRIFT」是把基线移动后得到的。
- **改法**（二选一，属裁决点 §4-1）：默认改 `0`；或 autosync 改「只 `--check`，见漂移整场 `exit 1`」＋ AGENTS 命令加前缀。
- **验证**：U16 的端到端复演——故意改坏一个 topic 数，`dev.ps1 -Task test` 必须红。
- **回归锁**：U16 G16（autosync 元层门）已存在但不足以自禁。

---

#### P0-4 「四门禁全绿 / 后端波零回归」宣称与实跑不符

- **坐标**：`AGENTS.md` #41、`HANDOFF-V21R5-20260920.md` §〇/§六、`docs/design/v21r4-b-RET2b-R-log.md:34`
- **锚点**：`入站声明了未登记能力`（U10 用它定位归属错判）
- **根因**：门禁快照只对采样时刻负责，并发写树下无人重跑；失败归因被推给「前端/TTS 在飞面」。
- **U10 实跑快照（本波唯一全量口径）**：
  - 全量 `collected 8584` → **`2 failed, 8567 passed, 12 skipped, 3 xfailed in 417.57s`**（宣称 8532P/0F）
  - lint `Found 63 errors / 36 fixable`（归因：`.tmp-test` 43 ＋ `%TEMP%` 2 ＋ 真文件 18 全 I001）
  - typecheck **`Found 1 error in 1 file (checked 618)`** ← 即 P0-1
  - `verify_hashes --check` EXIT=0（但被 P0-3 机制洗出，不可采信）
  - `pre_restart` `PASS 6 / SKIP 1 / FAIL 2`，`REAL_EXIT=1`；kb_drift `ANN=35341 vs chunks=4611`
  - `git status --porcelain` **867@T0 → 874 → 876**（426 M / 329 ?? / 112 D），HEAD `56d1461`(09-15)
- **改法**：以实跑回写宣称；重做 2 条失败的归因；哈希基线在**零并写窗口**重录 + `--check` 复验并记时点。
- **回归锁**：无代码锁，靠 §6 收口纪律。

---

#### P0-5 出站/脱敏无咽喉，用户可见内容零加工裸发

> U16 把这条记为 P1（§3.1），U15 记为 Critical（U15-01），U11b 记为 P1（D3-F1）。**合并者按后果升级为 P0 记账**：它同时满足「隐私内容可进群」「LLM 派生文本裸出站」「无任何门会红」。

- **坐标**：`domains/render/renderer.py:186/198`、`transport/sender/queue.py`（全文零调用）、`chat.py:2335-2357` vs `pipeline.py:731-835`、`__init__.py:2915/3027/3188/3335`、`domains/assistant/campus/campus.py:150`
- **锚点**：`text = naturalize_chat_text(text)`、`reply_text = normalize_paragraph_breaks(reply_text)`、`digest_push:111:`
- **根因**：脱敏与文本四件套**装在能力层靠自律**，只对 `bot.chat` 生效；中央对非 chat 通路零加工。U11b 实测 **32 条路由仅 `bot.chat` 一支遮**，13 处直建 `SendRequest`；U15 实测 **16 条通路中 11 条完全绕过 `plain_text` 咽喉**，含群摘要直进「群」。
- **改法**：`redact_outbound_text` / `process_outbound_text` 合挂 `submit`/`deliver` 与 render 入口单点；调度器改合成 `CapabilityResult` 走同一入口。
- **验证**：U16 给的负样本法——注入盘符路径 / `（好感度 85）`，出站必须被拦且门必须红。
- **连带缺陷**：U15-14 实测现有 `_LOCAL_PATH_RE` 字符类**不排除汉字与左括号**，会把「（好感度 85）」整段吞掉 ⇒ 补咽喉前得先修吞。

---

## §3 P1 主题归并（12 个主题，按「病根」而非席位组织）

### T1 中央入口旁有并列入口（六面同构，本波最深的一条）

| 面 | 证据 | 席位 |
|---|---|---|
| 出站 | 4 类互不相同出口（管线 / 副作用执行器 / 通道本体直调 / 完全旁路），37 处 `.finish()` | U3 |
| 分发 | 调度器族 / 校园 / cookie / 告警主动出站**整体旁路中央门禁**，各自实现小门语义互不统一；`send_queue.submit(request)` 无一调 `pipeline.handle*` | U4-H2 |
| 命令 | 第二套分发并存：6 个 `priority<50` 阻断 matcher 不走路由表，`/bot` 内再 33 路 `elif` 各自解析参数 | U7-F5 |
| 入站 | campus 读事件→拼文本→落库→直投队列**四段全复刻**，绕 gate/审计/幂等；12 个生产调用点仅 1 个走 `IngressGateway` | U1-09、U23 §0.1 |
| 文本加工 | 非 chat 主链与**全部调度器主动投递零文本加工**，含 LLM 派生文本裸出站 | U15-01 |
| 人格装配 | **六条通路绕过中央装配器自拼提示词**（戳一戳 / 早报划重点 / 群摘要 / 日程草稿 / 课表 / 文档导出），其中三条产出「守岸人语气」用户可见文本；旁路同时缺红线/反注入/人格三道门 | U18-D1-1 |

**收口动作**：`ProactiveDispatcher.precheck`（U4，`today_history` 作参考实现）+ `build_default_character_provider_kwargs` 单一工厂（U18）+ 路由表扩 `ADMIN_SUB` 声明与单一中央解析器（U7）。

### T2 SSRF 咽喉挂在调用点，不在取数层（8 处出口）

U11b 逐条：`downloader.py:595` `def probe(self, url)`（同文件 `download()` 有校验，`probe` 无）；`image_stitch.py:129` **拼图链零咽喉且把平台 Cookie 交给可 302 的 `http_get`**；`http_util.py:169/224/255/287/389` **全系跟随重定向不复查**（`_build_opener(proxy)` 无中央 opener，公网 302→内网即穿透）；`vision_describe.py:252-260` 取图 helper 无咽喉，**取回字节转 data URL 送 VLM 再进对话**（U11b 自评「全树最接近内网响应回显的通道」）；`meme_library_listener.py:80-93` `"follow_redirects": True` 且异常静默 `return None`；`credential_health.py:111/129/132` **凭据探测口带真实平台 Cookie 访问配置 URL 且跟随重定向**。
另有 U9-F-U9-01（`web_search.py:109/141/237`、`chat.py:3216`、`meme.py:103`）与 U1-U15（meme 图库）。
**改法**：`check_download_url` 下沉到 helper/取数层 + 逐跳 handler 复查；Cookie 仅同源主机下发。
**U11b 自评口径**：「外部可控输入直达未校验 sink」本席裁定为**否**（全部判 P1，无一 P0），因 URL 由第三方响应或 302 决定——**此裁定属席位判断，合并者不改判但标注为可争议**。

### T3 鉴权与角色门

- ✅ **`/bot why` 无任何角色门**，与帮助页 `admin_only=True` 矛盾：`__init__.py:6525`（U7-F4）＋ `diagnostics.py:673-700`，`store.find(token)` 按 request_id/debug_id **全库无会话过滤**，群内免 @ 即可跨会话读诊断。U7 的 AST 角色门扫描表列了 27 个 builder，**唯一 N 项即 `build_why_result`**。
- **被封禁的管理员在四条旁路 matcher 上仍然全权**（灌 Cookie / 改任意人昵称 / 导文件 / 读群文件清单），且绕开 policy/gate 黑白名单、限流与审计：`__init__.py:4938-4943`，锚点 `return user_id in {str(item).strip() for item in config.bot_admin_user_ids}`（U11b-D2-F1）。
- 同一份旁路谓词另有三处拷贝：`subscribe.py:169-172`、`subscribe_v2.py:62-67`（+ `echo.py:53`、`debug.py:1671`、`runtime_logs.py:18`），**不含 `bot_telegram_admin_user_ids`、不含超管自动叠加**（唯一 resolver 在 `policy/roles.py:25`）→ U18-D2-3。
- `ADMIN` 判定双实现口径不同：`base_router.py:194-196` 认裸形态 `bot X`，NoneBot `command_start={"/"}` 不匹配且无 ADMIN 兜底 matcher，而群门禁按 classify 免 @ 放行 ⇒ **静默黑洞**（U7-F2）。

### T4 假绿与自证型基线（U16 主场）

| 条目 | 严重度 | 证据 |
|---|---|---|
| 坐标锁走过场：`outbound_registry` matchers 命中 **0/50**、`add_job` **1/20**、`llm.py` registry=9 vs 真实 13；陈旧态下常驻门当场 `8 passed` | P1 | `MATCHERS total=50 hit=0 miss=50` |
| AST 扫描假 0：纯集合成员式对 `web_search` 命中 0 而 `find_spec=None`；对包级 from-import / PEP562 字符串 / 非常量动态导入（实存 3 处）/ 别名 re-export **四形态失明** | P1 | `parsed files: 618` |
| 自证基线：`render_hashes.json` 由被哈希文件自身生成；`doc_sync` 用正则推 `topics=77`，AGENTS 顶部把 77 当权威 ⇒ **闭环自证** | P1 | `return {name: sha256_of(path) for name in TRACKED_FILES}` |
| 「垫片→真身」三件套无常驻门；`assert "runtime/reactions.py" not in coordinates` 只查登记表字符串不查 import | P1×3 | U10 函数体内僵尸 import 与全量绿共存 |
| 反注入两洞长期挂 strict xfail：引用链标记单独出现不转义、`[TRUSTED_SYSTEM 层级3]` 后缀绕过 | P2 | `test_prompt_injection.py:97/111` |
| **skip 侧才是主患**：实弹/像素面全 opt-in（`BOT_ERRCARD_SMOKE` / `BOT_RENDER_NET_TESTS` / Chromium 启动失败→skip / finance 上游不可达→skip），红被吞成 skip；人格源-副本一致性门在无 Runtime 环境**自动解除武装** | P2×2 | 缺「该测没测成」与「故意不测」的区分 |
| S0 门开用例 spy 掉整条管线 ⇒ **门开②③④必被吞、拨门即整功能静默失效，126 项测试全绿** | P1 | U3-02 |
| `direct_sends` 23 处坐标已失效，但棘轮只断言 `location` 子串 ⇒ 实测 `126 passed` | P1 | U3-01 |

### T5 双真身与死账本

- **divination 双 `DrawStore`**（唯一真·域内双真身）：`data/draw_store.py`(637 行, `class@:386`) vs `store/draw_store.py`(419 行, `class@:212`)，同 docstring「V2.1 S12 抽签」；`capabilities/divination.py:40` 走 data、`api/facet.py:51` 与 `control_plane/api/divination.py:47` 走 store ⇒ **聊天链不注入 store → 塔罗永不落库，API 面另一份读写**（U5-F-06 / U2-P1-4 / U13）。U13 另加一刀：`bot_control_plane_divination_db` **全树未定义** → draws 生产永不建表。**归宿属用户裁决（§4-3）。**
- **计费双写**：`usage_service` 12 类双写、测试守僵尸实现（U2-P1-6）；≈3400 行 V2.1 usage/billing 栈退役还是接线待裁（U12）。
- **S10 总册 22 条生产零消费者**，三套能力注册表（`family.name` / `bot.*` / `bot.plugin.*`）互不映射 = 死册（U2-P1-2）。

### T6 配置面：不是单一 schema，实测七套值来源（U6，P1 13 条）

七套来源：`Config` / 下游影子缺省 / **873 处 `getattr` 三参兜底（其中 168 处兜底值 ≠ 字段缺省，涉 71 键）** / `os.environ` 直读 / driver `BOT_MUSIC_MODE` / `.env` 6 个幻影键 / 硬编码绝对路径。
关键条：
- `BOT_POTCCV_API_KEY` **无字段槽位**（18 个 `api_key_*` 独缺它），`model_router.py:482` 非 dotenv 路径恒取空 ⇒ registry 恒判 `config_missing`（U6-§2.2a，H3 同族第四次）。
- 凭据/用户档案键**未进 `path_fields`**：`credentials.py:218` `FileCredentialStore(file_path)` 裸串 ⇒ 按项目惯例填 `data/...` 即**写源码树**（U6-§2.3，台账 #1 第 4 次复发的根因）。
- R3 防刷屏键**登记了但生产读不到**：`rate_limit.py:39` 与 `config.py:927` 同旋钮两个 schema 源，行为正确纯因两值巧合（U6-§4.1）。
- 层级倒挂：`bot_schedule_enabled` 零消费而分门能开；ACG 三门「只改显示不改行为」；v21 分门两真两假。
- 校验覆盖 **65/616**；`.env.example` 缺 **110** 键；`RESTART_REQUIRED_KEYS` 理由串 10 组指向已不存在的旧路径；43 个密钥形键 **0 validator**。

### T7 垫片与分层（U5，含 1432 边全量分类表）

- **`domains` 反向 import 旧顶层 413 边 / 117 文件**（F-03，P1）：域真身绕自家旧门牌号回自己，锚点 `chat_reply/capabilities/affinity.py:19`。改线批次只覆盖旧目录/cp/tests 视角，**域真身内部引用从未入批**。
- `control_plane↔domains` 双向 22+11 边 ＋ 私有名穿仓（F-04）：`control_plane/llm_admin.py:379` 经垫片**连踩 4 个下划线名**。
- 跨域直入实现 55 边绕契约层（F-05），锚点 `finance/capabilities/stocks.py:119 → link_parse.parsers.http_util`。
- **枢纽未拆**（F-08）：根 `__init__.py` **8676 行**，`_register_nonebot_handlers@:3544` 独占 **5125 行 = 全包 59%**；顶层 import 102、51 个 matcher、15 个 `add_job` ⇒ **任意 import 本包即执行全部注册**。
- 垫片账面：158 张（PEP562 83 + star/thin 75），死 14 / 仅测 33 / 生产 111；台账「275→93 退役→4 挂起」与实况有漂移。
- **正面**：垫片 canonical 指向 **158/158 全可解析、零断链**；跨目录内容级双写 **0**。

### T8 无中央供给层（横切三条）

- **时钟**：29 个 `now` 助手 + **41 处 naive `datetime.now`** + timesync 仅 1 消费者；日界本地/UTC 分裂（`__init__.py:2855/3010/3177/3328` vs `trend.py:230`）→ U9-F-U9-05。业务后果已在 U19 兑现：卡面时间戳三张标法（F-U19-03）。
- **SQLite**：**75 处裸 `connect`、28 套建表、WAL 25 份而 `busy_timeout` 仅 10 份、`PRAGMA user_version` 0 处** → U9-F-U9-06 / U13。正统 `database_broker` **生产零消费**。
- **重试/超时**：`bot_download_timeout_seconds` 同键三套兜底（600/300/120/60）；≥11 处自实现冷却（U4）。

### T9 数据层与测试污染（U13）

- ✅ **无「测试写生产 Runtime」防线**：`tests/conftest.py:214` 的 G1 只快照**源码树** `data/`，不覆盖 `ChatBot_Runtime/data`；锚点 `_REPO_DATA = REPO_ROOT/"data"`；且 Teaching/broker 门缺省 True。**WIRE-SVC 已实际误写一次**。改法：session autouse `setenv` 指 tmp ＋ G1 改读解析后 `runtime_data_dir()`。
- **persona 知识库 ANN/FTS 与真相源漂移 7.6 倍**：chunks **4,611** vs FAISS ntotal **35,341** vs FTS 35,341；`vector_knowledge.py:471-473` 锚点 `fts_auto_rebuild=False` ⇒ 陈旧向量稀释召回且大库不自愈。
- **体积**：向量库 5.28GB+1.04GB / 905MB+154MB，BLOB 与 FAISS 双存、无 DB 级配额；`du -sh data` = **13GB**。
- events **三库并存无单一 owner**。

### T10 出站协议与幂等（U3）

- `feature_gate` 未登记即 fail-closed：`feature_gate.py:57-59` `return FeatureAccess(False, "feature_unregistered")` ⇒ **21 处文案今日静默不发**（U3-01，缺 `bot.file` 等 4 个 id）。
- ✅ **同一处两个方向的缺陷**：`via_queue=True` 时欢迎反被 `passive_group_message` DENY 误杀（U4-M-1）——与 U3-01 同穴。
- **part 级 UNKNOWN 确认协议生产零接线**：`__init__.py:1649-1656` 锚点 `unknown_part_confirmer: UnknownPartConfirmer | None = None,` 只在测试传 ⇒ `mark_part_unknown` 不写 `provider_message_id`，两条回退路皆不可达（U3-03，U23 转引）。
- **脱敏不在咽喉**：`redact_local_secrets` 盘符路径与 URL userinfo 在 review→render 全放行；四处主动推送直构 `RenderedOutput` 零脱敏。

### T11 超限与文本契约（U15）

- **超限文本三种命运按通路随机**（合并转发 / 静默硬切 / 整条撞平台上限），transport 无最后防线，**QQ 单条上限代码内零登记**；锚点 `_TEXT_FALLBACK_MAX_CHARS = 4000`；实测 5000 字走群摘要通路无切分（U15-05）。
- `ReviewAction.MOVE_PRIVATE` **全树唯一出现处、无消费者** ⇒「隐私内容转私聊」契约名不副实，等同 BLOCK + 机器文案（U15-10）。
- review 面 `result.body or result.summary or result.title` 三取一 ⇒ **text_parts 逃逸**（U15-02）。
- persona-drift / 公开不安全审查**硬编码只认 `bot.chat`**（U15-03）。

### T12 明文密钥与 LLM 直连（U12）

- **源码树内明文真实 axonhub key**：`scripts/configure_axonhub_registry.py:34` 锚点 `AXONHUB_KEY_VALUE = "ah-`，`:119` 写入 `.env` ⇒ 一次性装配脚本把值烘进仓库，**违反铁律 3**。改法：改读环境/交互、**key 按已泄露轮换**、提交前 `git grep --cached` 拦。
- 群摘要 LLM 压缩 = **绕过路由的单模型直连**，异常全吞、零日志、零账 ⇒ 直接构成**账单系统性低估**：`shared_group.py:299` 锚点 `reply = self.llm_provider.generate(`（U12-F-05，#33⑵ 修复只传了 raw provider 未走中央 router）。
- 另：meme 打标裸 `httpx`（F-01）、vision 全家第二套 failover 引擎（F-03）、**计价双写公式不一致**（`pricing.py:186` 不减 cache_write vs `ledger.py:237` 多减，F-06）、`BOT_LLM_BILLING_ENABLED` **死开关**（`.env` 永开不了，F-12）、`_llm_usage_audit_tags(` **仅 1 个调用点**。
- **正面**：全树零 OpenAI SDK 旁路（`AsyncOpenAI|from openai` = **0**）、`model_family_key` 单源、上下文钳制在 ModelRouter 单点强。

---

## §4 需用户裁决清单（合并 14 席「本席不代裁」，接手 AI 不得自裁）

| # | 裁决点 | 提出席 |
|---|---|---|
| 1 | `BOT_AUTOSYNC` 默认改 `0`，还是 autosync 改「只 `--check`、见漂移整场 exit 1」 | U16 |
| 2 | `.tmp-test/`（**489MB**）与树内字面 `%TEMP%/` 目录的清树授权 | U10/U16/U22 |
| 3 | divination 双 `DrawStore` 归宿（`store/` vs `data/`）；塔罗是否要落库 | U5/U2/U13 |
| 4 | `qx.json` 是否 `git add`（**属用户 git 动作**） | U5/U10 |
| 5 | 哈希基线一次性 `--write` 重录的**零并写窗口时机** | U10 |
| 6 | 未登记 / 控制面读失败时，是否 fail-closed 吞掉**用户可见出站**（U3 建议改启动期报错） | U3 |
| 7 | S10 总册升格为唯一总册，还是降级为「V2.1 预留协议壳」并改矩阵 | U2 |
| 8 | Mail 收编进统一协议 vs 显式豁免；ServerChan/PushPlus 是否入 `TransportPlatform` 枚举 | U2/U23 |
| 9 | ≈3400 行 V2.1 usage/billing 栈：退役还是接线 | U12 |
| 10 | 配置键改名波（`_whitelist/_blacklist` ↔ `_allowlist/_denylist`、`_max_retry`→`_max_attempts`、`BOT_MUSIC_MODE` 收编）；`bot_group_welcome_enabled` 缺省 `True` 是否降 `False`；`.env`/`.env.prod` 双文件制度是否保留 | U6 |
| 11 | 日界统一为本地日（**行为变化**）；`database_broker` 收编还是退役 | U9 |
| 12 | 人格装配收口力度：候选 A（全量主链装配）vs 候选 B（addressing+injection 精简两件套）。**U18 附带一刀：既往以 `/bot logs`/smoke 为证据判定的「人格面属实」重启验收结论，是否算可信（该席判「不可信」）** | U18 |
| 13 | U19 语义裁定三项：卡面是否须标注时区/来源语义、是否接受镇级静默代答、`falsy 判把 0.0 洗成「暂无」`是否认可「登记不修」 | U19 |
| 14 | DNS-rebind TOCTOU 与 yt-dlp 侧连接钩子是否堵；控制面 divination 5 个 POST（含 LLM 解读）挂在 read 权限是否收紧 | U11b |
| 15 | v21r4 方案 A（14 域）/ B（20 域）；R-4 五项终裁；`bot.py:481` mail_adapter 设计钉转正还是保留旧名 | U5/U7 |
| 16 | skip 基线钉 12 还是显式 strict marker 矩阵；两枚反注入 xfail 修复还是显式风险接受 | U16 |
| 17 | **树单写者**：多席反复记录「窗口内 11 个文件被并行改写」「快照仅对 15:52:4x 的树负责」。是否冻结其他会话写入、由单一 AI 独占收口 | U10/U3/U4/U6/U7 |

---

## §5 正面结论（已核验通过，接手者勿重复怀疑）

1. **最恶性形态不存在**：跨目录内容级双写 = 0；同名对 164 中双非垫片 0、sha 复制 0（U5）。
2. **垫片指向健康**：158/158 canonical 全可解析、零断链；「假承诺垫片」全树仅 P0-1 一例（U2/U5）。
3. **路由单一大脑成立**：无第二套路由；门禁确在 `_prepare` 一处且 A-18 序实证绿；InMemory/SQLite R3 生效集合等价；`decision` 缺省 `legacy_only` 属实、shadow 绝不发送/改回执/claim（U4）。
4. **安全面咽喉本体无缺陷**：24 私网段 + 全 DNS 结果判定 + IPv4-mapped 归一；角色缺省 `["user"]` fail-closed；`/bot` 31 条子命令逐条过门；**主动出站七通路零收件人注入**（U11b）。
5. **命令词表门是全仓最强统一门**：`command_catalog --check` 77 topics EXIT=0，双向棘轮 106+113=219 条全台账受控、零暗雷；「有路由无实现 0」「有实现无帮助 0」；reply/身份/昵称三页帮助与实现逐字符对齐（U7）。
6. **配置登记面干净**：catalog 零漏登记（`KNOWN_MISSING=∅`）、`path_fields` 55 项零拼错零幻影、`config.py` ruff 0 错、`.env` 未入库且可 commit 面零真实密钥、`config_store` 对重启键显式 raise（U6）。
7. **金融两域实算无编数**：离线复算 **51 checks / 0 FAIL**（KDJ 手算比对、北向量纲、停牌 `f2="-"`→None 非 0）；空响应重试 12/12 出口全覆盖；**非上市红线三层结构性成立**（契约无价格字段 + 外呼前早退 + 能力层 `NON_PUBLIC` 先于一切 fetch，「估值被当市值」无可达通路）（U19）。
8. **真拦的门**（U16 逐道验牙）：G6 能力登记门、G12 性能门（阈值有实测牙齿）、G13 数据卫生门、G16 autosync 元层门、S0 等价性四处收编。xfail 纪律（strict + 双向棘轮 + 转正先例）**好于均值**。
9. **出站幂等**：part 幂等键单源；队列 `RLock` + `ON CONFLICT DO NOTHING` + A-22 认领台账无竞态；`dedupe_key UNIQUE` 单点收敛（U3/U9）。
10. **装配咽喉各单一实现**：`providers.py:350`、`chat.py:1462`，缺陷全来自旁路而非重复实现；四类状态（好感/心情/怪癖/会话身份/称谓）读取 owner 唯一性逐条同源实证（U18）。
11. **依赖比登记更干净**：HTTP 单栈 httpx、图像单栈、`pip check` 无冲突（U5）。
12. **campus 收编方向正确**：垫片归属判定清楚（无第二真身、无双写）、逐门语义实测定表、声明未新造机制（U17 §0）。

---

## §6 建议执行顺序（合并者按依赖关系排，非任何单席原案）

**阶段 0 · 前置（不写代码）**
1. 裁决 §4-17 树单写者 —— **不解冻则后续所有快照都只对采样时刻负责**。
2. 裁决 §4-4 `git add qx.json` + §4-2 `.tmp-test/` 清树 —— 不先做这两条，**任何 ruff/test 数字都不可复现**。
3. 轮换 axonhub key（§3-T12），它随树即可入库。

**阶段 1 · P0 五条**（半天）
`P0-1`（一行 import + 删注释）→ `P0-5`（打码/文本咽喉）→ `P0-3`+`P0-4`（先修洗绿机制，**否则修完也无从证真**）→ `P0-2`（用户 git 动作）。
> P0-3 必须**先于**任何「我用测试证明了修好了」的宣称，顺序错了后面全是假绿。

**阶段 2 · 死功能止血**（一行级，收益最高）
`U1-05` 群摘要读写键：先读侧 `LIKE 'group_<gid>_%'` 一行止血（U18-D2-2 已给 SQL 实据：`LIKE 'group:%' → 0`，`LIKE 'group_%' → 2447`），根治（群级键 + 存量迁移）留裁决。
`U3-01` 四个 capability id 补登记 —— 今天就在静默不发。

**阶段 3 · 安全 P1 批量**（T2 + T3 同源，一次收口）
SSRF 咽喉下沉到取数层 + 逐跳 handler → 顺带清 8 处出口；`resolve_roles` 单点替换 4 处旁路谓词 → 顺带修 D2-F1 鉴权绕过与 `/bot why`。

**阶段 4 · 门补牙**（T4，U16 清单）
坐标锁改「符号名 + 锚点串 + 真行比对」；AST 四轨常驻化；`doc_sync` 正则改 AST 双口径对拍；skip 基线门。**这一批做完，前面所有「已统一」才第一次变成可证伪的命题。**

**阶段 5 · 结构债**（周级，须持写权排队）
T1 六面旁路收编（`ProactiveDispatcher.precheck` / `process_outbound_text` / `build_default_character_provider_kwargs`）→ T5 双 DrawStore → T7 413 边改线 → T8 `dbkit`/`clock`/`fetchkit` 三件中央层 → F-08 根文件三段下沉（8676→<1500，棘轮）。

**阶段 6 · 补审缺口**（§7 五面，本次等于没审）

---

## §7 缺口与不可采信清单（**接手者必读：以下不是「没问题」，是「没看」**）

### 7.1 无产物 / 取消
- **U8 TTS 语音链路**：本波取消。⚠️ 多席把 render/TTS 列为「在飞禁改面」并**把失败归因给它**（U10-C-2 已判该归因不成立）。
  **修订**：TTS 面并非无人审——同一 mandate 被用户按域拆给了并行会话 `3b50fe67`，其 TTS 专项已产出 **31 份报告 / 1.2 MB**（`.superpowers/sdd/2026-09-19-unify-audit/`，去重总账 = `report-T29.md`）。本汇总只覆盖后端面，TTS 结论不在其中。
- **U11a 后端安全（前席）**：未落盘。仅 U11b 存在，**U11a 的覆盖面完全未知** ⇒ 「后端安全已审」这句话目前只能对 U11b 的范围成立。
- **U14**：无产物，任务书亦未留档。
- **U24 中央……**：取消。

### 7.2 空骨架（结论不可采信）
- **U20 控制面**：六节正文全「（待填）」，零实跑。⚠️ 它自列的待答问题恰好是最危险的三面：**「模拟是否触达真出站」(D2-2)、危险动作全表判定 (D2-3)、免鉴权路由清单 (D3-1)**。
- **U21 并发**：18 行交付物全「待办」。**本席最重要交付物 = 事件循环线程上的同步阻塞 IO，未写**；承诺穷尽的 U4 offload 白名单未交付；文末「自查与披露」节**不存在**。
- **U22 测试沙箱**：未开工，**且开工基线快照三条全未勾** ⇒ 事后无法自证未污染。它点名要定位的 `.tmp-test/` 489MB 产生方仍未查明。
- **U23 适配器**：原创发现 0；唯一原创贡献（把 U3 让渡的 `bind_handler` 零生产调用做成正式发现）**D2-3 未写，接手未落地**。其 §0.1 引用表可当他席结论索引，**但采信的仍是 U1/U3/U6/U12/U13 各自报告**。
- **U4 条目不自洽**：§0 记 High 3 / Medium 6 / Low 5，正文独立编号只有 H-1/H-2、M-1…M-5、L-1/L-2 ⇒ **H-3 与第 6 个 Medium、L-3~L-5 未逐条成文**。引用时以 §0 还是条目为准，需先定。
- **U10 小结自相矛盾**：卷首「无法判定 1」，小结「无法判定 0」。
- **U18 D3/D4 未做**：而 D3「红线与内容边界后端执行统一」是该席自标的**重点**；附录 B 发现总表未回填。
- **U19 C3–C6 未开始**：时间语义、订阅/摘要/快报、点歌/链接解析/媒体归档、好感度 v5 与心情 **四节全「（未开始）」**；「无源编数风险点汇总表」为空 ⇒ **本波红线（无源出数/洗 0/伪装成功）只扫了 2/6 个域**。

### 7.3 各席共同的取证折扣
- **无人在树上注入过负样本**（U16 明写「树上负样本注入 0 次」，被他席并发在飞所阻，全改离线复算/天然陈旧态）⇒ §3-T4 的假绿结论**等价性有折扣**。
- **全部席位只跑 scoped pytest，无一人跑全量**（126 / 59 / 6 / 926 / 142 / 51 / 32 passed 等），U11b/U13/U23 **未跑任何 pytest**。
- **全部席位未读 `.env` 明文**（守铁律）⇒ 凡涉生产现值的判定一律标「证据缺失」而非「通过」（U6 明写此口径）。
- **U10 有三道门未跑**：前端宪法门 / `tsc -b` / graph-layout（权限拦截）⇒ exit 码「无法判定」；「重启能起 / 插件冒烟 3.39s」未复跑 = **证据不足**。
- **所有快照仅对采样时刻的树负责**：多席记录窗口内文件被并行改写（U10：11 个文件；U5：根缓存 mtime 09-19 12:3x）。

---

## §8 证据口径与树卫生事故

**统一纪律**（18 席一致，可作为本仓审计基线）：固定 venv 解释器 `ChatBot_Runtime/venv/Scripts/python.exe`（3.12.10）；前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；`--basetemp="$TEMP/<唯一名>" -p no:cacheprovider`；脚本产物一律写 TEMP（源码树外）；**零 git 写**；不读 `.env`；不碰 `ChatBot_Runtime/`、`personas/`；禁真实 LLM 调用与对外发送；「离线 passed 不得写成生产生效」。

**`PYTHONDONTWRITEBYTECODE=1` 本机有效性——两席互斥结论，合并者裁定为「有效，但只在解释器命令行级」**：
- U16 实测：带该参数 → `.pyc` 0、`__pycache__` 0，**明确判与机器记忆册「拦不住」记录相反**，并把 U10 的 366 个 `.pyc` 归因为「裸跑未带 export」。
- U10 自陈：本席造成 93 `__pycache__` / 366 `.pyc`，tar 备份 5,488,640 B / 459 条目后清零。
- U1 自陈：未挡住 366 `.pyc` / 93 目录，备份 5,427,200 B 后清零。
- U23 采纳 U1 教训，改为一律加解释器 **`-B`** 标志。
⇒ **处置建议：环境前缀不可靠，改用 `-B`（U23 已验证基线 `find → 0/0`）。**

**存量污染（非本波所为，按纪律未删，需收尾波统一处置）**：根目录 `.mypy_cache` / `.pytest_cache` / `.ruff_cache`（mtime 12:30–12:47，三席同报）、`.tmp-test/` 489MB、树内字面 `%TEMP%/` 目录（含 U15 误落的探针副本 `%TEMP%\u15_probe1.py`，三次清理被拦后停手）、各席遗留探针（`%TEMP%/u3_probe_*.py`、`u2_enum.py`、`u2_g1.py`、`C:\tmp\u9-fn-audit\`、`%TEMP%/u19_recheck_*.py`、U5 的 `scan_u5.py` **在 %TEMP% 会被清理，需从 U5 附录 A 重建**）。

**可复算资产**：U5 附录 A 含完整只读扫描器源码（纯 stdlib，8 分节，产物表①1432 边 / 表②垫片 158）；U9 指纹扫描器 14,456 函数；U18 AST 探针 604 文件 / 24 调用点。**这三件是本波最值得复用的部分——改线批次跑完后可以直接重算对照。**

---

## §9 分报告索引（下钻用）

全部在 `docs/design/`，前缀 `audit-20260920-unify-`：

`U1-invest`(673) `U2-proto`(261) `U3-outbound`(453) `U4-dispatch`(240) `U5-arch`(1529) `U6-config`(402) `U7-command`(293) `U9-function`(310) `U10-gate`(212) `U11b-sec`(337) `U12-llm`(329) `U13-db`(242) `U15-output`(222) `U16-green`(215) `U17-campus-wire`(108) `U18-persona`(227) `U19-correct`(215) `U20-cp`(66) `U21-conc`(80) `U22-sandbox`(43) `U23-adapter`(79) —— 合计 6,536 行。

**配套阅读**：上一波台账 `audit-20260919-unify-wave.md`（469 行，其 P0-1/P0-2 在本波分别以 U10-F2 / P0-1 **同坐标复发**，是「修了但没锁」的实证）；交接件 `HANDOFF-V21R5-20260920.md`（其 §〇/§六 宣称被 U10-C-1/C-2 判不成立）；TTS 面 `tts-audit-20260919.md`。

---

*汇总完。本文件只做合并与排序，**不新增任何未经席位举证的结论**；§2 五条 P0 中四条已由合并者亲验坐标（标 ✅）。两份文档与代码不一致时，以代码实测为准并回写本文件。*
