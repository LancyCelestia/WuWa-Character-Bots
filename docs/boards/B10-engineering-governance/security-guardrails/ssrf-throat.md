# 安全与凭据护栏 · 下载入口与落点双查

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.security-guardrails · 下载入口与落点双查

- 层级：一级 B10 → 二级 security-guardrails → 三级 `ssrf-throat`
- 实现落点：`plugins/bot_unified_runtime/domains/core/credentials`、`plugins/bot_unified_runtime/domains/chat_reply/security/__init__.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/dangerous_command.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/injection.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/display_guard.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/spoof_audit.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/database_broker.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

挡「让 bot 替用户去访问内网」。用户贴一条链接、回一句「下载这个」、订阅一个站点，URL 就是攻击面；把 `http://127.0.0.1:8090/…` 或云元数据地址伪装成普通链接，是这类 bot 最典型的越权读法。

真身分两层：底层判定 `domains/files/sources/downloader.py:check_download_url`（协议白名单 + 主机黑名单 + 字面量 IP 判定 + **全部** DNS 解析结果内网判定），上层收口 `domains/link_parse/parsers/ssrf_guard.py` 的两个函数——入口 `guard_user_url`（分发解析前）与落点 `check_fetch_landing`（拿到重定向后的 `geturl()`、回显内容之前）。**入口 + 落点双查**是范式，笔记图片、媒体归档、文件网关各自的下载口都照它办。

## 怎么调用

- 解析链入口：`guard_user_url(url)` 返回拒绝原因字符串或 `None`（`None` = 判定为公网，或护栏自身崩溃的 fail-open）。调用方把非 `None` 直接接进既有「解析失败」降级分支，不新增分支。
- 落点复查：`check_fetch_landing(final_url, original_url)`，命中即抛 `ParseHttpError`，消息带「SSRF guard」可判别标记。
- 下载/探测口：`domains/files/sources/downloader.py:_url_rejection_reason` 是咽喉在本文件内的唯一调用点，`download()` 与 `probe()` 共享同一闸门（曾经的缺口正是 `probe()` 没挂）。
- 逐跳：短链解析走 `domains/link_parse/parsers/http_util.py:_GuardedShortLinkRedirectHandler`（继承凭证剥离 handler），每一跳落点先过 `check_fetch_landing`，跳数上限从 urllib 默认十收紧到显式五。
- 装载期：配置键 `bot_tts_api_url` 在 `config.py` 装载时就要求 host 能被无歧义证明是本机 loopback（字面量 IP 落 `127.0.0.0/8`、`::1`，白名单 fail-closed），把「语音引擎必须本机」写成宪条而不是运行期补救。
- 紧急信息采集源额外加一道常量白名单（`domains/emergency_info/sources/http_get.py`：先常量白名单、再过 SSRF 闸，两道任一不过即 `FAILED`）。

## 开关与参数

没有「关掉护栏」的配置键，这是刻意的。可影响的只有 `bot_tts_api_url` 这类目标地址本身，而它反过来受装载期 loopback 白名单约束。

判据语义（审查 F-04 定稿，改动必须走评审）：**解析失败 = 拒绝，绝不放行**。DNS 解析失败、无主机名、畸形 URL、非法端口一律拒；整型 IP 形态（十进制、`0x` 十六进制、前导零八进制的 `inet_aton` 语义）先归一化成品点分十进制再走私网段判定，因为旧版正是让这些形态滑进「DNS 失败→放行」缺口。唯一允许的 fail-open 是护栏自身抛出非拒绝类异常，且必须 WARNING 留痕。

多结果域名的处理要点：对 `getaddrinfo` 的**所有**返回地址做判定，任一落内网即拒——只看第一条会被多 A 记录轮询绕过。

## 失败时看到什么

用户侧：一句「该地址指向本机，已拒绝」/「该地址属于内网/保留网段，已拒绝」/「只支持 http/https 链接」/「域名无法解析」，走该能力既有的解析失败降级，绝不回显任何内网响应内容。运维侧：`media url rejected by SSRF guard: <原因>` 的 WARNING（拒绝原因文案固定、不含地址，避免签名 URL 与 cookie 进日志），以及 `parse SSRF guard rejected (parse-entry|fetch-landing): reason=…` 的 INFO。

误伤排查顺序：先确认是不是纯代理可达的平台被字面判定拒了（这类只能显式加例外，不能放宽判定），再看是不是护栏崩溃走了 fail-open（有 WARNING 才算正常，没有就是异常被吞）。

## 测试与验收

`tests/test_parser_ssrf_guard.py`（判定表与整型 IP 形态）、`tests/test_ssrf_throat_coverage.py`（AST 计数：咽喉调用点数量 + 负样本注毒，专防「新加一个下载口忘了挂闸」）、`tests/test_tts_contract_layer.py` 与配置侧装载期测试（loopback 白名单 fail-closed，红态是构造期报错而非静默降级）。

新增任何「拿外部 URL 去请求」的代码，验收判据是：能指出它经过上面哪一个入口，并有对应负样本用例证明门会抓。只写「调用了 `check_download_url`」不算——存在性锁糊过活性判据是本仓付过学费的教训。
