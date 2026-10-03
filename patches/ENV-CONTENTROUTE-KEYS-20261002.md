# 工单 · ENV 内容路由四名单键核验（席 ENV · 2026-10-02 下午窗 · 只读核验席）

使命＝核验 `.env` 四枚 `BOT_CONTENT_ROUTE_*` 名单键在位性与装配形态，为亲密人腿生效判定供证。方法＝grep（值打码）＋ Runtime venv python 走 `smoke.load_smoke_config()` 实算（`PYTHONDONTWRITEBYTECODE=1`、`BOT_AUTOSYNC=0`；输出零值化）。全程只读，本工单为唯一写产物。**值与 ID 一律不入册**（AGENTS 规则 3）。

## ① 在位表（raw `.env`）

| 键 | 在位 | 行号 | 值形态 | 前导/尾随空白 | 同键重复行 |
|---|---|---|---|---|---|
| `BOT_CONTENT_ROUTE_GROUP_WHITELIST` | 是 | 231 | JSON 数组串 | 无 / 无 | 0 |
| `BOT_CONTENT_ROUTE_GROUP_BLACKLIST` | 是 | 232 | JSON 数组串（空阵） | 无 / 无 | 0 |
| `BOT_CONTENT_ROUTE_PRIVATE_WHITELIST` | **否（缺席）** | — | — | — | — |
| `BOT_CONTENT_ROUTE_PRIVATE_BLACKLIST` | **否（缺席）** | — | — | — | — |

参照：`.env.example` L869/870/880/881 四键模板齐备；生产 `.env` 只落了群两面，私聊两面未写。无注释掉的残行（无 `# BOT_CONTENT_ROUTE_*` 形态干扰项）。

## ② 装配后形态（`load_smoke_config()` 实算，2026-10-02）

| 键（对应 Config 字段） | 装配类型 | JSON 解析 | 条目形态 |
|---|---|---|---|
| GROUP_WHITELIST → `bot_content_route_group_whitelist` | `list[str]` | 成功 | 全 str；无空白项、无非串项、无空串项 |
| GROUP_BLACKLIST → `bot_content_route_group_blacklist` | `list[str]` | 成功（空阵） | — |
| PRIVATE_WHITELIST → `bot_content_route_private_whitelist` | `list[str]` | 键缺席 → pydantic 缺省 `[]` | — |
| PRIVATE_BLACKLIST → `bot_content_route_private_blacklist` | `list[str]` | 键缺席 → pydantic 缺省 `[]` | — |

解析口径（`domains/ops/smoke/smoke.py` M-68，生产同构）：非空值尝试 `json.loads`、失败/空回退原串；`list[str]` 字段吃裸逗号串会 `list_type` 崩（在册「两种口径」坑）。两枚在位键均为合法 JSON，**未踩坑**。

## ③ 计数

- 群白＝**非空，3 条**；群黑＝空，0 条；私白＝空（键缺席，缺省 0 条）；私黑＝空（键缺席，缺省 0 条）。

## ④ 结论

- **群面**：群白非空（3 条）＋群黑空 ⇒ 按简报判据「群白非空＝既有面不变」**成立**。
- **私面/人腿**：按简报判据「私白非空＝人腿开」⇒ 私白缺席为空 ⇒ **人腿不满足开启条件**；私黑同缺（空＝无排除项）。
- ⚠ **判据冲突待裁（前提缺陷，本席不代裁）**：`config.py` L1232–1235 在册语义为「私白**空＝私聊亲密面默认放开**（沿用既有私聊放开裁定）、非空＝仅名单内 QQ」——与简报「私白非空＝人腿开」**方向相反**。若人腿真以私白为总闸 ⇒ 现状未生效；若人腿沿用缺省放开语义 ⇒ 现状已开（无黑名单排除）。须由主会话对照人腿实现实际消费哪枚键后裁定，再定 `.env` 是否需补私白/私黑。

## ⑤ 未尽

1. 未核人腿实现代码实际读取哪枚键（本次只读核验四键在位性，超出授权范围）。
2. 两枚私聊键需**用户**向生产 `.env` 补写（本席禁改配置）；补后须重启 bot 生效（铁律＋台账 #10）。
3. 装配态为 smoke 同构路径实算，非 NoneBot 生产进程内存态；生产进程当前是否已带最新 `.env` 未验（零进程动作约束）。
4. 装配器 `load_smoke_config()` 有 `os.environ.setdefault` 副作用，仅作用于本核验进程内，无落盘。
