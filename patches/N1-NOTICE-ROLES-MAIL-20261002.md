# N1 · notice 幂等兜底键 + `"super"` 死判据 + 邮件四枚悬空 skip

> ⚠ **本件由主会话代记**：席 N1 在 150 轮到顶时中止（末句＝"Now the final A/B attribution
> run — same ruler on worktree and pristine HEAD."），**没交工单**。以下每一格都是主会话
> 自己读 `git diff` + 自己跑锁得到的，不是席的自述；席未完成的 A/B 复跑由主会话补。
> 日期＝2026-10-02。

## ① 三格现状与改法（主会话现算）

### 格一：`"super"` 死判据（`domains/chat_reply/character/reply_policy.py`）
diff 里那段注释与改后代码是本案核心，主会话复核为**两处都坏**：

- 旧腿 `"super" not in roles` **恒真** —— 六级角色真身是 `policy/roles.py` 的
  `user/trusted/enterprise/admin/super_admin/blocked`，字符串 `"super"` **不是任何真身角色名**。
- 同一表达式的另半腿 `str(sender_id).strip() in super_ids` 拿**裸 `sender_id`** 直接比 QQ 名单
  ⇒ 跨平台（TG/邮件/console 的 id 与 QQ 号）**相撞即冒名**。

改后＝`actor_is_super = ROLE_SUPER_ADMIN in roles`：判据只认中央角色真身，不再比裸 id。
本仓同型在册先例＝台账 #60★「禁读 `get_login_info` 认自身名」，同属"拿一个不稳定的字符串
当身份真身"这一类病。

### 格二：notice / 合成事件的幂等兜底键（`domains/chat_reply/runtime/event_idempotency.py`，+151 行）
落点在既有幂等件内，键段构造走 `is_legal_segment`（台账 #46★：键段禁 `:`）。
主会话复核方式＝跑该席新锁 `tests/test_notice_event_dedupe_fallback.py`（见 §2 读数），
未见到第二本去重账。

### 格三：邮件四枚悬空 skip（`domains/transport/mail/mail_adapter.py` + 两件测试）
**逐字符号清点（主会话 `git diff | grep -c` 现算，不采信任何自述）**：

- `^-.*pytest.skip|^-.*skip\(` 命中 **4** 行 ⇒ 四枚 dangling skip 全部撤除
- `^+.*pytest.skip|^+.*skip\(` 命中 **1** 行，且该行落在新增用例的 docstring 内
  （描述"原来那枚 skip"，不是新 skip）

⇒ 结论＝**四枚挂"待补真身"的 skip 换成了真身**，与台账 #69★ "挂着的 skip 不算覆盖"对上。

## ② 判据读数（主会话自己跑的，非席报）

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 python -m pytest -p no:cacheprovider \
  --basetemp=$TEMP/qoder-ver2/bt -q \
  tests/test_notice_event_dedupe_fallback.py \
  tests/test_reply_policy_super_target_platform_domain.py \
  tests/test_mail_adapter_resilience.py tests/test_mail_ingress_locks.py tests/test_sdd7_n4.py
→ 76 passed in 7.24s

PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 python -m pytest -p no:cacheprovider \
  --basetemp=$TEMP/qoder-n1/bt -q \
  tests/test_notice_event_dedupe_fallback.py \
  tests/test_reply_policy_super_target_platform_domain.py tests/test_reply_policy_permanent.py
→ 114 passed in 9.01s

ruff check（本件六面）→ All checks passed!
```

- `tests/test_reply_policy_permanent.py` 一起跑是为验**超管判据改动没把既有回复风格锁打红**（该件
  历史上被多席改过，是脆弱面）。
- `tests/test_mail_ingress_locks.py` 净减 176 行、净增 250 行：改写幅度大，故主会话按 §1 格三
  的符号清点单独验过"skip 只减不增"，不看它自述。

## ③ A/B 与净新增红（席没跑完，主会话补跑）
`git archive HEAD` 抽仓库外副本同尺复跑该三族：**基线本身即红**
（`test_mail_ingress_locks` 在 HEAD 副本上因旧 skip 形态与 `quirks.py` 语法错连带失败），
工作树侧本三族 76/114 全绿 ⇒ 判定＝**本波域净新增红 0**，按台账 #72★ **不签"全绿"**。

## ④ 未尽事项（交主会话排批）
1. `roles.py` 判据本体未动（本席按纪律只改调用侧）。若还要更多腿从"裸 id 比名单"迁到
   中央角色，需要一次全仓清点：`grep -rn "sender_id.*in .*_IDS\|in super_ids\|in admin_ids"`。
2. 平台域（同一自然人在 QQ/TG/邮件下的身份合并）真身在 `session_identity.py`，
   本席只堵住冒名判据，**没做**跨域身份合并策略——那是裁定面。
3. 超管名单是否要求带平台前缀（如 `QQ:123`）＝待用户裁；现网名单仍是裸号，
   判据改为只认中央角色后，裸号名单的效力面变小，重启后需观察一轮。
