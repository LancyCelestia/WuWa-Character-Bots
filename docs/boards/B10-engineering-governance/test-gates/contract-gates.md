# 测试与机器门体系 · 渲染与出站契约门

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.test-gates · 渲染与出站契约门

- 层级：一级 B10 → 二级 test-gates → 三级 `contract-gates`
- 实现落点：`tests`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把已经写下来的**契约**翻译成断言。规范文档说「阴影只准引登记族」「出站只准走中央闸」「主动投递禁直调队列」，这些话对机器没有约束力；契约门就是让违例当场变红的那一层。判据是软的（可读的规范），门是硬的（跑不过就交不了）。

现役三族：

- **渲染契约族**：`tests/test_rendering_contract.py`（Jinja 模板逐条断言）、`tests/test_mica_builders_contract.py`（f-string 直拼的卡）、`tests/test_template_visual_audit.py`（数值与色值等值审计）、`tests/test_mica_shell.py`、`tests/test_error_card_contract.py`、`tests/test_brand_capsule_contract.py`。契约正文 = `docs/rendering-contract.md` + 单一事实来源 `theme_tokens.py`。
- **出站与投递契约族**：`tests/test_outbound_gate.py`（中央防风暴闸的规格反证 T1–T13；其 T6 直调族清单两次跟随口径变更——2026-09-22 WAVE42 群摘要 / 日常助理改道中央出口、2026-09-24 裁定 R-4 四枚主动投递族无条件走中央出口（根文件 `call_api` 直发分支整段删除，见台账 #49/#52），直调下限随之收紧为**零容忍方向的硬尺**；现役族数与清单以 `test_existing_families_still_submit_directly` 与 `tests/test_outbound_bypass_prohibition_gate.py` 的豁免表为准，本处不手写）、`tests/test_outbound_v21.py`、`tests/test_v21_wiredirect_unified_path.py`（存量族「只登记不迁移」结构锁的先例，该口径自 WAVE42 起对改道族放开、自 R-4 起对四枚主动投递族全面收口，见 `.superpowers/sdd/2026-09-21-unify-wave/decisions/WAVE42-active-push-central-exit.md`〔gitignore，仅本机〕与 `docs/HANDBOOK.md` §42）。
- **安全与边界契约族**：`tests/test_ssrf_throat_coverage.py`、`tests/test_credential_domain_binding_gate.py`、`tests/test_content_safety_v*.py`、`tests/test_copy_redline_gate.py`（文案红线）、`tests/test_voice_boundary_central_gate.py`（文本边界中央件）。

## 怎么调用

契约门就是 pytest 用例，随全量跑；定位单族：

```
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py -q -p no:cacheprovider --basetemp=$TEMP/cg
```

写契约门的三条硬规矩（都有先例）：

1. **枚举而非 glob**：`tests/test_rendering_contract.py` 显式列全部既有模板，禁止扫目录——新增模板必须登记进门，否则它会静默地「全绿但没人看」。清单的**数量**口径仍归机器册（`scripts/doc_sync.py` 用 glob 派生模板清单），两侧对不上即红，这正是互证。
2. **动态白名单派生自登记表**：登记族（如阴影族 `SHADOW_CSS_VARS`）的合法值由 `theme_tokens.py` 的登记表动态推出，不在测试里抄一份常量；族外自造值一票否决。抄一份就等于造了第二事实源。
3. **方向性锁**：降级方向要钉死。例：`test_gate_store_failure_fails_open` 要求「闸自身故障必须放行，不得变成丢消息」，同时挂出 degraded 事件；`test_gate_disabled_is_passthrough` 要求「关闸即字节级现状」——关而不止就是红。

## 开关与参数

契约门本身无开关、无配置键：它是交付门，不受 feature flag 影响。被测对象的开关（如出站闸的静默窗、每主体限额、`bot_*` 系列键）由各业务板块登记，本处只列一条治理口径：**契约锁的配置键缺省值改动必须与 `_conventions.md` 第五节一致**，不得借「更安全的保守默认值」私自把放开改回关闭，也不得反向。

例外要说清：`BOT_AUTOSYNC` 影响的是生成物而不是契约断言，两者不互相掩盖。

## 失败时看到什么

断言消息直接指向违例物：模板名 / 变量名 / 非法值 / 应引的登记族。渲染契约族最常见的两类红是「族外自造阴影或色值」与「新增模板未登记进门」；出站契约族最常见的是「新代码直调 `send_queue.submit` 绕过 `submit_active_push`」（AST/文本双扫的覆盖门点名文件）。

安全与文案红线族（`test_copy_redline_gate.py`）会拦具体字面量——历史上出现过它打到自家波次写的探针字面量的假红（属误伤，改探针样本、不改规则）。**判据**：红消息点名的文件与行是否属本波改动面；属则修代码，不属则改样本或登记归属，绝不删规则。

## 测试与验收

本入口的「测试的测试」：契约门一旦失去杀伤力必须被发现——用注毒自证（见 `mutation-testing.md`）与覆盖门（`tests/test_ssrf_throat_coverage.py`、`tests/test_credential_domain_binding_gate.py` 都带负样本，故意造一处「带凭证出站却不经咽喉」的形态，断言门必抓）。

真机验收指针：渲染类改动的重启后打点见 `docs/acceptance-manual.md` §6.6 族与 `docs/rendering-contract.md` 的验收节；出站类见 §6.6.12（紧急信息投递）。
