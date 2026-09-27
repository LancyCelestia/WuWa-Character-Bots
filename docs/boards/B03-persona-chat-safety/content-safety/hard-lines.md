# 内容安全与亲密模式 · 六条硬线与不可架空

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 六条硬线与不可架空

- 层级：一级 B03 → 二级 content-safety → 三级 `hard-lines`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/security`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

守界面的确定性闸：一条文本进来，先折形/归一，再过「六条硬线 + 未成年」的词面与共现判定，命中即以 `scope="all"` 拦截，**不因用户设定、管理员身份或亲密模式已开而放行**。产出是一个 `SafetyAssessment`（命中类别、是否拦截、面向用户的守界话术键），供 chat 主链与主动投递共用。它只回答「能不能说」，不回答「该切哪个模型」——后者是 [亲密档位与双开关](intimate-mode.md)。生效条件：始终生效，没有可关的总闸（关掉即等于没有红线）。

## 怎么调用

真身在 `plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`；`security/` 下旧同名件已是再导出垫片，只准 import canonical 路径。核心公开件：

- `assess_public_content(...)`：主判定入口，收 `text`、`category`、`session_type`、`user_role` 等形参；`scope="all"` 的硬线档任何参数组合都越不过（不可绕过的结构锁见下方测试）。
- `minor_ambiguity_hit(text)`：未成年「歧义即拒」谓词——年龄或身份不明、出现儿童化信号时返回真，fail-closed，声称成年也洗不白。
- `normalize_for_matching(text)`：匹配前统一归一（NFKC、零宽剥除、空白折叠）；繁简折形走 `fold_traditional_to_simplified()`，库不可用时降级字级兜底表并显式告警。
- `safe_boundary_output(...)`：拦截后的用户可见出口（守界婉拒句），与 `personas/` 的「边界与红线」话术同源。

调用点（只消费、不重复判定）：`domains/chat_reply/capabilities/chat.py`（文字主链）、`domains/media/capabilities/tts.py`（语音播报共用同一道闸、同一个 `explicit_allowed` 单一事实源）、根 `__init__.py` 的被动好感感知，以及 `character/affinity.py`（`classify_behavior` 与本闸同源，守界拒答不扣好感）。

## 开关与参数

- 词面表、共现窗口宽度、儿童化信号集与成年 grounding 形态都是**代码常量**，没有配置键：放宽红线必须走代码评审 + 重启，不给会话面热改。
- 共现窗口与英文词面的 CJK 邻接望卫（形如 `(?<![A-Za-z])…(?![A-Za-z])` 的边界，治中文直连英文时 `\b` 失效）住本件真身，具体宽度以该件常量为准。
- 繁简折形在 import 期跑一次探针自检（`FOLD_STATE.backend` 可读出走的是库还是兜底表）；探针不过按库不可用处理，绝不「装了库却折成零」而不自知——locale 必须是简体中文那一档，写错档会静默 no-op。
- 与相邻入口不同源：本入口管「能不能说」，切模型与放篇幅的档位在 `bot_content_route_*`（见 [亲密档位与双开关](intimate-mode.md) 与 [四名单与群级门](roster-gates.md)），两把尺子互不替代。

## 失败时看到什么

- 判定自身抛异常：fail-open 到「安全缺省」，但只对非硬线档位；`scope="all"` 的硬线判定不参与降级，降级只会更保守、不会更宽。
- 用户侧是一句守岸人语气的温和婉拒（不点名「你触了红线」、不解释词面规则），细节进审计标签与日志。
- 被守界拒掉的消息不写记忆、不扣好感，避免「她拒绝我 = 她讨厌我」的错误反馈环。
- 繁体、夹零宽、拆句、夹带外语仍可能穿透：这是词面 + 共现的固有边界，最后一道是人格层软防线（`personas/` 与 Runtime 副本的「亲密边界」节），本闸不承诺语义级理解。

## 测试与验收

`tests/test_content_safety_v2.py` 至 `test_content_safety_v6.py`：逐轮裁定的行为锁——六硬线中英样本、儿童化 fail-closed 与成年 grounding 对照、CJK 邻接望卫（中文直连英文词面）、共现窗口、三参数不可绕过的结构锁、过拦对照组。真身模块自述与裁定口径见 `docs/design/r18-taxonomy-20260920.md`。
真机：`docs/acceptance-manual.md` §6.6.8（内容政策面）；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准。
