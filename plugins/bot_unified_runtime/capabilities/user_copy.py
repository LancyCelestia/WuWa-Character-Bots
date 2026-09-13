"""跨能力复用的用户可见话术常量池（UX-COPY U12 沉淀项）。

话术来源与语气基准：fix-uxc-report.md（U6/U9/U11/U12 落地文案）。
收编标准：跨文件复用或多处同文案的用户可见话术才入池；单点文案留原地。

纪律：
- 改这里的常量 = 改用户可见输出。改前先看 tests/test_user_copy_pool.py
  （逐字节文案快照 + 引用点表达式锁定），改后跑该测试与受影响能力定向回归。
- 纯常量模块：禁止 import 任何依赖，防止装配环。
"""

# U11 管理员门禁统一模板：「要<动作>，找管理员来操作。」
ADMIN_GATE_REQUIRED = "要{action}，找管理员来操作。"

# U12 数据源临时失败统一结构：原因短语 +「稍后再试。」
DATASOURCE_TEMP_FAILURE = "{reason}，稍后再试。"

# U9 推送表写盘失败（today_history 设置/取消两处同文案）
PUSH_SAVE_FAILED = "推送时间的改动没保存成功（写盘出错，我已记下原因）。稍后再发一次；还不行就找管理员看运行日志。"

# U6 运行环境异常共享尾段（file_exchange 起 Python/临时目录两处）
RUN_ENV_FAILURE_ADVICE = "稍后再试；还不行就找管理员看运行日志。"
