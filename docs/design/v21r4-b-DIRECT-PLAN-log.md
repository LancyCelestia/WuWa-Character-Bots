### 心跳检查点（2026-09-19，巡检探针后落盘）

- [x] 先例取证完成：L34/L35=OutboundSideEffectExecutor（control_plane/dispatcher.py:125-220，未 commit）+ poke 装配（__init__.py:4862-4918）+ reaction 装配（domains/meme/reactions/engine.py:661-702）；先例测试=tests/test_v21_dispatch_outbound_wiring.py（executor 语义 20+ 例）
- [x] 统一路径四形态取证完成：
  - A 管线路径（有 Event）：_send_text_through_unified_pipeline（__init__.py:4666）/_send_parts_through_unified_pipeline（:4694，支持 images）→ _run_capability_through_pipeline（:2519）→ render_reviewed_output（domains/render/renderer.py:186，images:206-208/files:214-216/prefix_parts:201-204）→ SendRequest（domains/chat_reply/runtime/pipeline.py:807）→ send_queue.submit → _deliver_transport_send_request（__init__.py:2433）
  - B 调度 job 路径（无 Event）：_deliver_due_reminders 范式（__init__.py:2852-2956）：构造 SendRequest→submit→_find_sent_request→内联 transport 投递→送达销账
  - C 副作用 executor 路径（poke/reaction 型平台原子副作用）：dispatcher.py:125-220（cancel 闸→准入→租约→固定映射→call_api 通道本体）
  - D 文件路径：CapabilityResult.files→renderer media_parts（renderer.py:214-216）→transport file 部件→get_default_file_gateway stage→deliver（domains/transport/sender/onebot.py:439-462）；既有测试 tests/test_phase0_3_features.py:180 已锁该链
- [x] notice 事件进摄取已确认可行：_incoming_from_nonebot_event（__init__.py:1263-1283）对 NoticeEvent 族 get_plaintext ValueError 降级空文本、group_id/user_id 属性面可用
- [x] ⑤登记表陈旧明细：outbound_registry.py:589-600 三条 BYPASS_SUSPECT 坐标全陈旧（4070→现4300、4878→现poke执行器装配区、5175-5182→现5184欢迎单通道）；:183-187 SEND_MESSAGE evidence 字符串陈旧；:205-216 poke/reaction 已收编但仍记 BY_DESIGN 待收编口径；:607-610 delete_msg 4569→现4802；:631-634 file_gateway 老路径 sender/→现 domains/transport/sender/
- [x] 既有测试面盘点：欢迎只有文本/门测试无发送路径断言（test_group_notice_b05.py）；cookie 到期提醒零测试覆盖（全 tests/ grep 无命中）；文件上传链已有 transport 级测试（test_phase0_3_features.py:180）
- [ ] 方案文档落盘 docs/design/v21r4-b2-direct-collect-plan.md ← 当前动作
### 交付完成（2026-09-19）

**交付物清单**：

1. `docs/design/v21r4-b2-direct-collect-plan.md`（本席唯一交付物，方案文档，零代码改动）——含：
   - §一 五处直连点读时快照重定位表 + 同文件其余 call_api 甄别（READ_PATH/BY_DESIGN 不收编清单）
   - §二 逐处现状取证（触发/去向/失败面/绕过方式，全部 file:line）+ ⑤登记表逐条陈旧比对表（8 条）
   - §三 收编方案：统一路径四形态依据表（管线/调度job/executor/文件网关）+ 逐处方案（①→形态B提醒范式+日期幂等、②→形态A管线、③→形态A mixed 图片、④→形态D文件网关链、⑤→纯登记表刷新）+ 各自开关（全部缺省关）/测试策略/风险回滚 + file_gateway PENDING_RULING→CHANNEL_BODY 裁定建议 + 明确不收编清单（防扩界）
   - §四 责任面划界（根 __init__.py 四点=WIRE-SVC 释放后才可动；⑤登记表+新测试文件=现在即可动；config 键须与 WIRE-SVC 区段错峰）
   - §五 工作量级与执行顺序（⑤先行→④→②→③→①→真机验收；共享「开关缺省关+旧路径锁测试」模式）+ 实施席前置检查单
   - §六 证据状态汇总（verified/转引/unknown 三档全声明）+ 全局诚实声明
2. 漂移实证补记：两次只读扫描间①配置门 :4262→:4277（WIRE-SVC 在飞实证），二扫锚点已写入方案文档头部，实施席以符号 grep 重定位。

**完成判定对照**：方案文档落盘 ✅；日志交付清单 ✅；五处坐标全部重新定位并带 file:line ✅；每处现状四要素取证 ✅；逐处收编方案（对齐 L34/L35 先例+backend-protocol-plan.md B2③+缺省关门+离线 mock 测试策略+风险回滚）✅；责任面划界 ✅；工作量级与顺序 ✅。硬约束全程遵守：零 git 写、零子代理、零 .py 改动、零渲染域触碰、矩阵只读、无真实发送/LLM/重启、无 python 直跑（纯 grep/sed/git log 只读，零树卫生风险）。**方案材料无一表述为已生效/已接线。**

——DIRECT-PLAN 席终。
