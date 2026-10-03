# 用户手操教学卡 · §四待办收尾（2026-10-02 晚，主会话）

> 已替你做掉的（无需你动手）：`pre_restart_check` 裸 ruff 腿加 `--no-cache`；`bot_db_backup_*` 七键落四面（config.py / settings.py / .env.example / config-catalog）；gate2 真身薄口（`host_metrics.free_bytes_for`，db_backup 改调真身）；ledger 地板与桶账三笔现算复录；auto-facts 重录。以下是你需要动手或拍板的部分。

## 一、亲密人腿上线（两步，约 3 分钟）

人腿代码已落地，但 `.env` 里**没有**私聊白名单键 ⇒ 现在整条人腿是关的。开启：

1. 用记事本打开 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\.env`（文件在 ChatBot 根目录，gitignore 内，别提交它）。
2. 在文件里 `BOT_CONTENT_ROUTE_GROUP_WHITELIST` 那一行的附近，另起两行照抄（把 `你的QQ号` 换成你的真实 QQ 号，JSON 数组形态、双引号，与群白名单同款）：
   ```
   BOT_CONTENT_ROUTE_PRIVATE_WHITELIST=["你的QQ号"]
   BOT_CONTENT_ROUTE_PRIVATE_BLACKLIST=[]
   ```
   含义：名单里的人在任何非群黑名单的群都能开亲密模式；黑名单留空＝暂不拉黑任何人。**名单为空数组时人腿保持关闭**（绝不会因空名单而放开，这是刻意设计）。
3. 保存（记事本默认 UTF-8 即可，不要另存为 ANSI）。
4. 重启 bot：只重启 bot.py 即可（SnowLuma 不用动）——管理员权限结束现有 bot 进程，然后照常启动 bot.py。
5. 验证（三条，缺一说明没生效回来说我）：
   - 你自己在**任意**没进群白名单的群里发「亲密模式 开」→ 应见到受理回执（这就是人腿的新能力）；
   - 换名单外的小号在同一群发同样的话 → 应不受理；
   - 原本就在群白名单里的群 → 行为与以前完全一样。
6. 想撤销某人：把他的号加进 `BOT_CONTENT_ROUTE_PRIVATE_BLACKLIST` 再重启（他原有群白名单放行不受影响——黑名单只关人腿）。

## 二、DB 备份腿（可选，不做也没影响）

七键已四面落齐，缺省 `BOT_DB_BACKUP_ENABLED=false`＝**现网行为零变化**。想开启每日保命备份：

1. `.env` 里加一行 `BOT_DB_BACKUP_ENABLED=true`（其余六键全部可留缺省：保留 7 份、单库上限 64 MiB、总量 4 GiB、剩余空间下限 20 GiB、24 小时过期）。
2. 重启 bot（同上）。备份区会出现在 `ChatBot_Runtime` 旁边的 `backups\sqlite\`（仓库外）。
3. 用超管在群里发 `/bot db-backup status` 一类的命令面（`runtime_admin` 的 DB 备份命令族）即可看到体检报告；覆盖/还原永远需要你人工执行，bot 绝不自动写回生产库。

## 三、待你拍板的四题（回一个词即可）

1. **tts_refs（人格音色引用字段）**：现状＝H-3 在册裁定"只声明未接线"。回复「**接**」＝排一批接线（动 tts.py 接线点＋三把锁＋音色素材批，工程量较大）；回复「**撤**」＝撤字段（动 persona_profile 两处＋两枚 registry json＋三把锁，较小）。不回复就维持现状（锁是绿的，不是坏账）。
2. **触发词债余 8 枚**（锁红：在册 467 < 现算 475）：两个闭法——「**登记**」＝把 8 枚补进在册名册（但该测试件是今天 14:10 另一会话的热写面，建议由那个 owner 波做或你明确授权我动）；「**撤词**」＝把 8 个触发词从帮助面撤掉（动 echo.py，同样是他会话面）。不拍板就维持红（诚实账）。
3. **`.zcodeignore`**（今天 14:55 出现的 ZCode 工具配置，内容＝.gitignore 同步＋工具默认排除段，无有害条目）：提交归档（进批 E）还是保持本地不入库？提交清单时你顺手定即可。
4. **`half-done/test_db_backup.py.HALF-WRITTEN` 残件**：正式测试件已重写（28 腿全绿），残件按"只准移不准删"规矩留着。回复「**清**」我就在下窗把它移入 ChatBot_Archive 归档；不回复就留档。

## 四、不用你管的（已闭）

ledger 六红（七键入册后的三笔基线复录：字面桶 43→48、总账 101→106、字段地板 784→791，判据与容差一字未动）；gate2 两红（db_backup 改调 `host_metrics.free_bytes_for` 真身薄口，零放宽）；相关门族 86+38 passed；doc_sync/verify_hashes 零漂。
