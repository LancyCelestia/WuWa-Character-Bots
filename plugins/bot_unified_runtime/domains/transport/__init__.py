"""transport 域（v21r2 重组 W14）：出站通道。

子板块：``sender``（发送队列/OneBot/NoneBot 通道/文件网关）、``mail``（邮件桥与韧性适配器）。
旧路径 ``plugins.bot_unified_runtime.sender`` / ``...mail_adapter`` / ``...mail_bridge``
由原位 re-export 薄壳垫片覆盖（退役条件见 docs/design/v21r2-reorg-plan.md §3.1）。
"""
