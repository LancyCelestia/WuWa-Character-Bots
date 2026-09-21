# 控制面 API 与工作区 · 鉴权与角色边界

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.control-plane-api · 鉴权与角色边界

- 层级：一级 B09 → 二级 control-plane-api → 三级 `auth-and-rbac`
- 实现落点：`plugins/bot_unified_runtime/control_plane`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定"谁能在控制面上做什么"。现役只有两枚令牌、三种角色档位，但每一件都真的在执法：
读接口要凭据、写接口要**另一枚**凭据、两枚都没配则整个 API 面直接不可用。

设计取向是"默认拒绝 + 失败要便宜"：SHA-256 摘要比对（明文只在生成时出现过一次，
落配置的是摘要）、`hmac.compare_digest` 恒定时间比较、同源 60 秒内 5 次失败即 429。
Host 头校验在**认证之前**执行——Bearer 只能挡住"没凭据的人"，挡不住恶意网页驱动
受害者浏览器朝 `127.0.0.1:8742` 发的跨域简单请求（DNS rebinding / 同源策略绕过），
所以 Host 白名单是一票否决门（审查 P-01）。

## 怎么调用

三枚依赖工厂都在 `control_plane/_app.py`，由 `create_control_plane_app` 注入各路由器：

- `_auth_dependency`：旧 `/admin/api/v1/*` 面（health/status），角色固定 `admin`；
- `_v1_read_dependency`：`/api/v1/*` 读接口，只读令牌与超管令牌**都**放行（超管令牌
  命中时主体改写为 `bearer-super-admin`、角色 `("super_admin","admin")`），
  两枚共享同一个失败限速器；
- `_super_admin_dependency`：`/api/v1/*` 写接口（config set / feature enable / action
  execute / workspace send），**只**认 `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256`。

凭据校验本体是 `control_plane/auth.py:BearerAuthenticator.authenticate`，
按 `Authenticator` Protocol 设计（可插拔，未来接密码/TOTP/OIDC 不动调用方）。
来源掩码 `auth.py:mask_source` 现阶段是主机粒度（IPv4 /32、IPv6 /128），
因为服务只绑环回；收窄掩码只需改这一处。

请求上下文：`_request_context_middleware` **忽略客户端传来的任何 id**，自造
`request.state.cp_request_id` 并写入 `contextvar`，防日志注入与请求冒充。
落痕：`_audit_middleware` 对 `/admin/api/v1/*` 与 `/api/v1/*` 逐请求写
`control_plane_audit`（`control_plane/audit.py`，与 B5 账本同库不同表），
字段含 subject/method/path/query(脱敏)/status/bytes_out/debug_id/error code；
`/healthz` 不审计。审计写失败只打日志，绝不影响响应。

## 开关与参数

- `bot_control_plane_enabled`（缺省 `false`，热更性：**需重启**）：总开关。
- `bot_control_plane_host`（`127.0.0.1`）/ `bot_control_plane_port`（`8742`）：
  非环回需要 Runtime 数据目录下的确认文件存在且非空，否则拒绝启动；
  `localhost` 归一为 `127.0.0.1` 避免 DNS 歧义。
- `bot_control_plane_token_sha256`：只读令牌摘要。空 = 读接口 503。
- `bot_control_plane_super_admin_token_sha256`：超管令牌摘要。空 = 写接口 503。
- `bot_control_plane_host_allowlist`：额外 Host 条目（`host` 或 `host:port`，
  省端口时继承控制面端口）；内置的 `127.0.0.1`/`localhost` + 端口**始终叠加、不可关**。

四枚键都是 pydantic 字段 → `os.environ` → 默认 的 getattr 防御式解析
（`control_plane/__init__.py:control_plane_settings`），字段缺失即视为关。
**摘要本身按凭证类登记**，控制面 DTO 出口只回 fingerprint 不回明文。
令牌生成与轮换是运维动作：明文不落仓库、不进聊天、不进日志。

## 失败时看到什么

| 现象 | 状态/码 | 说明 |
|---|---|---|
| 没配任何令牌 | 503 `control_plane_not_provisioned` | 防"忘了配就裸奔"，只有 `/healthz` 活着 |
| 缺/错 Bearer 头（读口） | 401 `unauthorized` | 记一次同源失败 |
| 写口凭据不对 | 403 `forbidden`「此操作需要 super_admin 权限。」 | 用只读令牌打写接口就是这条 |
| 60 秒内失败满 5 次 | 429 `rate_limited` + `Retry-After` | 三枚依赖共用同一限速桶 |
| Host 头不在白名单/多值 | 400 `host_not_allowed` | 原文只进服务端日志（`repr` 防控制字符注入），不回显 |
| Service 层判角色不够 | 403 `forbidden` | 例：工作区非超管、动作非超管 |

被 Host 门拒掉的请求仍会留下一条 400 审计痕（中间件注册顺序使审计层在 Host 门之外），
这是刻意的取证设计。

## 测试与验收

`tests/test_control_plane_m1.py`（401/403/503 三态与恒定时间比较路径）、
`test_control_plane_host_guard.py`（白名单、多 Host 头、扩展条目、不回显原文）、
`test_control_plane_lifecycle.py`（非环回拒绝、端口冲突拒绝）、
`test_control_plane_v1.py`（读写依赖分离）、`test_control_plane_workspaces.py`
（越权 403）、`test_control_plane_actions_api.py`（缺确认/非超管 403）、
`test_secret_redaction_hardening.py`（query 脱敏）。
真机（须用户先开总开关并配两枚摘要、提权重启）：
① 无 Authorization 打 `/api/v1/features` → 401；② 用只读令牌打
`POST /api/v1/config/.../set` → 403；③ 连错 6 次 → 429 带 `Retry-After`；
④ `curl -H "Host: evil.example"` → 400；⑤ 查 `control_plane_audit` 表确认
每一次都留痕且 query 中敏感值已打码。
