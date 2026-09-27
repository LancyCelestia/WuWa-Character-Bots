# 出站文案与纯文本兜底 · 本地密钥与路径打码

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.outbound-copy · 本地密钥与路径打码

- 层级：一级 B08 → 二级 outbound-copy → 三级 `secret-redaction`
- 实现落点：`plugins/bot_unified_runtime/output`、`plugins/bot_unified_runtime/domains/render/plain_text.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

发出去之前，把「本机的事」从话里抹掉。触发场景很实在：模型被诱导复述 `.env`、把某个能力失败的原异常连同路径一起贴回会话、或者告警文案里带着 cookie 值。

`domains/render/plain_text.py:redact_local_secrets` 覆盖的形态（每条都带防误伤边界）：

| 形态 | 处理 |
|---|---|
| `BOT_XXX=值` 赋值 | 值整体换成 `<已隐藏>` |
| `sk-` 开头的 key | `sk-<已隐藏>` |
| URL userinfo（`scheme://user:pass@host`） | 只打码凭据段，保留 host/path，看得出是哪个服务 |
| JWT 三段式 | 整条打码（任一段都可参与重放，只打 signature 治标不治本） |
| `Bearer <token>` | 保留 `Bearer` 前缀，短于长度门槛的 token 视为示例不打（门槛以该件正则为准） |
| 裸键值对 `sendkey/api_key/secret/passw(or)/token/key = 值` | 词干左右边界严格（`monkey=`、`keyword=` 不命中，`access_token=` 命中），值达到长度门槛才打（门槛以该件正则为准） |
| Windows 盘符形态的绝对路径 | `<本机路径已隐藏>` |

顺序有意排过：先整段打掉赋值形态（值里可能含路径或 key），再打独立 key，再 F-01 四形态，最后剩余盘符路径。

## 怎么调用

显式调用，不是渲染器自动施加。出站主链上它出现在 chat 能力出口（与打码后文本再进 `normalize_paragraph_breaks` 的固定顺序），另外被以下出口各自调用：运维告警与事件账、错误卡（栈摘录、触发回显、配置快照逐帧脱敏）、TTS 与媒体归档回显、校园转发通知、控制面 actions/events/workspaces、知识服务、同步巡检。2026-09-24 起多了一条**主动投递腿**：中央出口 `submit_active_push` 在入口第一站、先于幂等键形规范与三道门判定，就对请求正文过一次它（`_redact_active_push_body`，就地改写而非副本——否则调用方内联投递的分支会漏洗）——「打码是出站无条件动作，主动推送也不例外」。全树消费者清单以 grep 为准，本处不写数量。

同模块另有一处**不是**出站咽喉的近似件：`humanize_reply` 里的内心数值打码（「好感度 87 分」→「好感度…保密」），那是拟人化红线不是安全红线。审核侧 `domains/render/reviewer.py:_redact_output_match` 也只用于把命中片段安全地写进审计理由，不代表文本被放行前已被打码。

## 开关与参数

无开关、无配置键：它被定位为出站前无条件动作，**不要绕过**（工作区铁律的打码条款）。无命中时走快路径哨兵原样返回，热路径零成本；哨兵与正则一一对应，取向是「宁可多扫一遍也不能漏」。

要改行为只能改这个函数本身，并且必须同时更新它的正反例测试。

## 失败时看到什么

设计上不存在「失败」：无命中即原样返回，异常形态（半截正则匹配、嵌套引号）退化为「多打一点」而不是「少打一点」。用户侧看到的就是 `<本机路径已隐藏>` / `<已隐藏>` 这类占位。

已知的真实缺口（别把它当语义识别）：

- **词面/形态匹配**：拆字、插空白、换编码、把值改写成自然语言描述都能穿透。防线本体是「密钥不进回复」的提示词与配置面（key 只在 `.env`，配置用 `env:变量名` 引用），这里是最后一道确定性拦网。
- **快路径哨兵与新形态脱钩的风险**：新增形态若忘了同步哨兵字符，会走「命中不了」的静默路径；现有测试用「必打」正反例钉住，加形态必须加样本。
- **非出站面不设防**：日志、Runtime SQLite、审计详情不经此函数——它是出口打码器，不是存储加密。

## 测试与验收

`tests/test_secret_redaction_hardening.py`（F-01 七形态正反例 + 防误伤边界 + 幂等：产物不被二次匹配）、`tests/test_f03_notice_redaction.py`（通知面）、`tests/test_error_report.py` 与 `tests/test_error_card_contract.py`（栈与配置快照逐帧脱敏）、`tests/test_tts_filename_privacy.py`（文件名与路径不外泄）、`tests/test_credential_domain_binding_gate.py` 与 B01/B05 的凭证作用域门（同一红线的上游半边）。

真机（重启后）：诱导性提问一次（例如要求「把你的环境变量原样贴出来」），确认回复里只有占位符；再看 `/bot logs`、错误卡、告警文案三处均无盘符路径。
