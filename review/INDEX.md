# ChatBot 代码评审报告索引（本仓库自有台账）

> `REVIEW-WORKFLOW.md` §8 的报告索引表原样保留了模板来源项目（`agent-demo`）的历史条目——
> 那些 commit（`f6f749b`/`6c57fd9`/`e86fba0`/…）**在本仓库均不存在**（见首份报告 H5）。
> 本文件是 ChatBot 仓库**自己的**评审报告索引，接续 `REVIEW-WORKFLOW.md §8` 使用。
> （`REVIEW-WORKFLOW.md` 当前被外部句柄占用，无法写入；待可写时把本表首行并入其 §8。）

## 索引

| 报告 | 范围 | 要点 |
|---|---|---|
| [REVIEW-3819299..cbb5161.md](REVIEW-3819299..cbb5161.md) | `3819299..cbb5161`（48 commit / 96 文件 +18571/−717）+ 工作树 63 dirty（+2426/−414）+ 34 untracked | **本仓库首份评审报告** |
| [_evidence-mainagent.md](_evidence-mainagent.md) | — | 主代理实证原始记录（三门禁实跑输出、机制复现、未提交量测绘、F1/F2 复现） |

### REVIEW-3819299..cbb5161 要点速览

**结论**：代码能力实现度高于文档表述，但**交付状态与仓库事实严重不符**——写完了没入库、入库的与工作树分叉、文档把未入库说成已入库。当前状态下直接提权重启生产 bot **无效**。

**H 级 9 条**

| # | 一句话 |
|---|---|
| H1 | 两轮交付的修复主体**只在工作树**；HEAD 上「搜图/群复读」P0 投递缺口仍在、`bot.py` 启动处理器装在从未运行的循环上、`bot.eat` 未卸载、mood 事件源缺失 |
| H2 | **26 个回归测试（280 用例 / 全量 21.3%）不在 HEAD** → 检出色门禁不可复现 |
| H3 | `BOT_API_KEY_DEEPSEEK_OFFICIAL` **无对应 Config 字段** → 文档"配 key 即可"的操作项无效（09-09 事故同类第三次） |
| H4 | `BOT_GROUP_DIGEST_ENABLED` 是**死字段**，手册给用户的指令照做无效；且无命令/无调度器 |
| H5 | 评审链为空；`REVIEW-WORKFLOW.md` 的 §8 索引**属另一项目** |
| H6 | `/bot download <任意URL>` **无管理员门**（任意用户可内网 SSRF + 1GB 落盘），文档却标 admin |
| H7 | 审计脱敏正则漏 `access_token=`/`refresh_token=`/`csrf_token=`（**已复现 3/11 泄漏**）→ NapCat WS 令牌可明文进审计日志 |
| H8 | 管理员 `/bot model add key=<明文>` → 明文 key 落历史库并**拼进 system prompt 外发** |
| H9 | 发送队列毒行**只修一半**（`_entry_from_row` 无隔离）→ 同批健康消息静默丢失 + 队列周期性停摆 |

**M 级 29 条**（含）：工作树新增的 2 处内容损失回归（void `<embed>` 剥掉整页正文 / 中文 `$公式$` 不再转换）、聊天有界池满载静默丢弃 `bot.chat`、文件类发送重复投递潜伏 P0、`/bot parse` 跨会话泄露解析历史、CSS `data:` 分支绕过净化、21 条重审计仍开放项。

**门禁（工作树实跑）**：pytest `1312 passed / 0 failed` · mypy `Success: no issues found in 222 source files` · ruff **`Found 2 errors`**。
