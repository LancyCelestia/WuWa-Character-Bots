"""Compat shim: moved to domains/transport/mail/mail_adapter.py (v21r2 reorg W14 transport).

bot.py 经 ``plugins.bot_unified_runtime.mail_adapter`` 直接导入 ``ResilientMailAdapter``；
本垫片保证入口零改动（方案书 §3.2）。
"""

from plugins.bot_unified_runtime.domains.transport.mail.mail_adapter import *
