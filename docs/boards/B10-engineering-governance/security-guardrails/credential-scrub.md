# 安全与凭据护栏 · 跨域凭证剥离

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.security-guardrails · 跨域凭证剥离

- 层级：一级 B10 → 二级 security-guardrails → 三级 `credential-scrub`
- 实现落点：`plugins/bot_unified_runtime/domains/core/credentials`、`plugins/bot_unified_runtime/security`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/database_broker.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

保证「A 平台的 cookie 绝不发到 B 域」。审计定性是统一咽喉缺失：子串匹配没有锚定（`evilbilibili.com` 能骗过后缀判断），而 urllib 的跨 host 重定向**不剥** Cookie——浏览器语义会剥，urllib 默认只剥 content-length/content-type，于是「B 站登录态跟着 30x 跳到攻击者域」是结构性跳道。修法收在唯一咽喉：`domains/link_parse/parsers/http_util.py` 的初始请求构造 + 默认重定向 handler，绝不在各解析器各写一遍。

## 怎么调用

- `scrub_credentials_for_target(cookie, url)`：咽喉核心，返回允许带出的 Cookie 头明文；不归属则返回空串。
- `credentials_allowed_for_target(cookie, url)`：只做判定（供需要「能不能带」而非「给我 Cookie 串」的调用方）。
- `_apply_cookie_guard(headers, url, cookie)`：把（可能带归属的）cookie 经咽喉过滤后写头，被剥就不写。
- `_CredentialScrubbingRedirectHandler`：经 `_build_opener` 默认装上（它是 `HTTPRedirectHandler` 子类，`build_opener` 以 isinstance 顶替默认，不产生双 handler）。比较「初始请求 host」与「落点 host」，不同即 `_strip_credential_headers` 就地删 `cookie` / `authorization` / `proxy-authorization`；同 host 站内跳转不剥（误剥会毁掉正常登录态续跳）。
- 域名真身：`domains/link_parse/parsers/cookies.py:PLATFORM_COOKIE_DOMAINS`。规则是**扩写这张表，不另建第二张域表**。`PlatformCookie`（provider 产出）携带本平台窄域 → 按窄域校验；普通 `str` cookie（steam/epic 自读兜底）→ 回退到由该表派生的联合域。
- 归属判定 `_host_matches_domain`：后缀语义，`www.bilibili.com` 归入 `.bilibili.com`、裸域自配、`evilbilibili.com` 不误伤。取不到 host 时保守判「不允许」。
- 归因链：规则的 `allowed_hosts`（字段在 `domains/core/contracts/media.py`）由 `domains/link_parse/capabilities/content_parser.py:_host_belongs` 消费，决定从页面里派生哪个 URL——有规则域时只选归属域内 URL，无规则域（合成/无凭证规则）保持旧行为。
- 凭据引用面：`domains/core/credentials/credentials.py` 只发 `CredentialRef`，解析发生在 transport/fetch 边界，任何 repr 与审计输出只见掩码预览；文件态落被 git 忽略的凭据库（路径以该件的路径常量为准），`BOT_CREDENTIAL_` 前缀的环境变量值不出现在错误文本里。体检走 `dev.ps1 -Task credential-smoke`（查过期与可用性，绝不打印密钥值）。

## 开关与参数

无「关闭凭证校验」的键。校验失败的行为是**降级而非报错**：剥掉 Cookie 继续以未登录态抓取，绝不抛异常、绝不拒解析——对用户的可见差异只是部分内容拿不到，而不是整条链接解析失败。

热更性：cookie 域表随代码走（改表即改行为，不做运行期热改）；平台窄域由 provider 产出的 `PlatformCookie` 携带，新增平台只扩 `PLATFORM_COOKIE_DOMAINS` 一处。

## 失败时看到什么

没有「凭证被剥」的用户可见文案（这是设计：静默降级为未登录）。可观测面有三处：解析结果本身缺字段/被判为需登录（表现为「拿不到正文」类降级）、审计日志里的未登录态标签、以及 `credential-smoke` 的到期与可用性提示。

排障方向别搞反：出现「带凭证却拿不到内容」时，先怀疑窄域配置过窄或联合域未扩，而不是怀疑剥离逻辑多余——把它改宽的正确做法是改 `PLATFORM_COOKIE_DOMAINS`，不是在调用点绕过 `scrub_credentials_for_target`（绕过即触发机器门，见下）。

## 测试与验收

`tests/test_credential_domain_binding_gate.py` 是再生门：AST + 文本双扫，禁止在 `domains/link_parse` / `domains/music` / `domains/media` 里出现「带 Cookie/凭证的出站请求而不经统一咽喉」；合规判据是走 `http_get` / `http_get_text` / `http_get_json` / `http_post_json` / `http_post_form` 任一咽喉函数，或显式调用两个咽喉助手；名单外形态即红，配显式豁免表与负样本注毒。`tests/test_credential_domain_binding.py` 管域匹配语义（窄域、联合域、跨 host 重定向剥离的逐形态断言），`tests/test_platform_credentials.py` 管 provider 侧产出。

复跑：`PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_credential_domain_binding.py tests/test_credential_domain_binding_gate.py -q -p no:cacheprovider --basetemp=$TEMP/cs`。真机侧无专属条目，属重启后随链接解析打点一并观察。
