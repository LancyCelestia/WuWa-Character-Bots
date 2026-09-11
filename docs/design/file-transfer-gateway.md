# B3 · FileTransferGateway 统一文件出站设计规格

- 状态：**规格稿（未实现）**。本文只写设计规格，不含实现代码；细度以"下一会话可直接照做"为准。
- 规格来源：`docs/HANDBOOK.md:82` B3 行（规格源标注为 09-10-full §10.5；该节在归档件 `handoff-2026-09-10-full.md` 中仅一句"FileTransferGateway 统一（仍有 handler 直连 call_api）"——本规格据此与代码实况展开）；大文件分片沿用 **B1 part 协议**（HANDBOOK.md:80，原规格=归档 08-29 handoff §9.3，本文只引用不重复设计）。
- 姊妹规格：`docs/design/central-decision-engine.md`（B2）。本规格阶段 1 不依赖 B2（全部改动在 sender 层内）；阶段 2 的"删直连点"与 B2 阶段 2 迁移共用同一批 handler 改动，需协调排期（见 §5 R6）。
- 基线：全部 file:line 于 2026-09-12 对当前工作树 grep/实读核实；不确定项标 `unknown`。

---

## 1. 现状盘点（全部经 grep 核实）

### 1.1 文件出站直连点（发送层之外，违反"只有统一发送网关可发送"）

| # | 位置 | 调用 | 说明 |
|---|---|---|---|
| D1 | `__init__.py:3864-3877`（`_handle_admin_file_export`） | `bot.call_api("upload_group_file"/"upload_private_file", ...)` | `/bot 导出` 生成的文档（`export_document`，`capabilities/file_exchange.py:205` 返回本地 Path）直连上传；**不进 SendQueue、无回执落库、无幂等键、无 part 进度**；失败仅文本告警（:3878-3879） |
| D2 | `__init__.py:4012-4023`（`_handle_admin_cookie` login 分支） | `bot.call_api("send_group_msg"/"send_private_msg")` + `file:///` 图片段 | 扫码登录二维码 PNG 直发；绕过队列与回执 |
| D3 | `__init__.py:3360-3364`（`_cookie_expiry_reminder_job`，每日 cron） | `bot.call_api("send_private_msg", ...)` | 凭证到期提醒直发文本（非文件，但同属"绕过网关"清单，B2 收编） |
| D4 | `mail_bridge.py:312-344`（`send_mail_from_account`，被 `mail_bridge.py:450` 与 `runtime/disconnect_notice.py:188` 调用） | `bot.send_mail(message)` / `bot.send_to(...)` | 直连 SMTP；`EmailMessage.set_content` **纯文本，无附件能力** |

### 1.2 发送层内既有文件通道（现行"合法路径"，网关的地基）

| 位置 | 机制 | 约束 |
|---|---|---|
| `sender/onebot.py:341-449`（`_send_file_parts`） | OneBot 文件上传：仅支持**本地绝对路径**（:365-368 `Path.is_file()`→`path.resolve()`），群走 `upload_group_file`、私聊走 `upload_private_file`（:369-374）；优先 `getattr(bot, api)`，退化 `call_api`（:377-385）；文案在全部上传成功后补发（:394-411）；混合媒体部件再发一轮（M17 修复，:412-449） | **有副作用即绝不整体重试**（:349-351 文档声明；:447-449 注释）；非 file/text 部件经 `build_onebot_message_segments`（:227-232 有 CQ file 段构造） |
| `sender/onebot.py:303-316`（`_SendSideEffects`） | 请求级副作用计数 + part 级 `delivered_parts`/`unknown_parts` 索引 | B1 的 A7/A8/A11 批次产物：请求级已做，**part 级续发仍未做**（HANDBOOK.md:80） |
| `sender/nonebot.py:365-380` | Telegram 附件：`bot.send_document`，本地路径读**全量字节进内存**（:376） | **2MB 硬上限**（:372 超限抛 `_FinalSendError`）；caption 随件；缺回执按失败（:378-379） |
| `sender/nonebot.py:318/439-440` | Mail 回复通道（经 UnifiedDeliveryGateway） | 纯文本 reply，无附件 |
| `sender/queue.py:93/122-152`（`_part_key`/`PartRecord`/`PartProgress`） | 队列侧 part 级进度（delivered/unknown/pending 索引）已建模 | SendQueue Protocol（:156）不改 |

### 1.3 文件来源侧现状（决定 FileSource 设计）

- **本地路径**：D1 的导出文档；`capabilities/download.py:103`（`outcome.path` 进 `CapabilityResult.files`）；卡片渲染 PNG（`bot_card_render_dir`）。
- **URL**：入站经 NapCat 代理下载（`__init__.py:3792-3796` `get_file`/`download_file`；`sources/telegram_media.py:133` `get_file`）；出站媒体 URL 目前仅 TG 图片直链可透传（`sender/nonebot.py` photo_ref 路径）。**出站 URL 下载无统一入口**；SSRF 护栏已存在于 `sources/downloader.py:357`（`check_download_url`，`RejectedUrlError` :283），但只服务 `MediaDownloader`（:430）链路。
- **字节**：TG 侧 `read_bytes()`（`sender/nonebot.py:376`）；入站 base64 落盘（`__init__.py:3800-3807`）。**出站无字节直发接口**（必须先落盘）。

### 1.4 配额与缓存现状

- `runtime/cache_policy.py:17`（`enforce_quota`）：按 mtime 最旧优先清理目录至 `max_bytes`/`max_age_days` 内；每次落盘后调用方自行触发。
- `runtime/cache_policy.py:73`（`prune_prefixed`）：按文件名前缀保留最新 N 个——**注意只 glob `*.png`**（:89），对非 PNG 产物无效（限制，见 §4 Q5）。
- 落盘目录：`bot_download_dir`（默认 `data/downloads`）下 `incoming/`（`__init__.py:3785-3787`）与 `export/`（:3854-3856）。
- 现状缺口：**上传动作本身无配额概念**（单文件大小、单次请求总量、目标目录生命周期都无约束）；staging 与已投递文件的清理无 owner。

### 1.5 幂等与回执现状

- `SendRequest.dedupe_key`（`contracts/runtime.py:285`，非空校验 :307-312）已强制存在，但文件上传直连点（D1/D2）**根本不走 SendRequest**。
- 回执：`DeliveryReceipt`（`contracts/runtime.py:323`）+ `ReceiptState`（:92-101，含 `FAILED_RETRYABLE/FAILED_FINAL`）+ `operational_issue`（:233）；文件级回执信息（文件名/大小/平台 file id）现无结构化载体。
- 平台成功判定：`_onebot_result_is_success`（sender/onebot.py 内，upload 失败/超时一律升格 `_NonRetryableActionError`，:386-392——**宁可结果未知也不重发**）。

### 1.6 现状拓扑（文字版）

```text
capability / handler 产出文件
   │
   ├─ 合法路径（进发送层）：
   │   CapabilityResult.files / content_ref parts {"type":"file","file":<本地路径>,"name":...}
   │     → RuntimePipeline 渲染 → SendRequest → SendQueue.submit
   │     → handler 补投递（_deliver_transport_send_request, __init__.py:2053）
   │        或 后台 worker（_register_send_queue_scheduler, __init__.py:1335）
   │     → UnifiedDeliveryGateway（sender/gateway.py:30）
   │          ├─ send_onebot_v11 → _send_file_parts（仅本地路径；upload_group/private_file）
   │          └─ send_nonebot_message（TG: send_document ≤2MB / Mail: 纯文本）
   │
   └─ 直连路径（绕过发送层，B3 要消灭）：
       D1 __init__.py:3864  upload_group/private_file（/bot 导出文档）
       D2 __init__.py:4012  send_*_msg(file:/// QR 图片)
       D3 __init__.py:3360  send_private_msg（cron 提醒文本）
       D4 mail_bridge.py:312 send_mail/send_to（SMTP 直连，纯文本）
```

---

## 2. 目标架构

### 2.1 设计原则

1. **网关长在发送层内**：FileTransferGateway 是 `UnifiedDeliveryGateway` 体系下的文件通道组件（新模块 `sender/file_gateway.py`），不是 capability 侧的新库。这与 B2 十条强制规则第 4 条一致："只有统一发送网关可以向 QQ、Telegram、Mail、Console 发送"——文件只是消息的一种载荷。
2. **业务侧只见 FileSource，不见平台 API**：capability/handler 允许声明的最小词汇是"path/url/bytes + 目标会话"；`upload_group_file` 等字样从此只允许出现在 `sender/` 目录内。
3. **契约不变**：`CapabilityResult`/`SendRequest`/`DeliveryReceipt`/`SendQueue` 字段与语义不动（新增 `files` 内 dict 的**约定键**与新增独立类型 `FileTicket`/`FileTransferReceipt`，属"新增"不属"修改"）。
4. **大文件分片不另行设计**：part 级进度/UNKNOWN 确认/部分成功续发全部引用 B1 part 协议（队列侧 `PartRecord`/`PartProgress` 已备，发送侧续发逻辑待 B1 落地），网关只需保证每个文件 ticket 携带 `part_index` 可参与的稳定 `dedupe_key`。

### 2.2 组件与接口草案

```python
# sender/file_gateway.py（新模块）

class FileSource:                       # 三选一，判别字段 source_kind
    source_kind: Literal["path", "url", "bytes"]
    path: str | None                    # 已在磁盘上的文件（导出/下载产物）
    url: str | None                     # http(s)；必须过 SSRF 护栏
    data: bytes | None                  # 内存字节（上限见 Q2）
    name: str                           # 目标文件名（取 basename，禁路径分隔符，
                                        #   沿用 __init__.py:3781 的防御注释语义）
    sha256: str                         # bytes/path 统一计算，url 落盘后计算
    declare_only: bool = False          # True=允许平台侧自行拉取（TG 直链 photo），不 staging

@dataclass
class FileTicket:
    ticket_id: str                      # ft_<hex12>
    local_path: Path                    # staging 后的绝对路径（declare_only 时为空）
    name: str
    size: int
    sha256: str
    source: str                         # 来源标记：export/download/render/manual_bytes/...
    created_at: datetime

class FileTransferGateway:
    def stage(self, src: FileSource, *, request_id: str) -> FileTicket: ...
        # path: 校验存在+绝对化+进配额账本；url: check_download_url→代理下载进 staging；
        # bytes: 写 staging（to_thread，沿用 __init__.py:3803 的大文件写盘下放原则）
        # stage 完成即对 staging 目录执行一次 enforce_quota（cache_policy.py:17）
    async def deliver(self, bot, ticket, *, target: SendRequest, part_index: int = 0,
                      budget: Any = None) -> FileTransferReceipt: ...
        # 按 target.target_scope 分通道：
        #   OneBot GROUP   → upload_group_file(group_id, file, name)
        #   OneBot PRIVATE → upload_private_file(user_id, file, name)
        #   TELEGRAM       → send_document（>2MB 策略见 Q1）
        #   MAIL           → EmailMessage.add_attachment（新增能力，见 2.4）
        # 失败分类沿用 _NonRetryableActionError 语义（upload_rejected/
        #   upload_failed_or_unknown/missing_file）
```

- **收据**：新增 `FileTransferReceipt`（独立类型，不塞进 DeliveryReceipt）：

```python
class FileTransferReceipt(StrictBaseModel):
    request_id: str; ticket_id: str
    state: ReceiptState                 # 复用既有枚举
    name: str; size: int; sha256: str
    part_index: int = 0                 # 供 B1 part 协议索引
    provider_file_id: str | None = None # 平台侧 file id（OneBot 上传回执若有；unknown 字段形态）
    transport: str                      # onebot.file / telegram.document / mail.attachment
    debug_id: str
```
  落库走既有 `ReceiptRepository` 旁路（新增 file_receipt 表或以 audit_tags 结构化写入 `AuditRecord`——**推荐独立表**，理由：`/bot receipt` 查询需按文件维度聚合；最终取舍归 Q4）。

- **幂等**：文件级 `dedupe_key = f"{sha256}:{target_scope}:{target_id}:{part_index}"`；与 `SendRequest.dedupe_key` 并存（前者防同文件重复上传，后者防请求重放）。重试纪律不变：**一旦存在已成功副作用，本次请求绝不整体重投**（`_send_file_parts` 现行契约，onebot.py:349-351）。

### 2.3 与现有发送路径的接线

```text
send_onebot_v11（sender/onebot.py:571）
   └─ _send_file_parts（:341）改造为薄壳：
        parts 里的 {"type":"file"} → FileSource(path=…) → gateway.stage() → gateway.deliver()
        （每个 part 一次 deliver，沿用 _SendSideEffects 计数与 _TimeoutBudget 切片）
send_nonebot_message（sender/nonebot.py:300）
   └─ files 分支（:365-380）改造为 gateway.deliver(transport="telegram")
      （2MB 检查、caption、_FinalSendError 语义原样保留在网关内）
D1/D2/D3（__init__.py 直连点）
   └─ 改为构造 CapabilityResult.files / SendRequest → SendQueue.submit → 既有补投递
D4（mail_bridge.send_mail_from_account）
   └─ 保留 API 形状（命令面不变），内部改经网关 mail 通道；无事件上下文的调用
      （disconnect_notice）走 B2 的 origin=scheduler 分支或直接使用网关（Q3 裁定）
```

### 2.4 各通道规格要点

| 通道 | 上传 API | 来源支持 | 上限/策略 | 回执 |
|---|---|---|---|---|
| OneBot 群 | `upload_group_file`（经 gateway） | path（url/bytes 经 stage 转 path） | 平台侧限制 `unknown`（NapCat 未提供文档化配额，Q6） | `FileTransferReceipt`；无消息 id，`provider_message_id=None` |
| OneBot 私聊 | `upload_private_file` | 同上 | 同上 | 同上 |
| Telegram | `send_document` | path/bytes（现读全量字节）；url 直链可 declare_only | **2MB**（现行为）；超限策略 Q1 | `provider_message_id` 从 send_document 回执提取（现 :378 逻辑） |
| Mail | `EmailMessage.add_attachment`（新写） | path/bytes | 大小上限 Q1（建议先对齐 TG 2MB 起步）；MIME 由扩展名推断 | SMTP 无回执 id：sent 即终态，失败 `FAILED_RETRYABLE`（沿用 mail_retry_delay，mail_adapter.py:18） |

### 2.5 配额与缓存挂钩（复用既有 LRU 策略）

- staging 目录：`{bot_download_dir}/staging/`（新增，与 incoming/export 平级）。
- 每次写入后执行 `enforce_quota(staging, max_bytes=bot_file_staging_max_bytes, max_age_days=bot_file_staging_max_age_days)`（两个新配置键；默认建议 2GB / 3 天，落 config.py 时进 config-catalog-full）。
- 投递成功后文件**不立即删除**：保留至 TTL 由 LRU 淘汰——供重试/审计复查/B1 续发时复用同一 ticket（否则 unknown 态确认后无法续发）。
- `prune_prefixed` 保持服务卡片 PNG；不扩展其 glob（非 PNG 产物统一归 staging 配额管，避免双套语义）。

### 2.6 安全校验（进网关的固定闸门）

1. URL 来源：强制 `check_download_url`（downloader.py:357，复用既有 SSRF IP 黑名单逻辑），禁止内网/环回/重定向到私网。
2. 文件名：取 basename、剥离路径分隔符与控制字符（现 D1 处理链已有同名防御，`__init__.py:3781`）。
3. 生成文件安全扫描：与 handoff-2026-09-10-full 登记的"生成文件安全扫描"（P2 验收级项）挂钩——网关在 stage 后留 `scan_state` 挂载点（本规格不设计扫描器本身，只留接口位）。

---

## 3. 迁移路径（四阶段）

### 阶段 1：sender 层内收敛（零行为变化）

- 内容：新建 `sender/file_gateway.py`；`_send_file_parts`（onebot.py:341）与 TG files 分支（nonebot.py:365）改为调用网关，逻辑逐行等价搬运； golden 回归测试固化现有行为（上传参数、caption 时序、副作用熔断、2MB 拒绝）。
- 验收标准：
  1. 既有发送单测全绿 + 新增网关单测（三来源 stage/两通道 deliver/失败分类/part_index 传递）；
  2. 真机回归：群传文件+私聊传文件+TG 文档各 1 例（验收法按 acceptance-manual）；
  3. grep 证明 `upload_group_file|upload_private_file|send_document` 仅存在于 `sender/` 内。
- 回滚：单提交粒度 `git revert`（纯内部重构，无配置面）。

### 阶段 2：消灭直连点 D1/D2（handler 侧）

- 内容：`_handle_admin_file_export`（`__init__.py:3864-3885`）改为组装含 file parts 的 `CapabilityResult` → `_send_text_through_unified_pipeline` 同构的统一管线路径（或直接 `SendQueue.submit` + `_deliver_transport_send_request`），删除 `bot.call_api(upload_*)`；cookie QR（:4012-4023）改走队列 image part（`file:///` 段构造收进 `build_onebot_message_segments` 既有路径）。与 B2 阶段 2 同文件操作，须先约定分区（见 R6）。
- 验收标准：
  1. `/bot 导出` 四格式实测：群/私聊各收到文件，`/bot receipt` 可查该请求；
  2. `/bot cookie login` QR 图片真机可见；
  3. 上传失败场景（改名路径模拟 missing_file）回执为 FAILED_FINAL 且无重复投递；
  4. grep：`plugins/` 内 `call_api("upload` 零命中。
- 回滚：直连点回补丁单独成提交（保留旧实现于 revert 粒度内）；能力开关沿用运行时热改。

### 阶段 3：三来源 + Mail 附件 + 配额生效

- 内容：`FileSource` 三来源全量启用（URL 走 SSRF 闸门与下载代理）；Mail 附件通道（D4 收编：`send_mail_from_account` 内部改网关，命令面不变）；staging 配额键与 enforce_quota 接线；`FileTransferReceipt` 落库。
- 验收标准：
  1. url→群文件、bytes→TG 文档、path→mail 附件三链路真机各 1 例；
  2. SSRF 用例：私网 URL 被拒且审计留痕；
  3. staging 超限触发 LRU 清理（构造小 max_bytes 验证）；
  4. 邮件真机：QQ 邮箱收附件可打开。
- 回滚：新配置键默认关闭 URL/bytes/mail-attachment（`bot_file_source_allow` 白名单式开关），关回即回到 path-only。

### 阶段 4：B1 part 协议对接 + 收尾

- 内容：`FileTransferReceipt.part_index` 接入队列 `PartRecord/PartProgress`；UNKNOWN 确认与部分成功续发按 B1 规格（08-29 §9.3，归档）落地——**本文不重复设计，仅要求网关侧提供**：稳定 dedupe_key、ticket 可复用、deliver 可按 part_index 单发。删除 D3/D4 残留直连；CI grep 守门（`call_api\(` 白名单只许 `sender/` 与测试）。
- 验收：B1 验收标准为准；本文附加验收=文件维度 `/bot receipt` 聚合查询可用。
- 回滚：B1 协议特性开关独立，网关基础功能不受影响。

---

## 4. 风险与开放问题

### 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 重构 `_send_file_parts` 触碰"有副作用不重投"高危契约，等价搬运出错→重复发文件 | 阶段 1 golden 测试锁行为；副作用计数只搬不改；真机回归必过 |
| R2 | staging LRU 淘汰了仍在重试窗口内的文件，B1 续发时 missing_file | 配额淘汰按 mtime 且 TTL > 队列重试上限；淘汰前检查队列 pending 引用（阶段 4 一并做） |
| R3 | URL 下载引入新的 SSRF/大文件耗盘面 | 强制复用 check_download_url；下载大小上限与 staging 配额同一账本 |
| R4 | bytes 来源占内存（TG 现行 read_bytes 全量） | 阶段 3 起超过阈值（建议 8MB）的 bytes 拒绝并提示转 path/url（Q2 裁定） |
| R5 | Mail 附件被用于投递恶意生成物 | §2.6 扫描挂载点 + 阶段 3 前不上线 mail 通道（依赖安全扫描项排期） |
| R6 | 与 B2 并行改 `__init__.py` 冲突 | 分区约定：B3 只动 D1/D2 两个 handler 块与 sender/；B2 的 handler 迁移绕开这两块或排序在后 |

### 开放问题（7 个，动工前需裁定）

1. **Q1** TG >2MB 与 Mail 大附件策略：直接拒绝、压缩转码、还是改发"文件下载链接"（bot 自建下载点依赖 B4 公网，未立项）？建议先拒绝+提示。
2. **Q2** bytes 来源的内存上限与是否强制落盘后释放（建议：>1MB 即 stage 落盘，内存只作中转）。
3. **Q3** 无事件上下文的调用方（disconnect_notice、D3 cron）投递文件/直发文本时，是直接用网关还是必须过 B2 引擎（涉及 B2 规则 1"所有事件"的定义域）。
4. **Q4** `FileTransferReceipt` 落库形态：独立 SQLite 表（推荐，可聚合查询）vs 审计 tags；与 `/bot receipt` 查询语法的兼容。
5. **Q5** `prune_prefixed` 仅 glob `*.png` 的限制是否需要泛化为按前缀全扩展名（涉及卡片目录他能力产物安全，B13 相关）。
6. **Q6** NapCat `upload_group_file/upload_private_file` 的频控/单文件上限实测值（`unknown`，需真机探测后写回本表与 config-catalog）。
7. **Q7** OneBot 上传回执是否含平台侧 file id 可供 `provider_file_id` 回填（`unknown`：NapCat 返回形态需实测；影响重复上传去重的第二道防线设计）。
