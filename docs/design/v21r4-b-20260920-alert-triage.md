# 09-19 三条运行时告警调试档案（主代理席 · systematic-debugging）

## 取证
1. 进程（Get-CimInstance 实测）：**两个 bot.py 同时在跑**（均 2026-09-19 12:03:24 启动）——
   - PID 9732 = **系统 Python**（`AppData\Local\Programs\Python\Python312\python.exe bot.py`，非项目 venv）：**持有 8080 LISTENING + SnowLuma 3001 WS 连接 = 现役服务实例**；
   - PID 32256 = venv python bot.py：**零 TCP 连接 = 僵尸实例**（8080 被占未自灭）。
2. 新码在盘证据（domains/chat_reply/llm_engine/model_router.py）：链预算止损缺省 3s（:188/:638/:2116）、失败冷却 90s 降级（:598-608/:1984）、config_missing/auth 有意**不**进冷却（:599-601 设计注释「配置问题≠渠道不可用」）。
3. 链长时序（用户告警原文）：01:48 chain=14（重启前旧进程）→ 12:16 chain=15（12:03 新进程冷启动全表 walks）→ 13:00 chain=**6**（冷却降级生效、链缩短）——**证明冷却机制在工作**。
4. 同分钟耦合：13:00:14 LLM 全链 network 与 13:00:41 TG getUpdates NetworkError 同时发生 = **整机出站网络中断**（代理 127.0.0.1:7890 或上行）。
5. TG 文案出处 = scripts/telegram_resilience.py:107-108（v21r2 ⑨ 交付的韧性话术，指数退避 48s 在工作），**设计内行为非缺陷**。

## 结论
- 三条告警根因 = **外部网络中断**（LLM 渠道+TG 同时不可达）+ **故障转移按设计全表 walk**（一次请求吸收发现成本，冷却保护后续 90s）；无新代码缺陷。
- 真缺陷（办案中揪出）= **双实例 + 现役实例跑错解释器**（系统 Python 而非 venv）：依赖漂移风险+重复处理风险。处置=用户动作：杀两进程→venv 单实例重启（netstat 验证仅一实例持 8080）。
