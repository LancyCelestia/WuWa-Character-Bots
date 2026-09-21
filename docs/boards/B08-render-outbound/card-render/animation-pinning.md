# 卡片渲染 · 动画钉帧与截图确定性

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.card-render · 动画钉帧与截图确定性

- 层级：一级 B08 → 二级 card-render → 三级 `animation-pinning`
- 实现落点：`plugins/bot_unified_runtime/domains/render`、`docs/rendering-contract.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

让「同一个 payload 渲两次得到同一张 PNG」成立。卡片上的色斑是无限循环漂移动画，截图落在墙钟的哪一刻本来随机；不钉住，回归比对就没有可信判据，样张基线也会自己漂。

做法：截图前在页面里执行一段 WAAPI 脚本，遍历 `document.getAnimations()`，只对目标元素能 `closest('.card')` 命中的动画 `pause()` 并置 `currentTime = 0`。与 CSS 里按内容摘要派生的负 `animation-delay`（`--phase`）联合，得到的正是「加载即暂停」的相位帧——与既有相位设计逐字节一致，且与调用时刻无关。

入口是内部函数 `domains/render/render_backends.py:_pin_card_animations`，在元素截图与 `full_page` 兜底两条路径分叉之前各调一次（同一文档，钉一次两路同益）。

## 怎么调用

**不需要调用**——它是后端出图流程的一个固定步骤，能力层与 bridge 都不感知。要理解的是它的两个配套件：

- 相位来源：`domains/render/card_render/bridge.py:stable_payload_digest` → `digest_phase` / `payload_phase`，把 payload 内容摘要映射成 `--phase` 负延迟。这一步只钉**初相**（哪一帧是基准），不钉**采样时刻**，两件事不能互相替代。
- 装饰层单源：`domains/render/card_render/mica_shell.py` 的生成器产出色斑 DOM、`@keyframes mica-drift-a/b/c` 与 `prefers-reduced-motion` 关停规则；模板不许手抄。

明确排除的方案（写下来防止有人再走一遍）：截图参数 `animations="disabled"` 会把 infinite 动画**取消到基底位**，等价 `animation:none`，丢掉相位姿态——破坏既有 E01 设计，不采纳；`add_init_script` 注入的样式会被 `set_content` 重建文档时抹除；`add_style_tag` 在 `set_content` 之后注入则动画钟已走，冻结在流逝位而非钉帧位。

## 开关与参数

无配置键、无功能开关。行为条件只有两个：页面是否有可用的 `evaluate`（真实 playwright 页面才有），以及 `.card` 子树里是否存在动画。mermaid 卡的 `wait_js` 流程不受影响——钉帧时机在全部等待之后、截图之前，且全卡面动画只有 `mica-drift-*` 三族（由契约测试锁定）。

## 失败时看到什么

**fail-open，静默**：假页面（测试替身没有 `evaluate`）、脚本执行异常、单条动画设置抛错，都只跳过钉帧、照常截图。代价是这张图落回流逝时刻（外观没问题，字节不可复现），**不会**导致渲染失败或降级纯文本，也不新增故障面。

可观测性的缺口：目前钉了多少条动画、有没有一条都没钉上（`pinned == 0`），外部读不到。这正是要补的 D-8（基线 sha256 旁车入库 + `pinned==0` 告警 + 浏览器指纹字段）。

## 测试与验收

离线：`tests/test_phase_determinism*`（相位派生确定性与守卫，含 universal 混合体特例的相位锁）、`tests/test_v21r3_visual_gates.py` 中色斑数与时长门（gate02，覆盖 11 个渲染面）、`tests/test_rendering_contract.py` 的 keyframes 名门（Jinja 族；直拼卡侧仍缺独立名断言=待补 D-1）、`tests/test_render_backends.py`（钉帧在两条截图路径前均执行、异常不阻断）。

真机主判据（重启后执行，**本板块未跑**）：`python scripts/render_card_samples.py --out <目录>` 与基线 `baseline-20260919-paused` 逐面比 PNG 字节等值，`html_sha256` 作旁证；观察点归 `docs/acceptance-manual.md` §6.6.10 ②③（三枚色斑、reduced-motion 关停）。注意基线目前住在 `%TEMP%`，清临时目录后该判据即灭（D-8 在办）。
