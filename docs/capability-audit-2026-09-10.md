# capabilities 全面逻辑缺陷审查报告（C组交付）

> 日期：2026-09-10 · 范围：`plugins/bot_unified_runtime/capabilities/**` 逐文件只读审查（3 个并行子代理分片 + 交叉核对支撑模块）
> 定级：P0 崩溃/数据损坏 · P1 功能错误 · P2 边界/资源 · P3 理论风险
> **处置约定**：本报告只记录与给出修法。涉及 B 组文件域（music.py / runtime_admin.py / subscribe_v2.py / llm/channel_health.py）与 A 组文件域的发现，由对应组认领修复；C 组仅修复自身文件域内缺陷。审查时点后代码若有变更，行号可能漂移。

## P1（应优先处理）

| # | 位置 | 问题 | 建议修法 | 归属 |
|---|---|---|---|---|
| 1 | capabilities/runtime_admin.py:758-784（调用点 838/904/916/1044/1085/1095） | `/bot model add/update/priority` 把 .env 注册表**整体烘焙**进运行时持久层（`_persist_priority_move`→`replace_registry_entries` 全量写入含 env 来源条目）。此后 .env 改 key/换 base_url/删条目会被运行时旧副本**永久遮蔽**（`model_router.py:606-612` 动态覆盖 base_specs）；env 条目 api_key 直接落盘明文 JSON。update 回执文案与实际行为不符 | replace 前过滤未改动且来源为 env 的条目，或给条目打 source 标记跳过 | B组 |
| 2 | capabilities/subscribe_v2.py:101-112（+72-77、93-100） | v2 订阅 `pause/resume/remove` **完全无权限校验**（v1 有 `_can_operate`，v2 丢失）：任意私聊用户可停/删任意全局订阅；`list` 向所有人泄露全部订阅；`add` 重加时 `model_copy(update={"enabled": True})` 会把管理员暂停的订阅静默重新启用 | 移植 v1 创建者/目的地归属校验；re-add 不改 enabled | B组 |
| 3 | capabilities/subscribe.py:342-350 | `remove/pause` 作用于整个 spec：群 A 管理员删除会连带删掉群 B 与私聊目的地（`delete_spec` 连带 cursors/push_log）；私聊创建者暂停会停掉群推送——跨目的地数据丢失 | 按.destination 粒度增删/启停 | B组（订阅域） |
| 4 | capabilities/subscribe.py:359-418 | `check` 动作无 `_can_operate` 校验，任意用户可枚举 spec_id 查看他人订阅标题/URL/新增条数 | check 前加与 remove 相同的权限判断 | B组（订阅域） |
| 5 | capabilities/chat.py:901-943 | `_mcp_tools_schema` 首次调用异常（启动竞态/工作线程 `asyncio.run` 跨 loop）即把 `_mcp_tools_schema_cache` **永久置 []**：无 TTL 无重置，`enable_tools` 只看模块可导入，此后每条消息都开启工具却永远拿不到工具，静默失效到重启。`_mcp_probe_cache` 同理 | 失败不缓存或加 TTL；MCP 调用回主 loop（`asyncio.run_coroutine_threadsafe`） | C组意见：chat.py 无主，建议本轮后修，见 §修复建议 |

## P2（边界/资源）

| # | 位置 | 问题 | 建议修法 | 归属 |
|---|---|---|---|---|
| 6 | music.py:562-567 | `query.isdigit()` 对 `"²"`/`"①"` 为 True 而 `int()` 抛 ValueError（未捕获）——发「点歌 ²」即崩 | 改 `isdecimal()` 或 try/except 后按非编号处理 | B组 |
| 7 | music.py:570-634 | 候选详情失败静默 fallthrough：编号被当歌名搜索，`search_fn("3")` 返回含 3 的无关歌 | 详情失败回复错误并 return；数字查询不落普通搜索 | B组 |
| 8 | music.py:570 | 模块级 `_CANDIDATE_SESSIONS` 跨能力重建存活，`candidate_providers[parser_id]` 可能 KeyError | `.get()` 判空降级普通搜索 | B组 |
| 9 | sources/parsers/wbi.py `_WBI_CACHE` | 无上限：过期条目永不删除、无容量上限，cookie 轮换会累积（TTL 只影响取值不影响删除） | 惰性删除过期键+容量上限 | A组（parsers 域） |
| 10 | sources/subscription_store_v2.py | `subscription_outbox` state='sent' 行**永不删除**，随推送量线性增长；`mark_outbox_retry` 无 attempts 上限无限重试；`subscription_seen` 无 TTL 清理 | sent 行按时间裁剪；retry 加上限进死信；seen 加 TTL | B组 |
| 11 | meme.py:91-94、163 | `request_fn` 为 None 时每次调用新建 `httpx.Client` 且从不 close（每条表情命令泄漏一个连接池） | client 单例化或 finally 关闭 | C组意见：无主文件，建议本轮后修 |
| 12 | today_history.py:45-66、115-149 | (a) `_save_push_table` 吞 OSError，写盘失败仍回复"已设置/已取消"；(b) `_load_push_table` 读失败返回 `{}`，之后任何一次设置/取消用只含当前条目的表**整体覆写** JSON → 其他订阅全部丢失 | 写失败要回错；读失败拒绝改写 | C组意见：无主文件，建议本轮后修 |
| 13 | echo.py:962-964、debug.py:788-794 | 帮助卡/接入卡 PNG 文件名 digest 含 request_id，每请求必生成新文件且无配额清理（对比 meme.py:198-205 有回收）→ `data/cards` 无界增长 | digest 只按内容，或复用 meme 的 enforce_quota | C组意见：建议本轮后修 |
| 14 | chat.py:2159-2186 | `_apply_output_message_budget`：`max_messages<=0`（不限段）且单条字符上限>0 时只测第一块 → 直接返回全文，单条上限不生效 | 不限段时按"块数×单条上限"装箱 | C组意见：建议本轮后修 |
| 15 | chat.py:1318-1330 | `_schedule_memory_extraction` 每条成功回复起一个裸 `threading.Thread`，无线程池无并发上限 | 改有界 ThreadPoolExecutor | C组意见：建议本轮后修 |
| 16 | auto_send/parser.py:24-45 | (a) `is_auto_send_command_text` 要求「报存␣」（带空格）而 `_COMMAND_RE` 允许 `报存给`，`报存给A…` 能解析却过不了门控；(b) 正文提取 `内容(.+)$` 取第一个「内容」，主题含「内容」时正文截错 | 统一用正则判断；从主题匹配终点后搜「内容[:：]」 | C组意见：无主文件，建议本轮后修 |
| 17 | content_parser.py:433 | 卡片 `path.write_bytes(png)` 非原子写+固定 digest 文件名，同链接并发解析可能发出半截 PNG | 写临时文件后 `os.replace` | A组（解析域） |
| 18 | runtime_logs.py:58（实现在 sources/runtime_event_log.py:140） | `read_recent` 全文件 read_text().splitlines() 后再过滤，日志大时 `/bot logs` 一次读全量进内存 | 反向限量读取/按块扫描 | C组意见：无主文件，建议本轮后修 |
| 19 | file_exchange.py:81-98 | `return` 在 TemporaryDirectory with 块内：Windows 孙进程锁 workdir 时清理抛 OSError，被外层吞成"运行环境异常"丢真实结果 | 子进程用任务对象/cleanup=False/忽略清理异常 | C组意见：无主文件，建议本轮后修 |
| 20 | runtime_admin.py:321-344 | `/bot model probe` 无重入防护：连发 N 条起 N 个 8 线程探针全渠道真实计费请求 | 加"进行中"标志位 | B组 |
| 21 | runtime_admin.py:667-669 | usage 兜底分支 naive created_at 按进程本地时区解释（跨时区错档）；`list_recent(1000)` 截断致账单少算 | attach bot_timezone；分页聚合 | B组 |

## P3（低概率/理论）

| # | 位置 | 问题 | 建议修法 |
|---|---|---|---|
| 22 | music.py:435-437 | 候选容量淘汰按 dict 插入序而非过期时刻，长驻会话可能先于更早过期者被逐出 | 淘汰按 expires 排序 |
| 23 | music.py:113-121 | 「点歌 link/voice/all」等与模式别名同名的真实歌名永远被当模式设置 | 编号/引号转义或提示 |
| 24 | runtime_admin.py:836-846、1038-1048 | add 时 `actual_model_id` 静默覆盖 model 但回执回显原值误导；vision add 的 effort 未过 normalize_effort 校验 | 回执回显实际值；补校验 |
| 25 | subscribe.py:60-75、244-247 | 以「订阅」开头的普通句子被误吞回 usage；`digest_enabled` 只能置 True 无法退出日报 | rest 非动作词降级不接管；补 digest off |
| 26 | subscribe_v2.py:59-71 | resolve_target 返回 None 时报错文案显示"解析失败：None"；except RuntimeError 顺带吞事件循环错误 | 区分错误类型；显式文案 |
| 27 | content_parser.py:784 | `content.platform_extra` 未判 None（contracts 允许 None；同函数 793 行有守卫此处没有）——潜伏崩溃点 | 补 None 守卫 |
| 28 | platform_credentials.py:134-148 | cookie 读-判-写无锁并发可产生重复行；写死 includeSubdomains=TRUE 忽略原始域属性 | 加锁；保留原属性 |
| 29 | memory.py:97/161 + character/memory.py:237-240 | 每次调用新建 SQLite 连接且不在 offload 名单（事件循环内同步写），并发写可能 database is locked | 连接复用/入 offload |
| 30 | meme_library.py:51、85-109；poke.py:12、24 | cooldown/_last dict 只增不清无上限（会话数大时缓慢泄漏） | 容量上限+淘汰 |
| 31 | eat.py:125-231 | `_RECENT` 全局 dict/set 无锁多线程读写，`pop(next(iter()))` 可抛 dict changed size；`recent.clear()` 破坏"换菜不重复"语义 | OrderedDict+锁；clear 改部分保留 |
| 32 | chat.py:159-163 | `_FAILURE_MESSAGE_CURSOR` 多线程 pop(next(iter())) 竞态低概率 RuntimeError | 加锁或 OrderedDict |
| 33 | epic.py:39 | `_format_games` 直接下标 `game['title']`（其余字段都 .get），源缺 title 即 KeyError | `game.get("title") or ""` |
| 34 | eat.py:29-32 | `_EAT_RE` extra 分支含 `.*`，任何「吃…」开头句子（吃了吗/吃饭没）贪婪误捕 | extra 收紧为约束词白名单 |
| 35 | image_search.py:44-46 | 引用回复场景分支是死代码（`image_url = ""` 赋回空串），静默落通用提示 | 修正赋值或删分支 |
| 36 | file_exchange.py:173-174 | `_safe_file_name` 截断归一化后不同主题可碰撞静默覆盖旧导出（bot 自有目录，低风险） | 加短 hash 后缀 |

## 浸泡观察（2026-09-10 实测）

- **快速回归**（入套件，`tests/test_soak_growth.py`，独立命名）：多线程异常浸泡 1000+ 次操作后好感度库行数==用户数、线程数无增长、发送队列 max_items 裁剪生效、幂等表有界——3/3 通过。
- **4 分钟长跑**（%TEMP% 临时脚本，3 工作线程持续轰击 affinity/SendQueue/幂等表）：线程数稳定（结束完全回收）、affinity 行数恒 200、queue 行数精确封顶 500、幂等表封顶 4096、**零异常**。
- **2 分钟复跑（psutil RSS 采样）**：RSS 105.6→108.5 MB（+2.7%，增速逐段收敛 1.4→0.3→0.2 MB/15s，为预热稳定形态而非线性泄漏）；线程/行数/缓存指标同首跑全部有界。长跑结论：进程内主要状态（候选会话/幂等表/审计环形缓冲/队列行数）均有界；确认的无界点为 #9 wbi 缓存、#10 订阅 outbox/seen 表、#13 data/cards、#30-31 cooldown/_RECENT——均为慢速增长，短程浸泡不可见，已列 P2/P3 待修。

## 已检查无问题的方面（抽样）

群号均为 str 比较无类型错位；下载/卡片文件名经 yt-dlp id/sha1 生成、`_safe_file_name` 阻断路径穿越；moegirl 归一化循环可终止、本地 KB 缓存有锁；debug.py 全套 `_safe_*` 对 None/负值/非有限数兜底；today_history 时间校验完整（0-23/0-59）；候选会话 TTL 用 `time.monotonic` 无墙钟回拨问题；priority 排序稠密唯一槽位、`_price_rank` 无除零；health store 读写有锁、探针线程生命周期随池回收；各命令正则无灾难性回溯；sqlite/JSON 写入带锁或事务。

## C 组处置说明

C 组文件域（affinity.py/providers 注入段）内的缺陷（§3 画像被 observe 清空）已在数值化交付中修复并带回归测试。上表其余发现按归属列给 A/B 组与本轮后续修复，未越域改动。
