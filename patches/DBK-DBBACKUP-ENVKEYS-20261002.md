# DBK · db_backup 幽灵键第五面核查工单（2026-10-02 下午窗，核查席，只读）

席号 DBK。使命＝补查第五面 `.env`（NB4 已实证四面零登记）。全程只读，本工单为唯一写入物。**键值不抄**（`.env` 无键，无值可泄）。

## ① `.env` 在位表（第五面）

文件在位：27,991 字节，mtime 2026-10-02 04:00（实跑 `ls -l`）。

- `grep -c "^BOT_DB_BACKUP" .env` ＝ **0**（实跑）
- 宽松匹配任意位置 `DB_BACKUP` / `db_backup`（含注释行）＝ **0 行**（实跑）

| 键 | 在位否 | 值形态 |
|---|---|---|
| BOT_DB_BACKUP_ENABLED | 缺席 | — |
| BOT_DB_BACKUP_DIR | 缺席 | — |
| BOT_DB_BACKUP_KEEP_LAST | 缺席 | — |
| BOT_DB_BACKUP_SIZE_CEILING_BYTES | 缺席 | — |
| BOT_DB_BACKUP_MAX_FOOTPRINT_BYTES | 缺席 | — |
| BOT_DB_BACKUP_MIN_FREE_BYTES | 缺席 | — |
| BOT_DB_BACKUP_STALE_AFTER_HOURS | 缺席 | — |

## ② 七键真身与缺省（消费点全在 `plugins/bot_unified_runtime/domains/ops/db_backup.py` 的 `load_policy`）

| 键 | 消费点 file:line | 读取形态 | 缺省 | 约束 |
|---|---|---|---|---|
| `bot_db_backup_enabled` | db_backup.py:201 | getattr→None，再回落 `os.environ["BOT_DB_BACKUP_ENABLED"]`（:203） | None ⇒ **False** | 真值集 `{"1","true","yes","on"}`（:204） |
| `bot_db_backup_dir` | db_backup.py:208 | getattr 缺省 `""` | `""`（空） | str.strip() |
| `bot_db_backup_keep_last` | db_backup.py:209 | `_read_int`（:185-192） | 7 | clamp [1, 64] |
| `bot_db_backup_size_ceiling_bytes` | db_backup.py:210-213 | `_read_int` | 64 MiB | clamp [1024, 2 GiB] |
| `bot_db_backup_max_footprint_bytes` | db_backup.py:214-217 | `_read_int` | 4 GiB | clamp [1 MiB, 512 GiB] |
| `bot_db_backup_min_free_bytes` | db_backup.py:218-221 | `_read_int` | 20 GiB | clamp [0, 1 TiB] |
| `bot_db_backup_stale_after_hours` | db_backup.py:222-224 | `_read_int` | 24 | clamp [1, 720] |

`_read_int` 语义：`int(str(raw).strip())`，解析失败回落缺省，结果夹区间（db_backup.py:185-192）⇒ config 层字段用 `int` 类型即可，坏值在代码侧仍兜底。另读 `bot_timezone`（:205）与 `bot_runtime_data_dir`（:231），两键非本波范围、已有真身。

## ③ 死信判定

**无死信。第五面（`.env`）也干净——七键从未被人手写进生产配置，键从未暴露给生产配置。** NB4 四面零登记复核成立：config.py `grep -c bot_db_backup`＝0；runtime_paths.py / .env.example / config-catalog-full.md 零行（实跑）。五面合计＝零登记；功能能跑纯靠 getattr+缺省兜底，现网恒为 enabled=False 哑面（db_backup.py:198、:632 自证）。

## ④ 落四面需求表（主会话执行；本席不动手）

同批四面：`plugins/bot_unified_runtime/config.py`（Config 类七字段）＋ `scripts/settings.py` 热改态（台账 #68★幽灵字段三面齐，缺一面必红另一面）＋ `.env.example`（带注释样例；enabled 样例保持关闭＝现网哑面不变）＋ `docs/config-catalog-full.md`（七条目录项）。逐键需求＝②表：类型 bool×1 / str×1 / int×5；缺省一律取代码缺省（False / "" / 7 / 64MiB / 4GiB / 20GiB / 24）；消费点全部 db_backup.py:201-224。

⚠ 落批附注（诚实披露，非缺陷）：config.py 一旦落 `bot_db_backup_enabled: bool = False`，db_backup.py:203 的 env 直读腿只在字段为 None 时触发 ⇒ 恒短路，属预期语义收窄，批注里要点名，免得后人当 bug。

## ⑤ 未尽

- db_backup.py:180-181 自称"精确需求登记进 `patches/X1b-CONFIG-REQUEST.md`"——**该文件不存在**（实跑 `ls` 报 No such file or directory）。自称登记册缺席；落四面时以本工单④表为准，勿再找该文件。
- 本席受只读约束未跑测试：四面落地后需全量实跑测试树核对哑面缺省断言（`.env` 的 Runtime 根指向生产，测试卫生按规则 6）。
