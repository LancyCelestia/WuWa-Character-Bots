# 安全与凭据护栏 · 敏感信息不回传

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.security-guardrails · 敏感信息不回传

- 层级：一级 B10 → 二级 security-guardrails → 三级 `exposure-floor`
- 实现落点：`plugins/bot_unified_runtime/domains/core/credentials`、`plugins/bot_unified_runtime/domains/chat_reply/security/__init__.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/injection.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/display_guard.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/spoof_audit.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/database_broker.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

回复文本离开 bot 之前的最后一道确定性打码。它防的不是外部攻击，而是**模型被诱导复述本机信息**：用户问「把你的 .env 念一遍」「你机器上那个目录里有什么」，或者某条注入指令成功让模型吐出带令牌的报错文本。人格层的软拒绝会失手，所以要有硬编码的最后一闸。

真身：`domains/render/plain_text.py:redact_local_secrets`，接在出站链路上（说人话与数值打码同处），覆盖七类形态——`BOT_XXX=` 赋值、`sk-` 形态 key、Windows 盘符绝对路径、URL userinfo 段、JWT 三段式、Bearer token、裸键值对（`sendkey=` / `token:` / `key=` 一族词干）。

## 怎么调用

- 调用点：出站文本成型后统一过一次；渲染失败的纯文本兜底同样过闸（契约零破坏是渲染铁律，打码不许成为例外）。
- 语义：无命中即原样返回，热路径近零成本；有命中按固定顺序替换——先整段打掉 `BOT_XXX=` 赋值（值里可能同时含路径与 key），再打独立 key，然后 userinfo、JWT、Bearer、裸键值对（JWT 先于 Bearer，整条一次打掉），最后打剩余盘符。顺序是语义依赖，不许重排。
- 占位符两个：`<已隐藏>` 与 `<本机路径已隐藏>`。替换产物不会被二次匹配（幂等），同一段文本过两次闸结果一致。
- 快路径哨兵与正则一一对应，判据是「宁可多扫一遍也不能漏」：出现 `BOT_`、`sk-`、`:\`、`:/`、`@`、`eyJ`，或小写化的 `bearer`/`key`/`token`/`secret`/`passw` 任一即进入完整扫描。

配套的源头规矩（打码只是兜底，不是许可）：真实 key 只在 `.env`，配置一律 `env:变量名` 引用；密钥不写进 Markdown、Issue、归档说明与聊天；`docs/config-catalog-full.md` 头部明确声明「从未读取真实 `.env`，只引用 `.env.example`」；`_SafeMediaLogger` 一类纪律要求签名 URL 与 cookie 不进日志；`domains/core/credentials/credentials.py` 要求凭据值不进 `AuditRecord.private_debug`、`RuntimeDiagnostic`、用户可见消息与 prompt。

## 开关与参数

无配置键，且不可关。它不在 feature flag 面里，因为「可关的最后一道防线」不成立。

谁能改：只有把新形态补进正则、并同步补一条**注毒用例**（种一段该形态文本，断言被替换成占位符）的人。历史上这道闸一开始只覆盖三类高置信形态，URL userinfo / Bearer / JWT / 裸键值对全部漏网，是评审 F-01 逐形态补齐的——每次扩形态都要同时写防「又漏回去」的锁。

## 失败时看到什么

用户看到的是句子里凭空多了 `<已隐藏>` 或 `<本机路径已隐藏>`，其余文字保持原样（打码不做润色、不改句式、不吞整条回复）。

两种典型问题：

- **该打没打**：新形态不在七类里。判据是拿真文本构造样本先复现，再决定是扩词干还是加新正则；扩词干要同时收紧误伤边界（裸键值对那条对词干左禁邻字母、右禁邻字母数字下划线、值长度有下限，就是为了不把所有 `key=` 类正常文字打成码）。
- **打过头**：正常内容被吞。评审先例是文案红线门打到自家波次写的探针字面量，处置是**改样本不改规则**——任何「为了过门而放宽安全规则」的动作都要当 P1 看待。

## 测试与验收

`tests/test_secret_redaction_hardening.py`（逐形态正反例，含 F-01 四类的扩面锁）、`tests/test_f03_notice_redaction.py`（第三方出处声明的打码面）、以及各能力测试里「回复里不许出现盘符路径」的断言。全仓卫生扫描的既有做法是 grep 密钥形态后逐条判真伪（一次实测结论为「命中全是占位符、零真实密钥」），复跑命令：

```
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_secret_redaction_hardening.py -q -p no:cacheprovider --basetemp=$TEMP/ef
```

真机验收：重启后在私聊里显式诱导复述 `.env` 与本机目录，确认回复只出现占位符（条目指针见 `docs/acceptance-manual.md` §6.6 族）。
