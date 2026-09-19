"""domains/emergency_info: 外部紧急信息聚合域（气象预警/政务应急/校园紧急通知）。

本席（B1R3）交付可离线测内核：契约与等级枚举（contracts.py）、纯规则定级
（service/grading.py）、去重键与时效窗（service/dedupe.py）、人工报料审核门
（service/review.py）、SQLite 存储（sources/store.py）。

装配期注入、缺省不改变既有行为：本域不新增配置键、不注册路由、不出卡、
不接语音、不碰 LLM（定级/去重/时效/审核全为纯规则，产品裁定 D-6）。
"""
