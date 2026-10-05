# 内容安全与亲密模式 · 四名单与群级门

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 四名单与群级门

- 层级：一级 B03 → 二级 content-safety → 三级 `roster-gates`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/intimate_control.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

「哪些会话有资格进亲密面」的名单门：一张四名单矩阵决定 `explicit_allowed_for_session` 的真值，是档位机制的**外门**——门没过，`intimate` 档无从谈起。它是纯会话面配置判定，不调模型、不看内容。产出是一个布尔放行，供 chat 主链、被动好感感知与路由侧共用同一份判定（单一事实源，禁各判一套）。生效条件：QQ 私聊与白名单群按矩阵走，控制台是运营者本地面直接放行，其余会话类型（TG 频道、邮件等公开面）不放行。

## 怎么调用

真身在 `plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`。

- `explicit_allowed_for_session(session_type, group_id, config, sender_id="")`：四名单判定本体。群聊 = 命中白名单且不在黑名单（黑名单优先，白名单为空则整群关闭，绝不猜群）；私聊 = 黑名单永远赢、白名单为空即默认放开、非空则仅名单内。`sender_id` 缺省（被动好感感知的旧调用面）不启用私聊名单门，行为与旧版逐字节一致。
- 它与档位内门在 `resolve_intimate_context` 里合成为「外门 ∧ 用户级状态」，注入缝与路由侧读的是同一个它——见 [亲密档位与双开关](intimate-mode.md)。
- `match_master_love_admin(sender_id, group_id, entries)`：Master Love 名单匹配，条目既支持裸 QQ（全域）也支持「群号:QQ」域条目。
- 与订阅面区分：本门管「能不能进亲密档」，不是「哪个群收哪类推送」，后者在紧急信息域的订阅表，两件事不互相替代。

## 开关与参数

键前缀 `bot_content_route_`（四枚名单）与 `bot_master_love_`（自动钉名单），逐键语义与缺省以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准：

- 群级两键：`bot_content_route_group_whitelist` 与 `bot_content_route_group_blacklist`——黑名单优先，白名单空即群聊亲密面整体关闭。
- 私聊两键：`bot_content_route_private_whitelist` 与 `bot_content_route_private_blacklist`——白名单空是**放开的刻意不对称**（私聊默认允许，非空才收窄），黑名单永远赢，连 Master Love 也压不过。
- `bot_content_route_group_per_user_enabled`（缺省为真）：开则群内个人钉与滞回落成员派生键、做到 (群, 用户) 隔离；关则回退为群级整群生效。
- 谁能改：名单全在管理员/超管侧配置；会话内没人能用一句话把自己加进白名单。

## 失败时看到什么

- 判定 fail-open 到不放行：读不到配置、会话类型不认识、名单解析异常，一律按「不进亲密面」收口，安全侧绝不猜。
- 白名单为空时（尤其群聊）是**预期的零放行**，不是故障——要放开就在配置里显式点名，代码绝不替管理员猜群。
- 平台边界：非 QQ 的公开面会话类型直接判不放行，避免同一个号在不同平台被误当同一身份。
- 本门只拦「进不进亲密档」，硬线（能不能说）另在 [六条硬线与不可架空](hard-lines.md)，两者不互相顶替。

## 测试与验收

`tests/test_content_route_v3.py`（四名单矩阵、黑名单优先、白名单空在私聊与群聊上的不对称、Master Love 压不过显式关闭钉）、`tests/test_content_route.py`（外门与档位内门的合成）。
真机：`docs/acceptance-manual.md` §6.6.8；以测试件为真身，用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准。
