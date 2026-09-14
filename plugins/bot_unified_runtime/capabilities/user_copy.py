"""跨能力复用的用户可见话术常量池（UX-COPY U12 沉淀项）。

话术来源与语气基准：fix-uxc-report.md（U6/U9/U11/U12 落地文案）。
收编标准：跨文件复用或多处同文案的用户可见话术才入池；单点文案留原地。

纪律：
- 改这里的常量 = 改用户可见输出。改前先看 tests/test_user_copy_pool.py
  （逐字节文案快照 + 引用点表达式锁定）与 tests/test_user_copy_unification_gate.py
  （旧句式池外硬编码负向扫描门），改后跑该测试与受影响能力定向回归。
- 纯常量模块：禁止 import 任何依赖，防止装配环（sources 层零依赖常量池
  跨层引用因此安全，见审查 Q-01）。

豁免登记（审查 Q 组 2026-09-15；语义特殊或域禁碰，不强制入池）：
- 订阅族「群内添加订阅需要管理员。」（subscribe_v2.py）：含群推送目的地
  具体上下文，非通用门禁语义；文件属并行在飞禁碰域。
- 订阅族「没有权限操作该订阅。」（subscribe.py / subscribe_v2.py）：
  资源属主校验语义（非管理员门禁）；文件属禁碰域。
- media_archive.py「这个归档功能暂时只对超管开放，这份心意守岸人先记下了。」：
  超管门槛（BOT_MEDIA_ARCHIVE_MIN_ROLE），写「管理员」会失实，不适用
  管理员门禁池；卖萌语气已按 Q-02 去除。
- group_info.py「公告和精华只有管理员能看哦，先不给你翻这份啦。」：
  禁碰域（Q-02 卖萌体残留，待该文件域批次收口）。
- __init__.py「只有管理员才能…」族：禁碰域（绝对不碰）。
- echo.py _HELP_ENTRIES 内「…晚点再试试？」/「…稍后再试。」为 help 文本对
  兜底行为的历史引用示例，非输出本体；help 口径变更牵动 command-catalog
  同步门（域外），按引用原文保留。
- content_parser.py「…先把原链接放在这里，晚点我再试试：」：附原文链接的
  重试承诺（非纯失败告知），且含第一人称自称（Q-04 未列点，留待专项）。
"""

# U11 管理员门禁统一模板：「要<动作>，找管理员来操作。」
ADMIN_GATE_REQUIRED = "要{action}，找管理员来操作。"

# Q-02（2026-09-15 文案统一批）：权限拒绝池。首条 = U11 原模板（订阅族等
# 既有引用点零行为变化），其余为守岸人语气变体（温和、不机器腔、不卖萌）；
# 域内调用点用 random.choice(ADMIN_GATE_TEMPLATES).format(action=...) 取句。
ADMIN_GATE_TEMPLATES: tuple[str, ...] = (
    ADMIN_GATE_REQUIRED,
    "{action}需要管理员权限，守岸人做不了主。",
    "要{action}，得请管理员出面才行。",
    "守岸人过不了这道门——要{action}，得找管理员来操作。",
)

# U12 数据源临时失败统一结构：原因短语 +「稍后再试。」
DATASOURCE_TEMP_FAILURE = "{reason}，稍后再试。"

# Q-01（2026-09-15 文案统一批）：数据源临时失败池。首条 = U12 原模板，其余为
# 守岸人语气变体；调用点用 random.choice(DATASOURCE_FAILURE_TEMPLATES)
# .format(reason=...) 取句。reason 传「<对象>暂时拉不到」式短语。
DATASOURCE_FAILURE_TEMPLATES: tuple[str, ...] = (
    DATASOURCE_TEMP_FAILURE,
    "{reason}，晚点再试试？",
    "{reason}，守岸人晚点再帮你看看。",
    "{reason}，潮水这会儿不顺，稍后再来一趟吧。",
    "{reason}，先放一放，过阵子再试一次。",
)

# U9 推送表写盘失败（today_history 设置/取消两处同文案）
PUSH_SAVE_FAILED = "推送时间的改动没保存成功（写盘出错，我已记下原因）。稍后再发一次；还不行就找管理员看运行日志。"

# U6 运行环境异常共享尾段（file_exchange 起 Python/临时目录两处）
RUN_ENV_FAILURE_ADVICE = "稍后再试；还不行就找管理员看运行日志。"
