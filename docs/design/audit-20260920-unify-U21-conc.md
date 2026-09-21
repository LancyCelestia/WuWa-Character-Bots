# U21-CONC 审计日志 — 并发 / 线程 / 资源生命周期统一（2026-09-20）

> 席位：U21-CONC（只读审计子代理）。工作区 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot`。
> 范围裁定：只查后端 Python。**不查不碰** webui/、domains/render/**、output/card_render/**、theme_tokens.py、TTS/语音链路。
> 渲染后端浏览器只看「生命周期与线程归属」一层。
> 硬禁令：不再派子代理；无 git 写；不改代码/配置（除本文件）；无 `--write`；无真实网络/LLM/发送；**不 kill 不启动任何进程**；不读 .env 明文；ChatBot_Runtime/ 只读。

## 席位总目标（用户统一 mandate 的运行时侧）

「中央统一处理」在运行时必须意味着：
1. **只有一层线程/事件循环边界模型**；
2. **只有一种 offload 规则**；
3. **只有一种资源取得与释放路径**。

凡各模块自开线程 / 自设超时 / 自建缓存、某条通路在错误线程上跑阻塞 IO、资源只取不放 → 即为缺陷。

## 引用同波既有结论（不重复取证）

- `audit-20260920-unify-U4-dispatch.md` — M-2：`_prepare` 同步跑在事件循环线程、`bot.news` 漏登 offload 白名单（本席穷尽该清单）。
- `audit-20260920-unify-U9-function.md` — 网络重试/超时实现份数。
- `audit-20260920-unify-U13-db.md` — 裸 connect 75 处 / busy_timeout 缺失。
- `audit-20260920-unify-U3-outbound.md` — UNKNOWN/PARTIAL 断点续发。

## 进度状态

| 节 | 交付物 | 状态 |
|---|---|---|
| D1-1 | 线程/池创建点全枚举 + owner 表 | 待办 |
| D1-2 | offload 规则单源性判定 + 「该 offload 而未 offload」穷尽清单 | 待办 |
| D1-3 | 事件循环线程上的同步阻塞 IO（本席最重要交付物） | 待办 |
| D1-4 | threading.local / 线程中毒残留 | 待办 |
| D2-1 | 锁清点 + 读改写无保护可变状态 | 待办 |
| D2-2 | 双实现限流竞态语义 | 待办 |
| D2-3 | 幂等 claim 四层并发放行可达路径 | 待办 |
| D2-4 | 调度器重叠 / 单飞保护 / 补投风暴 | 待办 |
| D2-5 | 时区与系统钟一致性 | 待办 |
| D3-1 | 句柄泄漏清单 | 待办 |
| D3-2 | 常驻资源 + 内存无界增长 top5 | 待办 |
| D3-3 | 磁盘增长与 prune「只定义未调用」 | 待办 |
| D3-4 | 退出清理与关停顺序 | 待办 |
| D4-1 | 背压缺失生产者链 | 待办 |
| D4-2 | 超时预算叠乘最坏端到端延迟 | 待办 |
| D4-3 | 告警抑制单源性 + 静默失败清单 | 待办 |
| 附 | 未覆盖清单 / 收口清单 / 可观测性缺口 | 待办 |

## 环境卫生自查

- 直跑 python 一律带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest 带 `--basetemp="$TEMP/u21-*" -p no:cacheprovider`。
- 分析脚本一律写 `%TEMP%`，不写源码树。
- 树卫生复扫见文末「自查与披露」。

---

# D1 线程与事件循环边界统一

（待填）

---

# D2 竞态与锁

（待填）

---

# D3 资源生命周期与「只取不放」

（待填）

---

# D4 失败面与背压

（待填）

---

# 收口清单与可观测性缺口

（待填）
