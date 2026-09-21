# 人格上下文与称谓身份 · 人格源与运行副本一致性

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.persona-context · 人格源与运行副本一致性

- 层级：一级 B03 → 二级 persona-context → 三级 `persona-sync`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character`、`personas/shorekeeper`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

钉住「仓库里策展的人格源」与「生产实际读的人格副本」这两份文本**在同一次人工审阅
时刻是对齐的**。必须先说清它不做什么：它**不同步、不拷贝、不推导**——实测两侧逐行
精确重合率为零（副本是生产镜像、各自演化），所以逐字比对在结构上不可能成立，
硬做只会得到一条永远红或永远假绿的门。能机械成立的关系只有一句：
锚定 = 一次人工审阅的凭证，钉住（源快照 S，副本哈希 C）这一对。

## 怎么调用

- 门本体：`scripts/sync_persona_source.py`（只读校验）
  ——`python scripts/sync_persona_source.py`（默认 `--check`：绿/跳过退 0，红退 1）、
  `--check --require-copy`（部署机：副本缺失一律红）、
  `--check --allow-missing-copy`（维护窗口显式放行）、
  `--adopt --note "…人工审阅说明…"`（重录锚定，**v2 起 `--note` 必填**，
  杜绝「顺手 adopt 抹红」）。
- 编程接口：同文件 `check(copy, anchor)`（返回带 `status`/`message` 的结果，
  `is_red` 谓词）与 `adopt(copy, anchor, note=...)`；覆盖面清单
  `SOURCE_SNAPSHOT_FILES`，锚定文件 `scripts/persona_sync_anchor.json`。
- 常驻：由全量套件里的 `tests/test_persona_source_sync.py` 离线复现（假仓库根，
  全程不接触真 `personas/` 与 Runtime 副本），另有 `scripts/pre_restart_check.py`
  作为重启前人工检查项时以该脚本自身清单为准。
- 消费方：生产人格正文由 `BOT_PERSONA_FILES` 指向 Runtime 副本，经
  `character/providers.py:build_character_context_provider` 加载；
  `personas/shorekeeper/knowledge/` 下的文件被知识/热词检索**直读同一份**，
  不存在副本分叉。

## 开关与参数

- 状态语义（只有这些，别自己发明新的）：
  红 = `DRIFT`（副本被单方面改）、`SOURCE_DRIFT`（**源侧演进**，2026-09-21 ISYNC 根治项）、
  `SOURCE_UNCOVERED_FILE`（新增源文件既不覆盖也不豁免）、
  `SOURCE_UNCOVERED_AT_ANCHOR`（覆盖集比锚定新，需一次性补锚）、
  `COPY_MISSING_DECLARED`（`.env` 显式声明了副本路径却不存在）、
  `COPY_UNREADABLE` / `ANCHOR_MISSING`；
  跳过（退 0）= `SKIP_COPY_MISSING`（仅当路径来自约定回退，即未部署 bot 的机器）。
- 豁免：源文件要排除得进 `SOURCE_EXCLUDED` 并写明理由，否则覆盖面自锁直接红。
- 人格侧相关键：`bot_persona_files`（生产唯一正文来源，空=不加载）、
  `bot_persona_versioned_injection`（缺省 False，见下）、`bot_persona_profile_id`/
  `bot_persona_display_name`/`bot_persona_version`/`bot_persona_alt_profiles`。

## 失败时看到什么

- 本门红**不产生任何聊天侧用户可见文案**：它是工程门禁，信号是退出码与一行判定文本，
  附带下一步指令（`ADOPT_CMD` 会直接给出可复制的 `--adopt --note` 命令）。
- 人格版本库注入路径（`bot_persona_versioned_injection=True` 才生效）的失败面是
  fail-open：灌库失败/版本库空/存储不可用一律 warn 一行并回退文件正文，
  消息链零阻塞；损坏数据由服务层隔离留证并自动回退最近完好版本，chat 侧不二次判断。
  **该开关缺省 False，即线上目前仍是文件正文路径，版本库属灰度未启。**
- 副本真缺失（未部署机器）会 SKIP，不会假装绿；但 `.env` 明确声明了路径而文件不在，
  是 `COPY_MISSING_DECLARED` 红——这条区分就是为了让「没部署」和「丢文件」不混。

## 测试与验收

`tests/test_persona_source_sync.py`：改源必红（`SOURCE_DRIFT`）、红持续到补锚为止、
CLI 退出码、覆盖面自锁（新增文件未豁免必红）、注毒自证（把源侧判定改回信息性会红）。
真机/本机：`python scripts/sync_persona_source.py --check` 退出码 0 才算人格面就绪；
改完 `personas/` 想上生产，必须人工核对 Runtime 副本并按凭证语义 `--adopt --note`。
铁律提醒：人格文本改了不重启不生效（缺省读的是启动期快照）。
