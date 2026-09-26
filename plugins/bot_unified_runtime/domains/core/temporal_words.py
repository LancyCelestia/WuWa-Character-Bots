"""中文时间副词字面量真身（S-TRIG 收编，2026-09-26）：「今天/今日」的字形只有这一份。

成因（副本棘轮门 ``tests/test_trigger_word_copy_ratchet.py`` 44>42 越界副本 D2）：
``domains/chat_reply/runtime/time_window.py``（2026-09-13 起）用字面正则
``(?:今天|今日)`` 解析「总结一下今天群里的聊天」；2026-09-26 检索去噪波新增
``domains/core/search/web_search.py`` 的多字脚手架表（``_CJK_SCAFFOLD_WORDS``）时把
同两枚时间副词收进同一集合——棘轮门按 ``*_WORDS`` 命名式把它收成真身，于是把 09-13
的旧正则追认成"第二副本"。裁定不接受"登记豁免当修好"，本模块即那条唯一正当出路：
两管线共享的时间副词字形收编到一处真身，两侧都改为**引用**——

- ``time_window``：正则由 ``"|".join(TODAY_ADVERB_WORDS)`` 拼装（模式不再是手写词集）；
- ``web_search``：脚手架表 = 疑问/客套段 + 本对 + 其余时间词段 按序 ``tuple +`` 拼接，
  成品与收编前**逐字相同**（其消费点本就按长度倒序排，顺序语义零依赖）。

绑定名含 ``_WORDS`` 命中棘轮门 ``HOME_NAME_PAT``：本文件在两本尺（副本棘轮/词面单源）
视野里就是这对词形的唯一真身——其它位置出现同集手抄将被照常记账，不设豁免。
繁简口径与中央件一致按字面串处理（「今天/今日」繁简同形，无需折叠）。
"""

from __future__ import annotations

from typing import Final

#: 「今天」的两种字形（时间窗解析与检索去噪共用；新增字形须两侧同时评估后才进表）。
TODAY_ADVERB_WORDS: Final[tuple[str, ...]] = ("今天", "今日")
