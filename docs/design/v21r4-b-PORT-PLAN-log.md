# PORT-PLAN 席位进度日志（B2② 端口装配组·接线方案材料）

> 席位：PORT-PLAN｜包：B2②｜交付物：docs/design/v21r4-b2-port-wiring-plan.md（只读调研+方案文档，零代码改动）
> 本文件是断点续跑依据。红线：本席零实装、零真实发送；方案文档不得写成已生效/已接线。

## 2026-09-18 开工

- [x] 开工第一动作：已追加协调表 `v21r4-b-coordination.md`（PORT-PLAN | B2②方案材料 | docs/design/v21r4-b2-port-wiring-plan.md（只读+文档））。
- [x] 已读 HANDOFF-V21R4-B-20260918.md（纪律红线：对外动作先问；诚实红线 6 条）。
- [x] 已读 docs/design/backend-protocol-plan.md §三 B2②（端口装配组=L46 WORKSPACE+L47–L54 相关行，高风险先问）。
- [x] 已读 backend-v2-acceptance-matrix.md 现状。**行号漂移发现**：MAT 席 B1 回填批注已合入矩阵头部（第 7 行），主表行号整体 +2——交接书/草案 L 编号 = 现文件行号 − 2（L39 WORLD→现41、L46 WORKSPACE-001→现48 等，与交接书 B2① 域名清单逐一吻合）。方案文档将双编号并列引用。
- [x] 取证完成（关键坐标）：
  - 503 not_wired 精确位置=`control_plane/workspaces.py:327-328`（_begin_send 消费确认前）；另 create=503 real_session_unavailable（:186-187）、preview=503 workspace_generator_unavailable（:279-280）。
  - 装配缺口=`factory.py:105-106` 只注入 sandbox_generator；`api/v1.py:75` protocol 面宣告 real_session 恒 False。
  - 测试=`tests/test_v21_s9_workspace.py:151-176`（不烧确认+带端口对照组 queued）、`:196`；`tests/test_control_plane_workspaces_api.py:36,64`。
  - 行号漂移实证=`domains/creation/tts/contracts.py:3` 自引「矩阵 L51 V21-TTS-001」→ 现文件第 53 行，−2 漂移坐实。
  - 端口族 canonical 坐标（v21r2 重组后）：vision_describe.py:620/654、transcribe.py:277/410、video_understanding.py:263、file_reader.py:93/222、file_gateway.py:165/230/316、downloader.py:363、search_service.py:388/623、media_archive.py:353、queue.py:167/242、gateway.py（UnifiedDeliveryGateway）、__init__.py:2433-2460（gateway 装配）、runtime/capability_protocols.py:82,493-497（invoke=unavailable not_wired）。
  - 移交输入=v21r2-s9-log.md §六.1、v21r2-s10-log.md §六 1-6、docs/design/control-plane-workspaces.md「真实会话端口」节（deliver 契约=Policy/Review/Renderer/SendQueue+receipt、delivery_id 幂等、unknown 不展示成功）、guide §6 L149（确认 token 120s 一次消费 vs workspace 合同 300s——TTL 口径分歧已登记待裁定）。
  - 矩阵快照=现文件 L48-L56（WORKSPACE/MEDIA/FILE/TTS/IMAGE/SEARCH 六族）读时仍为回填前值（无〔v21r2〕括注），MAT 席对 L46+ 回填疑在飞；方案文档引用草案 §一 L46-L54（draft:60-68）为准并附读时快照。
- [x] **交付完成**：docs/design/v21r4-b2-port-wiring-plan.md 已落盘。

## 交付清单（2026-09-18 收官）

1. `docs/design/v21r4-b2-port-wiring-plan.md`——B2② 端口装配组接线方案材料（待用户逐项确认，文首显著标注「不构成实施授权；未确认前不得动码」）。含：
   - §〇 行号对照表（交接书 L = 现矩阵行 −2，双编号并列）；
   - §一 逐行现状取证：草案 §一 L46-L54 行原文（draft:60-68）+ 矩阵读时快照（L46+ 回填疑在飞，如实记 unknown）+ workspace/real_session 全坐标（503 not_wired=workspaces.py:327-328 消费确认前；create/preview 503；factory.py:105-106 real_adapter 从未注入=根因；api/v1.py:75 protocol 宣告恒 False；测试 5 处坐标）+ 端口族 8 行 canonical 坐标 + 统一出站路径坐标；
   - §二 逐行接线方案：L46 主方案（4 配置门键缺省关/real_adapter 三端口复用实现/确认协议五层防误触保留+4 个待裁定点/审计回执面/频控白名单/三级回滚/7 步实施波次）；L47-L54 要点式（对外发送面=仅 L46/L50/L51/L52，其余为控制面 REST 化中风险）；
   - §三 风险三级分 + **15 项可勾选前置条件清单**；
   - §四 边界：L41 不覆盖；未确认前矩阵行保持 not_wired、代码保持 503；
   - 附 A 证据与置信度（现状断言=high 源码直读；实跑结论全部转引 s9/s10 席日志并注明）+ unknown 清单 5 项；附 B 权威链。
2. `docs/design/v21r4-b-coordination.md`——开工登记 1 行。
3. 本日志。

## 纪律自查

- 零 .py 改动、零 theme_tokens.py/render_hashes.json/domains/render/**/output/card_render/** 触碰、矩阵只读未改；零 git 写、零子代理、零真实 LLM 调用/对外发送/重启；未直跑 python/pytest（全部取证用 grep/sed/ls/head 只读），源码树零缓存零 data/ 残留。
- 诚实红线自查：方案全文无「已接线/已生效」表述；not_wired 现状如实；实跑证据均转引并注明出处。
