# W5 · 本地路径域门收尾（媒体腿）——落袋 + 正门接线方案 + 残余记账

席：W5（实施席）。日期：2026-10-01（UTC 08:30 起算）。独占面：
`domains/media/ingest/vision_describe.py`、`domains/media/registry/vision_caption_cache.py`、
`domains/media/ingest/video_understanding.py`、`domains/media/ingest/transcribe.py`、
`domains/media/video/video_pipeline.py`、`domains/media/path_gate.py` + 对应 tests。
禁碰面照简报：`render_backends.py`/`downloader.py`/`eat.py`（W4）、`policy/*`、`plain_text.py`、`domains/meme/**`。

零 git 写、零配置改动、零进程操作、零真实外发。本件只登记，不部署（代码待用户重启才生效，台账 #10）。

---

## 一、本席四件处置（判据真身在哪）

| # | 处置 | 落点（真身） |
|---|---|---|
| 1 | 摘 `# noqa: BLE001` 冗余指令（RUF100 实报的 4 枚：`vision_describe` 三枚随第 2 件迁入 `path_gate` 时消形、`transcribe` 一枚就地摘） | `ruff check plugins/.../domains/media/` ⇒ All checks passed（读数见本波报告） |
| 2 | 「哪些目录算合法」收成**一处**：`%TEMP%` 暂存根 + 协议端 `nt_data` 锚 + 正门 `readable_roots` 三段合成，全部只住 `path_gate.py` | `domains/media/path_gate.py::media_read_roots` / `media_temp_root` / `protocol_media_anchor` / `registered_read_roots` / `forbidden_roster_refused` |
| 3 | 第二把裸尺 `Path(path).is_file()` 收敛：档案腿的「还能不能用」＝带门判据的布尔投影 | `domains/media/video/video_pipeline.py::_local_file_usable` |
| 4 | ffmpeg 直喂腿改按**判定折算后的真身**下发（上一波「按原串下发」那句自陈销账） | `vision_describe.py::_local_media_execution_source`（抽帧腿 `_extract_video_frames`、音轨腿 `video_understanding._extract_audio_clip` 两腿同形） |

`_local_media_source_allowed()` 保留，但改成 `_local_media_execution_source()` 的**布尔投影**——
「只问放不放行」与「要下发」共用同一枚判据，不许两说（旧在册锁 `test_video_ingest_ssrf_entry`
的 http 腿口径零改动）。

行号（2026-10-01 本波落笔后现算，会随后续改动漂移 ⇒ 以函数名为准）：

| 件 | 关键行 |
|---|---|
| `domains/media/path_gate.py` | `PROTOCOL_MEDIA_ANCHOR_NAME`:230／`media_temp_root`:233／`_safety_paths_module`:244／`registered_read_roots`:265／`protocol_media_anchor`:279／`media_read_roots`:293／`forbidden_roster_refused`:319 |
| `domains/media/ingest/vision_describe.py` | `_local_path_from_value`:184（`contain_within`:219／`forbidden_roster_refused`:225／在场一问 `resolved.is_file()`:229）／`_local_media_execution_source`:236／`_local_media_source_allowed`:262／抽帧腿取执行形态:724 |
| `domains/media/ingest/video_understanding.py` | import 换名:35／音轨腿取执行形态:136、`:165` 的 `-i` 已吃折算串 |
| `domains/media/video/video_pipeline.py` | `_local_file_usable`:55（转调:69，裸 `Path().is_file()` 已消形） |
| `tests/test_vision_local_path_domain_gate.py` | `_is_file_sites`:294（AST 尺）／根名册单点格／裸尺清零格＋注毒自证格／判执同形格两腿／档案腿行为格 |
| `tests/test_video_ingest_ssrf_entry.py` | 两腿本地格改按折算真身断言；音轨内网格 docstring 登记 HEAD 基线红 |
| `tests/test_safety_exec_paths.py` | `ALLOWED_CONSUMERS` 第六枚：`media/ingest/vision_describe` ⇒ `media/path_gate`（随判据迁移） |
| `plugins/.../domains/media/ingest/transcribe.py` | 冗余抑制注释摘除位（转写失败那腿） |

### 判据链（现在只有一条）

```
入站串 → vision_describe._local_path_from_value      （唯一带门判据 def，形态四问）
            ├─ path_gate.contain_within              （容器归属：折算后段元组前缀）
            │     └─ path_gate.media_read_roots      （唯一根名册：正门 ∪ 声明根 ∪ 锚点派生）
            ├─ path_gate.forbidden_roster_refused    （禁触名册：safety_exec.check_sendable 两枚判据）
            └─ resolved.is_file()                    （在场，只此一形，AST 锁钉死枚数=1）
消费侧（transcribe / video_understanding / video_pipeline / vision_caption_cache）一律转调，零判据。
```

---

## 二、两枚新根并入正门的接线方案（**未动 `safety_exec/paths.py` 本体**，该件归别席）

现状：`media_read_roots()` 合成的三段里，第 ① 段是真读正门（`default_policy().readable_roots`），
第 ②③ 段是媒体侧**声明式**附加根。名册已单点（锁 `test_root_roster_lives_in_exactly_one_file`
按 AST 认「值恰为锚点目录名的常量」与 `tempfile.gettempdir()` 调用，两处都只准 `path_gate.py`），
但**位置**仍在 media 域，不在正门。真并入正门要动的三面（缺一不可，只动一面必红另一面）：

1. `domains/core/safety_exec/paths.py`
   - 暂存根：在 `build_policy()` 里按 `tempfile.gettempdir()` 追加一枚
     `("hosttemp", temp_root)` 可读根（**不要**进 `_OWNER_RULING_READABLE_ROOTS`——
     那张表按该文件注释是「所有者裁定根、唯一初始条目」，宿主暂存根不属于它，混进去
     会把裁定面变成随手加根的口子）。
   - 协议端锚：`nt_data` **不适合**当静态登记根——它的位置随 QQ 账号目录而变，
     按目录名放行是本波刻意保留的窄腿。并入正门时建议以
     `paths.protocol_media_anchor_of(resolved)` 这种「派生规则」形态入册（判定函数、
     不是根常量），并保留 `index > 0` 那条「根段自身不算」的约束。
2. `tests/test_safety_exec_paths.py`
   - `test_default_policy_roots_are_derived_from_runtime_paths` 里
     `len(paths._OWNER_RULING_READABLE_ROOTS) == 1` 与 corpus 逐字符那两格：
     暂存根走 `build_policy` 那一腿 ⇒ 该格**不该**被改动；若改后它红，说明接错了表。
   - `ALLOWED_CONSUMERS`：本席已把第六枚登记对象从 `media/ingest/vision_describe`
     换成 `media/path_gate`（判据那一问随名册一起迁入真身，消费侧不再有 import）。
     若第 1 步把暂存根并入正门，`path_gate` 仍需在册（它继续问 `check_sendable`）。
3. `domains/media/path_gate.py`
   - 并入后 `registered_read_roots()` 会自动带上新根，届时删掉
     `_MEDIA_DECLARED_ROOTS` 里 `"media_temp"` 一项与 `media_read_roots` 的锚点派生段，
     `media_temp_root`/`protocol_media_anchor` 迁进正门；本件只留 `contain_within` 本体。
   - 同步翻转的锁：`test_root_roster_lives_in_exactly_one_file` 的三处期望值
     从 `path_gate.py` 改成 `safety_exec/paths.py`（**同一批**改，别只改代码——
     只改代码会让那格红，只改锁会把真身漂成无人登记）。

**裁定归属**：这一步动的是正门与「哪些目录算合法」的口径，属所有者裁定面 ⇒ 本席不擅自落，
等用户/主代理点头再动（台账 #68★「幽灵字段补齐＝三面齐」同源教训：只补一面必红另一面）。

---

## 三、残余记账（**别当已封死**）

1. 🔴 **锚点按目录名放行**：任何盘上任何一枚名为 `nt_data` 的目录，其内容都是
   **可读且可外传**面（`_protocol_media_root` 旧形 ⇒ 现 `path_gate.protocol_media_anchor`，
   判据不变：`index > 0` + 折算后段名 casefold 相等）。真机取证：本机 `…\nt_qq\nt_data`
   三枚（QQ 账号目录），**不存在**该名的私人目录 ⇒ 现实面=协议端落盘。
   活性锁：`tests/test_vision_local_path_domain_gate.py::test_protocol_adapter_media_leg_still_reads`
   （夹具把那枚锚放在假 `Documents/Tencent Files/<号>/nt_qq/nt_data/…` 下 ⇒ 这一格本身就
   是「按名放行」的实况证据），以及 `test_directory_above_the_anchor_is_refused` /
   `test_protocol_anchor_is_not_a_wide_root` / `test_junction_named_like_the_anchor_does_not_widen_the_root`。
   收紧方案（二选一，须裁定）：① 把协议端**绝对根**写进正门名册；② 撤锚、协议端媒体改由
   摄取层先搬进 `media_archive` 再判（会动 record/video 段的入站契约，docs/snowluma-setup.md §6）。
2. **HEAD 基线在册红（本席不签「已修」）**：
   `tests/test_video_ingest_ssrf_entry.py::test_audio_clip_rejects_internal_url_before_ffmpeg`
   红，根因＝`video_understanding._SSRF_PRECHECK_WELDED_OFF = False`（2026-09-27 席位
   S-ATKFIX-SSRF2 依用户裁定「先登记不堵」焊死关闭）。翻它属裁定面、不属本波收尾面 ⇒
   保持红并在此点名。抽帧腿那一侧的入口咽喉仍在工作（对应用例绿）。
3. **第二把裸尺在本波域外仍有**（不在 W5 独占面，未动）：
   `domains/media/capabilities/tts.py:317`、`domains/media/ingest/telegram_media.py:369`
   仍是 `Path(x).is_file()` 形态，`capabilities/media_archive.py:193` 是同族在场判定。
   本波的 AST 禁词格只覆盖简报点名的五枚件（`CONSUMERS` + `vision_describe` + `path_gate`），
   对域外不宣称已收。要收得连 owner 席位一起动。
4. **连接级残余不变**：ffmpeg 自带网络栈跟随的重定向落点仍不复查（与 yt-dlp F-5 / F-8 同族，
   登记不堵）；本波只保证「不下发未过门的地址、下发的是折算真身」。
5. `is_within_registered()` 仍是**不抛异常**版判定（随机图那侧在用），它不接根名册、
   只收调用方给的 `roots`——收紧名册时别忘了它那一支（randpic 现由 meme 席在改，
   `tests/test_media_path_gate.py::test_single_containment_judgement_site` 因
   `domains/meme/capabilities/randpic.py` 里的 `is_relative_to` 在 HEAD 轴就红，非本席所造）。

---

## 四、需 W4 在 http_util / downloader 侧配合的接线点（本席不改那两侧）

1. **私有名跨件引用**：`vision_describe._guarded_image_opener()` 现在
   `from domains.link_parse.parsers.http_util import _GuardedShortLinkRedirectHandler`
   （带下划线的私有名），notes 那侧同族。请 W4 在 `http_util` 落一枚**公开别名/工厂**
   （如 `build_guarded_opener()`），媒体与 notes 两消费点改指公开名 ⇒ 私有名重排不再静默炸图。
   改名/加别名前请先落别名再迁调用（两批），否则本波域锁会红。
2. **拒绝与瞬时失败必须仍可分**：`_download_image_bytes` / `prepare_vision_image_urls`
   依赖 `RejectedUrlError`（入口咽喉）与 `ParseHttpError`（逐跳落点）**原样上抛**、
   且「明确拒绝＝丢图不回透、瞬时失败＝保留原 URL」这一口径（审查 F-2）。
   W4 若把咽喉返回值改成 bool/异常合并，本侧的诚实失败分类会一起塌 ⇒ 请保留异常族。
3. **`check_download_url` 的同一条形**：抽帧腿/音轨腿在把 http 源交给 ffmpeg 前问它一次，
   本地腿**不问**（路径门归路径门）。若 W4 把 `downloader` 的判定改成「取字节后再判落点」，
   请同步通知本席把 `_extract_audio_clip` 那枚焊死开关按裁定翻开（见第三节 2）。
4. 可选合流：`downloader` 落盘暂存根的在场判定若能转调 `path_gate.contain_within`
   （现 `tts.py`/`telegram_media.py` 仍持裸尺，见第三节 3），名册就真正只剩一处——
   但那两侧归 W4，本席只登记不代改。

---

## 五、验证（读数在报告里，本件只记命令）

**归属反证**（台账 #68★ 正道）：`git archive HEAD` 抽到仓库外同尺复跑，按**节点 ID** 分桶比对
⇒ 本波域**净新增红 0**。两把读数（同名同集合）：

| 尺 | 工作树 | 净身 HEAD 树 |
|---|---|---|
| 简报点名的高危树扫门 18 件 | 6 failed / 416 passed | **同 6 枚节点 ID** / 416 passed |
| 台账 #70 媒体守门波七格 + 本席两件 | 2 failed / 219 passed | 同 2 枚（randpic 那枚 + 音轨焊死那枚） |

两把红点逐条：
1. `test_media_path_gate.py::test_single_containment_judgement_site`——`domains/meme/capabilities/randpic.py`
   里的 `is_relative_to`（meme 席在飞面，本席禁碰）；
2. `test_video_ingest_ssrf_entry.py::test_audio_clip_rejects_internal_url_before_ffmpeg`——
   `_SSRF_PRECHECK_WELDED_OFF=False`（第三节 2）。
其余 4 枚在 `test_capability_tag_orthogonality`（配置键→标签表，57≠58）、
`test_orchestration_callsite_single`/`test_orchestration_wiring_chat`（chat.py 与 mail_ingress 的
callsite 漂移）、`test_attack_surface_consumers`/`test_capability_manifest_gate` leg7/leg8——
**两棵树读数逐字相同**，全不在本席独占面。

**lint 那一格的坑（写给下一席）**：解释性注释里**不许出现** ``# noqa: BLE001`` 这种字面量——
ruff 会把它当**真指令**解析并报 `warning: Invalid # noqa directive`（本席第一版就踩了，
改成「不加抑制注释」的中文写法才干净）。摘除判据＝RUF100 本体，注释别替它复述。

```bash
# 本波域四道锁 + 台账 #70 媒体守门波七格
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_media_path_gate.py tests/test_notes_image_guard.py \
  tests/test_notes_image_leg_throat_fg4.py tests/test_media_archive.py \
  tests/test_media_registry.py tests/test_media_contract_v2.py \
  tests/test_media_digest.py tests/test_media_identity_single_source_ratchet.py \
  tests/test_safety_exec_paths.py tests/test_telegram_media.py \
  tests/test_vision_local_path_domain_gate.py tests/test_video_ingest_ssrf_entry.py \
  -q -p no:cacheprovider --basetemp="$TEMP/qoder-w5/bt"

# 消费侧回归（转调那四件的既有行为锁）
... -m pytest tests/test_asr_transcribe.py tests/test_video_understanding.py \
  tests/test_vision_caption_cache.py tests/test_vision_local_media.py \
  tests/test_vision_and_failover.py tests/test_video_progress_ack.py \
  tests/test_video_seam.py tests/test_vision_remote_data_url.py \
  tests/test_audio_ingest_ssrf_hop.py tests/test_vision_image_ssrf_hop.py \
  tests/test_subscription_vision.py tests/test_subscription_vision_guard_sub4.py \
  tests/test_content_video_auto_send.py -q -p no:cacheprovider --basetemp=...

# 全域引用面（47 件 tests/*，凡提到 media.ingest / path_gate / vision_caption_cache 的都算）
grep -rlE "vision_describe|video_pipeline|_extract_video_frames|transcribe|video_understanding|path_gate|vision_caption_cache|media.ingest" tests/*.py
#   ⇒ 842 passed / 7 failed / 1 skipped（7 枚＝上表两把里那 7 个节点 ID，净身轴同集合）

# lint（RUF100 摘除的核对尺）
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m ruff check --no-cache \
  plugins/bot_unified_runtime/domains/media/
# 全树 ruff 现算＝9 枚（channel_health 1／fx 1／error_report 5／randpic 与 group_recent_image 测试 2），
# 本席独占面 0 枚；改动前那 4 枚 RUF100（vision_describe 207/228/271 + transcribe 537）已清。

# 真机只读探针（合法腿照读 / 禁触与域外拒 / 执行形态＝判定形态；仓库外，不读字节不外发）
../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/qoder-w5/w5_real_leg_probe.py"
```

真机读数摘要（探针输出，`RESULT failures=0`）：`meme_library/*.jpg`、`cards/*.png`、`%TEMP%`
暂存件三枚合法腿 **read**；`.env`、`*.sqlite3`、`*.log`、`C:/Windows/win.ini`、
`C:/Windows/win.ini.`（尾点形）、`downloads/../../../.env`（穿越形）六枚 **refuse**；
协议端真件（`…\nt_qq\nt_data\…\0.png`，本机三枚账号目录之一）**read**，且
`path_gate.protocol_media_anchor()` 折出的锚点＝该 `nt_data` 目录本身、
锚点**父级**（`nt_qq` 那一格）落点 refuse。每次「read」那几枚同时断言
`_local_media_execution_source() == str(判定结果)`（判执同形，无 MISMATCH 行）。
