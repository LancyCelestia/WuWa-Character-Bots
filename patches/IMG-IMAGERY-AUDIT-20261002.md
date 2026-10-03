# IMG 席工单 · 意象族数读出取证 + voice.tts_refs 幽灵判定（2026-10-02 下午窗）

> 只读取证席。全程零 git 写、零进程动作、零配置改、`personas/**` 一字未动。
> 实跑环境：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0` + Runtime venv python。

## ① 三格取证

### 格 1：族数读出（交接档 §四 T1 ①）

**文件本体**：`personas/shorekeeper/imagery_families.txt`（在盘，未跟踪件已恢复）。直接数：**12 族**（第 14–25 行，每行 `族名｜取材提示`，12/12 全有提示，无重复）。

**读侧真身**：`plugins/bot_unified_runtime/domains/chat_reply/character/imagery_roster.py`
- `parse_roster_text`（:51-72）：解析唯一口径；**去重机制真身在册**＝`seen` 集合（:57、:68-70，撞名即丢）。
- `load_imagery_families`（:82-108）：默认根 `_repo_root()`＝包内绝对仓库根（:46-48）；读不到 ⇒ 空池不抛（:99-107）。

**现算读数（实跑，走默认真身根，不喂 root）**：
- `load_imagery_families('shorekeeper')` → **12 族，非空**（名单与文件逐条一致）。
- `parse_roster_text` 直喂真文件字节 → 12/12（原始非注释行 12 行，去重零损耗＝机制武装且未触发）。
- 轮换有牙现算：`choose_imagery_families(families, recent=[前2族], count=2)` → 返回**另两族**（避开窗口生效）。
- `danya` → 0 族（无册文件，诚实缺席口径）。

**在册锁实跑**：`tests/test_seat_t1_persona_contract_20261002.py` + `tests/test_seat_feat_persona_prof.py` 合跑 **23 passed**（verified）。
该锁判了什么：① 默认真身根读出非空 + 族名无重无空 + 提示齐（:131-145）＋缺席/读空注毒腿（:148-158）；② 恢复件与 `scripts/persona_sync_anchor.json` 审阅凭证逐字节相等（:184-193，锚只盖 `aliases.txt`+`imagery_families.txt` 两件）；③ 附属资产同一根 + 词表读侧与 cwd 无关 + 生产树零 `Path("personas")` 相对读（:238-299）；④ 意象派发按现役人格、在册无册不借别人家、占位档才回落（:306-330）；⑤ 三腿要么实装要么明写缺席（:412-419）；⑥ 自锁不抄族名（:445-454）。
**没判什么**：全程 `store=None, person_key=""`（离线纪律 :38-39）——真库上的用量账轮换（`recent_imagery_families` 写读闭环）不归它判，那在 `tests/test_reply_style_imagery_default.py` 的 mock store 腿。

### 格 2：voice.tts_refs（交接档 §四 T1 ②）

全命中清单：
| 处 | 性质 |
|---|---|
| `personas/registry/shorekeeper.json:18-19`、`danya.json:18-19` | `"tts_refs": []` + `_status:"只声明未接线（H-3）"`（声明，空值） |
| `character/persona_profile.py:29`（docstring H-3）、`:188`（字段）、`:318`（从 raw voice dict 解析入 record） | 声明＋装载，**非消费** |
| `tests/test_seat_feat_persona_prof.py:117-181` | 三把锁：生产树（plugins/+scripts/）`.tts_refs` 属性读恒 0（:139-146）、在册值必须空+未接线注记（:149-163）、注毒自证（:171）——**当前绿（本次实跑）** |
| `scripts/verify_chatbot_env.py:225` `check_tts_refs` | **同名不同物**：审的是 config 键 `bot_tts_ref_audios`（参考音频池），不读人格 record 的 tts_refs |
| `tests/test_seat_t1_persona_contract_20261002.py:350,363,368,389-391` | 契约三腿的 voice_tts 腿（读 registry dict，非 record 属性） |

**判定：非意外幽灵，是 H-3「只声明未接线」的在册裁定态**——零生产消费点且被三把锁钉死在 0。且 T1 锁 docstring（:23-29）已明写裁定：**"不是幽灵字段，撤不得也接不得；接线属另一批（下发腿在 TTS 能力面，音色真身目前只跟 `BOT_TTS_REF_AUDIOS` 这枚 config、不跟人格）"**。⇒ 交接档 §四 T1 ② 的"未闭"很可能是**账面滞后**：裁定已落锁、锁已绿。

**两案对照（不代裁）**：
- **接案**：下发腿消费点＝`domains/media/capabilities/tts.py:1029`（现读 `cfg.bot_tts_ref_audios`）——在此处加"现役人格 record.tts_refs 非空则优先"分支；须同批改三把 H-3 锁（`test_seat_feat_persona_prof.py:139/:149/:171`，锁语义从"恒 0"改"声明即许"）+ T1 契约腿（:389-391 `_leg_wired` voice 分支联动）；**且 registry 值现为空**——光接线零行为变化，逐人格参考音频属人格资产（规则 8），素材须用户定。代价：高（跨域 TTS 面 + 锁重写 + 素材批）。
- **撤案**：删 `persona_profile.py:188`（字段）+:318（解析行）+:29（docstring 行）；registry 两 json:18-19；`test_seat_feat_persona_prof.py` 三把锁；T1 锁 `PERSONA_LEGS`/`DECLARED_ABSENT` voice_tts 两格（:350,:363,:368）+ `_leg_wired` voice 分支（:389-391）。`verify_chatbot_env.py` 的 tts_refs finding 独立于人格字段、不受影响；字节锚不盖 registry json、不受影响。代价：中，但**推翻在册 H-3 前瞻声明**（TTS 按人格换音色这条路将来还得重新声明一遍），且动 `personas/registry/*.json` 属规则 8 敏感面、须用户授权。

### 格 3：台账 #66★ 边界核对

两条在册裁定在当前码面**均成立**：
1. **名册按现役人格读、config 只回落一层**：`reply_policy.py:725`（`families = load_imagery_families(active, root=root)`，`active`＝:724 的 persona_id）→ `:726` 守卫 `if not families and not _persona_is_registered(active):` → `:731` 才回落 `configured_profile`。现役人格来源链：`providers.py:738`（`ContextBundle.active_persona_id=persona_profile_id`，主格每轮现选）→ `capabilities/chat.py:6093`（传给 `reply_policy_section_for_turn`，调用点 :6077）；预览同构 `runtime/prompt_preview.py:268-273`。
2. **在册人格无意象册＝诚实缺席**：`reply_policy.py:732-733`（`if not families: return text`，只少意象行、策略正文不塌）；`imagery_roster.py:85-107`（读不到 ⇒ 空池不抛）。实证：danya 现读 0 族、派发不借守岸人名册（T1 锁 :316-323 绿）。

## ② 结论

- **族数：非空（12 族），去重有牙**——解析级 `seen` 去重在册武装（本次未触发＝零撞名），轮换级避开窗口现算生效；交接档 §四 T1 ① **可闭**（判据＝`test_seat_t1_persona_contract_20261002.py` ①②腿，本次实跑 23 passed）。
- **tts_refs：非失控幽灵，是 H-3 在册"只声明未接线"态**，三把锁钉死且绿。交接档 §四 T1 ② 建议改记为"已裁：接线属另一批（H-3），非本波事项"，除非主会话要推翻 H-3 开接线批或撤声明。

## ③ 不确定项

- 真库（生产 SQLite）上的用量账轮换未实证（离线纪律 store=None；#66★ 猴补规则禁实例化 shared_reply_policy_store）——"有牙"判据覆盖解析+选族纯函数与 mock store 腿，生产库写读闭环按 unknown 记。
- `recent_imagery_families` 窗口宽度常数的具体值未抄（`reply_policy.py:1535` 有注释，数值以真身为准，规则 10）。
- 接案的 TTS 面只到 `tts.py:1029` 消费点一线，未深读下发腿全链（engine_provider / reserved_provider 判定源是否需同批动，未取证）。

## ④ 建议

- **T1 ①（族数）**：主会话即可闭账，证据引本工单 + `tests/test_seat_t1_persona_contract_20261002.py` 实跑（23 passed，含 H-3 锁）。
- **T1 ②（tts_refs）**：按在册 H-3 裁定维持现状、交接档销项改记"已裁未接线"；若用户要接或撤，均须用户点名（接＝另一批 TTS 接线 + 素材批；撤＝动 `personas/registry/*.json` + 三把锁，规则 8 授权）。
- 无需新立任何锁：既有两把锁已全覆盖本次两格判据。

## ⑤ 未尽事项

- 主树还原事故（台账 #68）回潮面：imagery_families.txt 现为**未跟踪件**＋字节锚在册——若再遇外部 restore，锚与 T1 锁 ② 能判红，但恢复动作仍须人工（本席只读取证，未动）。
- 接线批若立项，TTS 面消费链（`tts.py:1029` 之后的选音逻辑）需先做一次只读取证补全本工单 ③ 的缺口。
