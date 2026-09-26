"""``domains/media/tts/`` —— 语音域的「呈现变换」子层（席位 S36 开）。

现役真身不在这儿：合成管线/产出步单一真身仍在
``domains/media/capabilities/tts.py``、预设与生效硬顶在 ``domains/media/tts_presets.py``。
本子层目前只装一件东西：「结果变换形」执行体 ``result_transform.py``
（自动配音第二条腿的**中央第三形**——S36 落件、S91 收编进注册册并通电，
现网两枚键关 ⇒ 今天不可达；口径与逐条证据见该件模块 docstring「通电状态」段）。
本 ``__init__`` 刻意不 re-export 任何符号——壳不搬真身（禁第二真身）。
"""

from __future__ import annotations
