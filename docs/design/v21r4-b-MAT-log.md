MAT | B1 | 00:04:22 开工：已领 B1，独占写 backend-v2-acceptance-matrix.md
MAT | B1 | 00:23:19 断点1：四份必读已读完；矩阵未被 verify_hashes/doc_sync 锁定（grep 零命中）可安全编辑；not_wired 处置按任务简报=草案选项①收编词表；L61 草案表有值但未列入规则2清单→按草案表值落定并记录；开始执行词表行(L7)+批注行+65行三段替换
MAT | B1 | 00:26:40 断点2：词表行+批注行+表段A(L13-L32)+表段B(L33-L55) 已写入；剩表段C(L56-L77)→校验(grep已生效/行数/四列空缺)→ruff→对照表日志

---

## B1 交付记录（2026-09-18 MAT 席）

### 一、落定方法
- 数据源：`docs/design/v21r2-matrix-backfill-draft.md` §〇 十一条规则 + §一 65 行表（唯一数据源）。
- not_wired 词表处置=任务简报裁定（草案选项①）：矩阵 L7 词表 production_wiring 扩为 unknown/partial/wired/not_wired，定义「not_wired=代码已实现但无生产调用点，重启+实跑证据前不升 wired；禁写成 wired、禁去掉括注写成裸 partial」。
- 合入形态：矩阵表结构不变（9 列，未加列，L7「confidence 另存」口径不变）。原坐标指针仍属实的保留；增量以「v21r2 增量=/现值保持=」前缀并入 implementation 列；confidence+证据指针统一以 `〔v21r2 conf=X；证：…〕` 附于 live 列行尾。L40「RRF 无」、L48「ASR 无」两处证伪括注删除并留痕。

### 二、草案 vs 矩阵 逐行对照表（值=impl/wiring/offline/live/conf，✓=程序化比对一致）
| 行 | 草案值（impl/wiring/offline/live/conf） | 判定 | 落定注记 |
|---|---|---|---|
| L13 | partial/unknown/unknown/unknown/high | ✓ | 清单外（conf=high 有增量），按草案§一表落定；变更归属增量并入 |
| L14 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持+supervisor 域迁移注记 |
| L15 | partial/unknown/unknown/unknown/unknown | ✓ | 同上 |
| L16 | partial/unknown/unknown/unknown/high | ✓ | 清单外，按草案表；import 探针先例并入 |
| L17 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持（s9 只读复用注记） |
| L18 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L19 | partial/unknown/unknown/unknown/unknown | ✓ | feature_catalog/gate 迁移注记 |
| L20 | partial/unknown/unknown/unknown/unknown | ✓ | 执行门仍未接注记 |
| L21 | partial/unknown/unknown/unknown/verified | ✓ | 人工落定行：消费方增量，用草案值（wiring 括注台账#3 取舍） |
| L22 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L23 | partial/partial/unknown/unknown/verified | ✓ | 人工落定行：+13 LLM+8 占卜端点；wiring=partial（REST 挂接+键未配未部署） |
| L24 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L25 | partial/unknown/unknown/unknown/unknown | ✓ | 仅指标无治理未动 |
| L26 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L27 | partial/unknown/unknown/unknown/verified | ✓ | 人工落定行：两新消费方 |
| L28 | partial/unknown/unknown/unknown/verified | ✓ | 人工落定行：trace_id 增量；无生产写入方保持 |
| L29 | partial/unknown/unknown/unknown/unknown | ✓ | S14 计划面勿回填注记保留 |
| L30 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L31 | partial/unknown/unknown/unknown/unknown | ✓ | ledger 面零红注记 |
| L32 | partial/unknown/unknown/blocked/high | ✓ | 清单外（conf=high），按草案表；creation 契约字段落盘并入 |
| L33 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L34 | partial/partial/passed/unknown/verified | ✓ | 规则2直接覆盖；OutboundSideEffectExecutor 阶段1 |
| L35 | partial/partial/passed/unknown/verified | ✓ | 直连点收编 |
| L36 | partial/partial/passed/unknown/verified | ✓ | retcode=1200 挂起语义 |
| L37 | partial/unknown/unknown/unknown/verified | ✓ | 清单外（conf=verified 有增量），按草案表；字素切分无仍缺保持 |
| L38 | implemented/partial/passed/unknown/verified | ✓ | WIRE 在盘不得记 wired 括注保留 |
| L39 | implemented/not_wired/passed/unknown/verified | ✓ | build_worldbook_service 零接线 |
| L40 | implemented/not_wired/passed/unknown/verified | ✓ | 「RRF 无」证伪括注删除+留痕；存量已有三通道 RRF |
| L41 | implemented/not_wired/passed/unknown/verified | ✓ | 前提冲突（独立新库 vs 同源同库）注记保留在证列 |
| L42 | implemented/not_wired/passed/unknown/verified | ✓ | unknown→implemented；未对生产库实查注记 |
| L43 | implemented/not_wired/passed/unknown/verified | ✓ | unknown→implemented |
| L44 | partial/partial/passed/unknown/verified | ✓ | 人工落定行：保持 partial 勿升 implemented（s9 §三） |
| L45 | implemented/partial/passed/unknown/verified | ✓ | R7 复核+探针 |
| L46 | partial/not_wired/passed/blocked/verified | ✓ | 人工落定（草案表值）：503 not_wired 诚实位 |
| L47 | partial/not_wired/passed/unknown/verified | ✓ | OCR=VLM 代位 degraded |
| L48 | partial/not_wired/passed/unknown/verified | ✓ | 「ASR 无」证伪括注删除+留痕；transcribe.py/build_asr_provider 在盘；wiring「同上」展开=同 L47 |
| L49 | partial/not_wired/passed/unknown/verified | ✓ | pypdf 环境注记 |
| L50 | partial/not_wired/passed/unknown/verified | ✓ | 域内侧限定 |
| L51 | partial/not_wired/passed/blocked/verified | ✓ | 人工落定行：草案折中值 partial+live blocked；wpa1 §5 分歧括注保留、终裁留用户 |
| L52 | partial/not_wired/passed/blocked/verified | ✓ | 人工落定行：同 L51 折中+分歧注记 |
| L53 | partial/not_wired/passed/unknown/verified | ✓ | ACG 竖源三源非九源本体注记 |
| L54 | partial/not_wired/passed/unknown/verified | ✓ | rebinding 无证据保持 |
| L55 | partial/partial/passed/unknown/verified | ✓ | HTTPS 授时兜底链增量 |
| L56 | implemented/not_wired/passed/unknown/verified | ✓ | unknown→implemented |
| L57 | implemented/not_wired/passed/unknown/verified | ✓ | wiring「同上」展开=同 L56 |
| L58 | implemented/not_wired/passed/unknown/verified | ✓ | 存量 reminders.py 并行未切注记 |
| L59 | implemented/partial/passed/unknown/verified | ✓ | 措辞规范化：草案「重启生效」→矩阵「待重启生效」 |
| L60 | unknown/unknown/unknown/unknown/unknown | ✓ | 整行维持 unknown（债登记） |
| L61 | partial/partial/unknown/unknown/verified | ✓ | 清单外（草案§一表给值+conf=verified），按草案表落定并在此声明 |
| L62 | partial/partial/passed/unknown/verified | ✓ | 防环/回归锁增量 |
| L63 | partial/partial/passed/unknown/verified | ✓ | TG reaction 无触发点诚实保持 |
| L64 | implemented/partial/passed/unknown/verified | ✓ | REST 挂接+生产键未配未部署 |
| L65 | implemented/partial/passed/unknown/verified | ✓ | 同 L64+解释端口待接线（见偏差②：handoff 18 行口径差异） |
| L66 | implemented/partial/passed/unknown/verified | ✓ | bazi 同源断言 |
| L67 | partial/partial/unknown/unknown/verified | ✓ | 人工落定行：组织面完成、行级验收未动；conf 限「重组零回归」 |
| L68 | partial/unknown/unknown/unknown/high | ✓ | 清单外（conf=high），按草案表 |
| L69 | partial/partial/passed/unknown/verified | ✓ | R2 六项+R8 兜底 |
| L70 | partial/unknown/unknown/unknown/unknown | ✓ | conf=unknown→四列值维持现值（§〇.4），仅并入计划面勿回填注记 |
| L71 | unknown/unknown/unknown/unknown/unknown | ✓ | 整行维持 unknown；B3 立项（CHARTER 席并行，不在本席范围） |
| L72 | partial/unknown/unknown/unknown/unknown | ✓ | 同 L70 口径 |
| L73 | partial/unknown/unknown/unknown/unknown | ✓ | 现值保持 |
| L74 | unknown/unknown/unknown/unknown/unknown | ✓ | 整行维持 unknown |
| L75 | partial/unknown/unknown/not_applicable/verified | ✓ | 人工落定行：纯文档规格 live=not_applicable |
| L76 | partial/unknown/unknown/unknown/high | ✓ | 人工落定行：全量门禁未跑如实注记 |
| L77 | unknown/unknown/unknown/unknown/unknown | ✓ | 整行维持 unknown |

### 三、偏差与口径声明（5 条）
1. 清单外落定行：L13/L16/L32/L37/L61/L68 未列入草案§〇.2「可直接覆盖」清单，但§一表给出带证据的明确值（conf=verified/high）→ 按草案§一表落定；L70/L72 conf=unknown → 四列值维持现值、仅并入「计划面勿回填」注记（符合§〇.4）。
2. **HANDOFF §1.3「not_wired=18 行含 L65」与草案冲突**：草案 L65 wiring=partial（控制面 REST 已挂接）、§四统计 not_wired=17。以草案表为准（唯一数据源）；L64/L65/L66 的 partial 来自控制面 REST 真装配，LLM 解释端口才是 not_wired 位。此计数口径差异留档待收口波核对。
3. 草案§四统计行「live unknown 61」按行级表实为 **60 unknown + 1 not_applicable（L75）**；矩阵按草案行级表落定。
4. 措辞规范化：草案「重启生效」→「待重启生效」（语义不变：重启后才生效，避免任何「已生效」形近表述）。
5. 草案「同上」引用（L48/L57 wiring）展开为显式指代「同 L47」「同 L56」。

### 四、交付验证（实跑证据）
- 命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 ChatBot_Runtime/venv/Scripts/python.exe %TEMP%/mat_verify_b1.py`（脚本=草案 65 行期望值硬编码 vs 矩阵实文件逐行解析比对）
- 输出：`65行逐行比对: 65/65 一致, 0 不一致`；EMPTY CELL 零触发（四列无空缺）。
- 统计（与草案§四吻合）：impl=partial 47/implemented 14/unknown 4；wiring=unknown 31/partial 17/not_wired 17；offline=unknown 34/passed 31（全部限定面）；live=unknown 60/blocked 4/not_applicable 1/passed 0；conf=verified 39/high 5/unknown 21。
- `grep -n "已生效" docs/design/backend-v2-acceptance-matrix.md` → 零命中（exit 1）；「已上线」零命中。
- `python -m ruff check .` → `All checks passed!`（exit 0）。
- 改动面：仅 `docs/design/backend-v2-acceptance-matrix.md`（独占写）+ 本日志 + `v21r4-b-coordination.md` 登记。零 git 写操作、零代码改动、前端域（theme_tokens/render_hashes/domains/render/card_render）零触碰、未派子代理、无真实 LLM/发送/重启。

### 五、B1 完成判定
65 行四列无空缺 ✓；禁语零命中 ✓；逐行对照表可复核（本文件§二+§四脚本）✓；ruff 全绿 ✓ → **B1 交付完成（纯文档；全批仍未 commit/未重启/未部署，矩阵内所有值均为代码面证据，不含任何生产行为生效主张）**。
