# v21r5 U17-CODEREVIEW 席日志

- 席位：U17-CODEREVIEW（只读质量复审；唯一写面=本 log）
- 开场时间：2026-09-19
- 审查对象（实读工作树，非 diff 工具）：
  1. `plugins/bot_unified_runtime/domains/assistant/campus/campus.py`
  2. `plugins/bot_unified_runtime/__init__.py` campus handler 段（约 :5027-5130）
  3. `tests/test_campus_digest.py`
  4. 对照 `docs/design/v21r5-U17IMPL-log.md` / `docs/design/v21r5-U17REVIEW-log.md`
- 审查维度：
  1. builder 字段映射 vs SendRequest 契约（session_id/target_scope/capability_id/dedupe_key/audit_tags persona 机制）
  2. `_offload` 闭包：异常吞噬面/池竞争注释真实性/与 offload_capability 同构声明
  3. BLOCK 观测：detail 无源文本/suppression 生效/best-failure 不抛
  4. 测试卫生：新例断言语义独立/harness ReceiptState 注入脆弱性（REVIEW M1 同族？）
  5. 命名/风格/类型标注与项目惯例一致性
  6. FIX-U17 redact 落点：只及转发正文、不误伤 store 原文落库
- 结论：待填（逐维度判定 + 发现分级 Critical/Important/Minor/nit + 总裁决）

## 进度流水
- [开场] 建 log；并行读取四类对象文件。
