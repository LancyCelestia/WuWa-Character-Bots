"""常驻门：git 已跟踪源硬编码凭据扫描尺（scripts/secret_scan_tracked.py）的四把锁。

席位 S100R（2026-09-24，代 S100 交卷）。设计口径全部以尺的真身为唯一来源：
清单口径 = ``git ls-files`` + ``is_in_scope``（禁在本文件复制第二份排除逻辑）。

四把锁
------
1. **回潮锁（去脆化形）** ``test_f1_findings_are_exactly_known_debt_roster``：
   今天全树的 F1 命中按 **(件, sha256[:16]) 计数** 与点名册**双向闭合**——行号【不进判据】、
   只作导航（他席在测试件上方加行即整体漂移，按行号钉死会造出「非新秘密」的假红，见 §点名册）。
   两条腿同时执法：①「回潮」＝树上出现册外 (件,指纹) 或某枚出现次数超过册值 ⇒ 当场红
   （新硬编码凭据、同值多印都拦得住，不靠行号）；②「反查·每枚仍在」＝册里点名了但今天
   树上扫不到 ⇒ 当场红（不许靠删册条目自我豁免，还债须与摘册同批）。白名单以自身指纹逐枚
   可反查，**绝不扩成「整件免检」**。
2. **棘轮锁** ``test_roster_never_grows``：点名册总出现次数只准降不准升（上限钉死为建账现值）。
   想加=先还债并经用户裁决；册里有而树上没有=被回潮锁第②条腿打死，两把锁互为闭合。
3. **反缩面地板** ``test_scan_surface_never_shrinks_below_floor``：
   ``git ls-files`` 口径可扫描件数低于地板即红——清单被人改短（比如把排除面放宽）
   时，本门与尺内 ``enforce_coverage`` 一起响，不许「少扫了还全绿」。
4. **注毒自证（全内存/临时目录，真树零写入）**：
   ① 种一枚高熵假凭据 ⇒ F1 必抓；② 同位写成 ``env:`` 引用 ⇒ 落 F2 不落 F1
   （证明 F1/F2 分流真的在工作，而不是判据写反）；③ 扫描件数缩到 1、地板高于 1
   ⇒ ``enforce_coverage`` 必抛。

⚠ 本文件自身禁止出现任何可被该尺扫到的凭据字面量形态（前缀键一律运行时拼接，
点名册只存 sha256[:16] 裸十六进制——它不匹配任何 F1 家族正则）。

锁①的豁免面（夹具级，不是第五把锁）
------------------------------------
``FIXTURE_FAKE_EXEMPTIONS``：测试夹具里**由该测试自己合成的假凭据**（形态落 F1、任何服务面上
都不存在、把它摘掉等于摘掉那条回归锁本身）一律**不进** ``F1_DEBT_ROSTER``。理由照实写：名册记的
是「tracked 源里硬编码真凭据」这笔**欠账**，欠账总出现次数被 ``ROSTER_CEILING``（33＝2026-10-04
登记后现值；建账原值 32，见常量处注）钉死只准降；把合成值塞进名册＝拿假债顶穿上限，唯一出路是抬
上限，而抬上限＝放宽判据，本门明令禁——例外只有一条：用户裁决点名登记（同处注记授权来源）。
夹具不是债，就按夹具处理：**逐枚 (件, 指纹) 豁免 + 写明它是哪条断言的料**。豁免同样**绝不扩成
「整件免检」**——同件里另一枚形态相同但值不同的凭据、或同一枚被多印，都照旧落回潮腿（两条牙见
``test_fixture_exemption_teeth_*``）；豁免条目在今天的树上扫不到也照红（不许留幽灵预豁免未来凭据，
与名册的 missing 腿同一条口径）。
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pytest

from scripts.secret_scan_tracked import (
    REPO_ROOT,
    CoverageError,
    Finding,
    enforce_coverage,
    f1_findings,
    f2_findings,
    fingerprint,
    scan_paths,
    scan_text,
    tracked_text_files,
)

# ------------------------------------------------------------------ 点名册（去脆化形）
# 判据按 (相对路径, sha256[:16]) -> (期望出现次数, 导航行号) 计数比对；行号【不进判据】、
# 只供人导航——他席在测试件上方加行会让整枚凭据的行号漂移，按行号钉死会造出「非新秘密」的假红。
#
# 改因（S205 去脆化方案，2026-09-24，本席 S209 落地）：
#   前值 = 三元组 (件, 行, 指纹) frozenset（字面 31 条 / 建账上限 32），锁①按三元组集合差判；
#   现算红证 = test_search_api_providers.py 六枚整体 +4（册 39/47/147/168/215/220 → 现
#   43/51/151/172/219/224，同指纹 06d8d5…）、test_outbound_gate.py 册 1 条 2074 → 现 2 条
#   2229/2411（同指纹 b50195…）——根因是行号漂移，非来了新密钥。
#   后值 = (件, 指纹) -> (次数, 导航行)：18 枚唯一 (件,指纹)、总出现 32；行号降为导航。
#   现算复核（date -u 2026-09-24T15:35Z，尺=scripts/secret_scan_tracked）：树上 (件,指纹)
#   唯一数 18 == 点名册 18，「册外新 (件,指纹)」集合 = 空 ⇒ 去脆化未把任何新凭据洗进白名单。
#   复跑：../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_secret_scan_tracked.py -p no:cacheprovider --basetemp=<私有唯一目录> -q
#
# 还债史（S139，RULINGS 第 12 项，保留）：原首条 scripts/configure_axonhub_registry.py（67 字符
# 网关凭据，sha256[:16]=c4f4497b2b308d04，提交 0234547 引入且脚本会反写 .env）已从文件中摘除、
# 脚本改只读并零命中拒写。按裁定「不改史」旧值仍在历史、轮替在她。该枚回潮由锁①「回潮」腿兜住：
# 删册后若树上再出此 (件,指纹)＝册外新债＝当场红。
#
# ⚠ test_outbound_gate.py 的 b50195… 命中是夹具里的裸 QQ 号（非密钥），以自身指纹逐枚点名、
#   可被判据反查——白名单机制该容纳此形态，但绝不扩成「整件免检」。
F1_DEBT_ROSTER: dict[tuple[str, str], tuple[int, tuple[int, ...]]] = {
    # (相对路径, sha256[:16])                            : (期望次数, 导航行号[非判据])
    # 2026-10-04 登记（用户简报点名、审计席逐条核过原文＝零真凭据）：scripts 件的
    # RUNTIME_WRITE_TOKEN 是 ``--authorize`` 闸的全大写连字确认短语（掩码 I-A**TE、len=23），
    # 名字含 token 才落 F1 赋值腿。该件不在 tests/ ⇒ 夹具豁免表形态门拒收，名册是唯一合规落点
    # （上限随之 32→33，见 ROSTER_CEILING 处注）。
    ("scripts/migrate_persona_isolation.py", "5750c01c28a72247"): (1, (79,)),
    ("tests/test_auditfix_parsers.py", "382f2b92346e5945"): (1, (120,)),
    ("tests/test_auditfix_parsers.py", "86939b09d8c07c28"): (2, (614, 622)),
    ("tests/test_auditfix_parsers.py", "c6ce0b1cf21984fa"): (1, (358,)),
    ("tests/test_config_control_service.py", "96eb739141230917"): (1, (588,)),
    ("tests/test_control_plane_events.py", "bae281b144b7e435"): (1, (101,)),
    ("tests/test_credential_domain_binding.py", "139d3c840c528e4b"): (1, (160,)),
    ("tests/test_credential_domain_binding.py", "f6d90a237b6a449e"): (1, (167,)),
    ("tests/test_event_service_v21.py", "1584ab5c55a42564"): (2, (185, 196)),
    ("tests/test_event_service_v21.py", "4318451bb9291580"): (1, (189,)),
    ("tests/test_mcp_server_spec_gate.py", "dd314f7768cac64c"): (1, (78,)),
    ("tests/test_memory_router_reuse.py", "67a750a0a1ce5568"): (1, (88,)),
    ("tests/test_outbound_gate.py", "b50195a0d6eca27e"): (2, (2229, 2411)),
    ("tests/test_parser_ssrf_guard.py", "f506a48b0b9b5c37"): (5, (451, 475, 495, 530, 546)),
    ("tests/test_sandbox_windows.py", "17bd62ad1f089c61"): (1, (63,)),
    ("tests/test_sdd9_n3re.py", "47059f721a364e9c"): (2, (319, 324)),
    ("tests/test_search_api_providers.py", "06d8d5a5d1794d05"): (6, (43, 51, 151, 172, 219, 224)),
    ("tests/test_twitter_subscription_graphql_v2.py", "a33bb8a347448762"): (2, (202, 651)),
    ("tests/test_v21_s9_llm_api.py", "ca86684ee63d2d4d"): (1, (57,)),
}

# 夹具级豁免（**不是欠账**）：形如 (相对路径, sha256[:16]) -> (豁免枚数, 逐枚理由)。
# 理由必须写清「它是哪条断言的料、为什么摘不得」——写不出＝它不是夹具，是真债，走还债流程。
# 本表按 (件, 指纹) 逐枚生效：同件另一枚凭据、同一枚被多印，都照样落回潮腿（见文件头
# 「锁①的豁免面」与 `test_fixture_exemption_teeth_*` 三条）；条目今天在树上扫不到＝幽灵预豁免，当场红。
FIXTURE_FAKE_EXEMPTIONS: dict[tuple[str, str], tuple[int, str]] = {
    ("tests/test_alert_plain_text.py", "b576db5ca548c08e"): (
        1,
        (
            "2026-09-29 席 BASECFG 现算归因：该件 `test_detail_cut_leaves_no_key_head` 的「先洗后截」回归料"
            "——padding 串与一枚 `sk-` 前缀合成键（掩码形态 `sk-********89`、len=24）拼进 `safe_summary`，"
            "断言的是打码必须排在截断**之前**、截口不许把密钥头部留在出站文本上。值是当场硬写的假值，不存在于"
            "任何服务面；摘掉它＝拆掉这条回归锁本身（换成别的形态就验不到同一件事）。取证：该件对 HEAD 的 diff"
            "里这一行是**新增**（HEAD 无此串）⇒ 属他席在飞件的夹具，不是历史欠账。按名册口径它不进"
            "「tracked 源里硬编码真凭据」那笔债 ⇒ 不进 F1_DEBT_ROSTER、不动 ROSTER_CEILING。"
        ),
    ),
    ("tests/test_atk_llm3_channel_health.py", "439209996799d6ac"): (
        2,
        (
            "2026-10-04 审计确认夹具假值：`test_record_failure_redacts_various_secret_shapes` 的"
            "打码回归料——合成 ``sk-`` 形 bearer 假值（掩码 ``sk-a**89``）喂进 ``record_failure``"
            "（:42），:44 反断言原文不得进存储。两处同值＝同一条锁的喂料加反断言。合成串、任何服务面"
            "不存在；摘掉＝拆掉该打码锁本身（换形态就验不到同一件事）。"
        ),
    ),
    ("tests/test_atkfix_tgmail_failure_reasons.py", "3a10fc1822801ce9"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：模块常量 ``_STRADDLE``（44 个 x 后接 ``sk-`` 词根，令密钥"
            "连段骑跨截断窗口）是 `test_final_error_truncated_secret_fragment_never_reaches_issue`"
            " 的边界回归料，断言残段形态不得进 kind/safe_summary。合成串、服务面不存在；摘掉＝该"
            "「先截后洗」边界锁验不到同一件事。"
        ),
    ),
    ("tests/test_connect_phase_retry.py", "7152ffc9d2ee83fc"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：`test_nonebot_exception_message_text_never_enters_receipt_json`"
            " 在异常文本里硬写 ``BOT_TOKEN`` 前缀的 ``sk-`` 形假值（掩码 ``sk-l**en``），断言异常原文"
            "不得进回执 JSON。合成串、服务面不存在；摘掉＝该防泄锁失去料。"
        ),
    ),
    ("tests/test_credential_health_probe_throat.py", "b3384e859d047291"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：模块常量 ``COOKIE_SENTINEL``（SESSDATA 前缀的泄漏金丝雀，"
            "掩码 ``SE**64``）是 `test_cross_host_redirect_strips_cookie_from_probe` 与"
            " `test_same_host_redirect_keeps_cookie_from_probe` 的公共料——断言 cookie 值跨宿主剥离、"
            "同宿主保留。金丝雀合成值；摘掉＝两条重定向 cookie 锁同时失明。"
        ),
    ),
    ("tests/test_dangerous_command_outbound_wiring.py", "10065436e1c1bc8a"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：`test_blocked_path_still_audits_dangerous_families` 在"
            " answer 文本里硬写 ``api_key`` 赋值形假 ``sk-`` 串（掩码 ``sk-a**56``）当危险家族审计"
            "样本。合成串、服务面不存在；摘掉＝该审计腿验不到同一件事。"
        ),
    ),
    ("tests/test_file_send_receive_parity.py", "210fd51512083fab"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：`test_inbound_telegram_document_segment_is_produced_and_fetched`"
            " 给假 bot 配置的 token 槽喂 ``123456:secret`` 形字面量（六位数字冒号短词，不成真 token"
            " 形）。合成串、服务面不存在；摘掉＝该入站文档收发对锁失去夹具。"
        ),
    ),
    ("tests/test_meme_vlm_observability.py", "b788e22f3b91cc5e"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：模块常量 ``SECRET_KEY``（``sk-`` 前缀「勿泄漏」金丝雀，掩码"
            " ``sk-S**e7``）是 `test_l4_http_status_leaves_one_attributable_trace` 至"
            " `test_l7_json_parse_error_traces_type_and_len` 四把归因锁与 backfill 各用例的公共假 key"
            " 料。合成串、服务面不存在；摘掉＝整组归因锁同时失料。"
        ),
    ),
    ("tests/test_person_profile_memory.py", "1584ab5c55a42564"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：`test_instrumented_local_secrets_are_redacted` 在引用文本里"
            "硬写 ``sk-`` 形假 key（掩码 ``sk-a**90``）加盘符路径，断言打码腿把两者一起盖住。合成串、"
            "服务面不存在；摘掉＝该打码锁失料。"
        ),
    ),
    ("tests/test_policy_gate_reason_observability.py", "3e71794c5b09eb9f"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：`test_free_text_never_becomes_a_gate_reason` 在自由文本里"
            "硬写 ``token`` 赋值形假 ``sk-`` 串（掩码 ``sk-a**67``），断言自由文本不得当门禁理由透传。"
            "合成串、服务面不存在；摘掉＝该锁验不到同一件事。"
        ),
    ),
    ("tests/test_seat_fix_persona_r2.py", "1584ab5c55a42564"): (
        3,
        (
            "2026-10-04 审计确认夹具假值：`test_receipt_details_redacted_for_exception_with_paths` 的"
            " ``sk-`` 形合成假 key（掩码 ``sk-a**90``；:481 喂料、:488/:492 反断言原文不进"
            " summary/detail）。三处同值＝同一条回执脱敏锁的喂料加两处反断言；摘掉＝该锁失明。"
        ),
    ),
    ("tests/test_telegram_document_ingress.py", "210fd51512083fab"): (
        1,
        (
            "2026-10-04 审计确认夹具假值：``_FakeBot`` 给 bot 配置 token 槽喂 ``123456:secret`` 形"
            "字面量，是本件文档入站各用例（`test_document_is_now_in_the_file_id_types` 等）的公共"
            "夹具。合成串、不成真 token 形、服务面不存在；摘掉＝整件文档入站锁失去假 bot。"
        ),
    ),
}

# 棘轮上限 = 建账现值「总出现次数」（去脆化前 len(三元组)=32 的原语义，沿用计数和）。
# 还债后想降：删条目或降次数即可（本锁只拦升）。
# 32→33（2026-10-04，用户简报点名授权）：新增 scripts/migrate_persona_isolation.py 的
# RUNTIME_WRITE_TOKEN 确认短语占位符一枚（:79，掩码 I-A**TE，审计席核过原文＝非凭据）；
# 该件不在 tests/ ⇒ 豁免表形态门拒收，名册是唯一合规落点 ⇒ 上限随账 +1。记账性抬升，非为真债开口子。
ROSTER_CEILING = 33

# 反缩面地板（2026-09-24 现算 git ls-files 口径可扫文本件=1893，留 ≈5% 余量）。
SCANNED_FLOOR = 1800


@pytest.fixture(scope="module")
def full_scan() -> tuple[int, list[Finding]]:
    """全量跑一次尺（只读），回潮锁与地板锁共用这一次实扫。"""
    scannable, _binary, _excluded = tracked_text_files(REPO_ROOT)
    findings = scan_paths(REPO_ROOT, scannable)
    return len(scannable), findings


def _counts(findings: list[Finding]) -> Counter[tuple[str, str]]:
    """全树 F1 命中按 (件, 指纹) 计多集；行号不参与（漂移容错）。"""
    return Counter((f.path, f.digest) for f in f1_findings(findings))


def _roster_counts() -> Counter[tuple[str, str]]:
    """点名册的 (件, 指纹) -> 期望次数 视图（导航行号在此丢弃）。"""
    return Counter({(p, d): c for (p, d), (c, _nav) in F1_DEBT_ROSTER.items()})


def _exempt_counts() -> Counter[tuple[str, str]]:
    """夹具级豁免的 (件, 指纹) -> 豁免枚数 视图（理由在此丢弃，由逐枚理由用例执法）。"""
    return Counter({(p, d): c for (p, d), (c, _why) in FIXTURE_FAKE_EXEMPTIONS.items()})


def _tree_after_fixture_exemption(
    tree: Counter[tuple[str, str]],
) -> tuple[Counter[tuple[str, str]], list[tuple[tuple[str, str], int]]]:
    """扣掉夹具豁免后的树上多集 ＋「豁免条目今天在树上扫不到」的幽灵清单。

    两件事一起返回是刻意的：豁免面必须与名册的 missing 腿同口径反查——条目一旦从树上消失
    （他席把这条夹具摘了或改写了值），留在表里就等于给未来的凭据预发免检证，必须当场红。
    """
    exempt = _exempt_counts()
    return tree - exempt, sorted((exempt - tree).items())


def _exemption_reasons_are_written() -> list[str]:
    """豁免面自锁：逐枚理由非空、且必须点名它属于哪条断言（写不出料=不配豁免）。"""
    bad = []
    for (path, digest), (count, why) in FIXTURE_FAKE_EXEMPTIONS.items():
        if count < 1 or not path.startswith("tests/") or len(digest) != 16:
            bad.append(f"{path}:{digest} 形态不合法（枚数<1／不在 tests/／指纹非 16 位）")
        if not why.strip() or "`test_" not in why:
            bad.append(f"{path}:{digest} 的理由没点名它属于哪条用例")
    return bad


def _debt_delta(
    tree: Counter[tuple[str, str]],
    roster: Counter[tuple[str, str]],
) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]]]:
    """回潮锁的两腿差集：
    extra   = 树上有而册里没覆盖（新凭据 / 同值多印 / 册外件）——「不许自我豁免」；
    missing = 册里点名了而树上已扫不到（未摘净 / 幽灵条目）——「每枚今天仍在」。
    二者皆空才算闭合。
    """
    return tree - roster, roster - tree


# ------------------------------------------------------------------ 锁① 回潮（双向闭合）
def test_f1_findings_are_exactly_known_debt_roster(
    full_scan: tuple[int, list[Finding]],
) -> None:
    """(件, 指纹) 计数双向闭合：树上任何册外/多出的 F1 = 新硬编码凭据回潮；名单里点名了
    但树上已无 = 未摘净/幽灵条目（不许靠删册自我豁免）。行号漂移不再触发假红。
    夹具级豁免（测试自己合成的假凭据）在比对前按 (件,指纹) 逐枚扣减；扣完仍多出＝照样红。"""
    _scanned, findings = full_scan
    tree, stale_exemptions = _tree_after_fixture_exemption(_counts(findings))
    assert not stale_exemptions, (
        "夹具豁免条目点名了、今天树上却扫不到（该随夹具一起摘，不许留着当预豁免）："
        f"{stale_exemptions}"
    )
    extra, missing = _debt_delta(tree, _roster_counts())
    assert not extra, (
        "git 已跟踪源出现册外/超次的 F1 硬编码凭据命中（(件,指纹) -> 多出的出现次数，全掩码）："
        f"{sorted(extra.items())}"
    )
    assert not missing, (
        "点名册点名了、但今天树上扫不到的 (件,指纹)（还债须与摘册同批，"
        f"不许留幽灵条目自我豁免）：{sorted(missing.items())}"
    )


def test_seed_full_scan_still_spots_a_rostered_debt(
    full_scan: tuple[int, list[Finding]],
) -> None:
    """活性种子（S139 重锚 / S209 去脆化跟随）：全树实扫必须仍能命中点名册上至少一枚在册真 F1。

    判据为树上 (件,指纹) 键集与点名册键集交集非空（尺瞎⇒空集⇒红）；尺活性不靠「债必须永驻
    树上」来保（那会把还债本身判红）。被摘那枚的回潮由锁①「回潮」腿执法。
    """
    _scanned, findings = full_scan
    assert set(_counts(findings)) & set(F1_DEBT_ROSTER), (
        "全树扫不中任何一枚在册 F1——扫描面或判据出了回归（尺瞎了）"
    )


# ------------------------------------------------------------------ 锁② 棘轮
def test_roster_never_grows() -> None:
    """点名册总出现次数只准降不准升：加行须先过用户裁决（本门默认拒绝）。

    去脆化后语义 = 各 (件,指纹) 期望次数之和（对应建账现值 32），非字典键数。
    """
    total = sum(c for (c, _nav) in F1_DEBT_ROSTER.values())
    assert total <= ROSTER_CEILING, (
        f"点名册总出现次数 {total} 已超上限 {ROSTER_CEILING}——"
        "F1 欠账账本不允许膨胀"
    )


# ------------------------------------------------------------------ 锁③ 地板
def test_scan_surface_never_shrinks_below_floor(
    full_scan: tuple[int, list[Finding]],
) -> None:
    """清单口径 = git ls-files（is_in_scope 排除），扫描件数塌了必须响。"""
    scanned, _findings = full_scan
    assert scanned >= SCANNED_FLOOR, (
        f"扫描件数 {scanned} < 地板 {SCANNED_FLOOR}；扫描面被缩小了"
    )
    # 尺自带的地板机制本身要能抛（锁④-③ 的另一半在注毒席）。
    enforce_coverage(scanned, floor=SCANNED_FLOOR)


# ------------------------------------------------------------------ 锁④ 注毒
def _fake_prefixed_key() -> str:
    """一枚形态合法的假 ah- 凭据（合成串，非任何真值；本文件源码行不落入 F1 形态）。"""
    return "ah-" + hashlib.sha256(b"s100r-poison-fixture").hexdigest()


def test_poison_fake_credential_lands_in_f1() -> None:
    """注毒①：内存里种一枚高熵假凭据 ⇒ F1 必抓、指纹对得上、掩码不带原文。"""
    fake = _fake_prefixed_key()
    findings = scan_text(f'api_key = "{fake}"\n', path="mem/poison1.py")
    hits = f1_findings(findings)
    assert hits, "注入的假凭据未落 F1——尺瞎了"
    assert any(f.digest == fingerprint(fake) for f in hits)
    for f in hits:
        assert fake not in f.masked  # 掩码纪律：原文绝不进输出面


def test_poison_env_reference_lands_in_f2_not_f1() -> None:
    """注毒②：同位置写成 env: 引用 ⇒ 落 F2 不落 F1（F1/F2 分流判据没写反）。

    故意用带 secret 语义的变量名（api_key）：若判据写反，这条会被赋值正则
    直接抓进 F1；正确行为是 classify_placeholder 先行、把 env: 引用降入 F2。
    """
    line = 'api_key = "env:BOT_API_KEY_AXONHUB"\n'
    findings = scan_text(line, path="mem/poison2.py")
    assert not f1_findings(findings), "env: 引用被判成 F1——分流写反"
    env_refs = [f for f in f2_findings(findings) if f.family == "f2:env-ref"]
    assert env_refs, "env: 引用未被 F2 认出——尺看不见合规形态"


def test_poison_shrunk_file_list_trips_coverage_floor(
    tmp_path: Path,
) -> None:
    """注毒③：扫描清单缩成一枚文件 ⇒ 地板必抛（少扫不许全绿）。"""
    poison = tmp_path / "leaked.py"
    fake = _fake_prefixed_key()
    poison.write_text(f'API_KEY = "{fake}"\n', encoding="utf-8")
    # 清单只剩这一枚文件时，尺确实还能扫到它（证明抛错是「面缩」而非「码坏」）。
    hits = f1_findings(scan_paths(tmp_path, ["leaked.py"]))
    assert any(f.digest == fingerprint(fake) for f in hits)
    with pytest.raises(CoverageError):
        enforce_coverage(1, floor=SCANNED_FLOOR)


# ------------------------------------------------------ 去脆化后锁①仍须有牙（三条）
def test_lock1_teeth_scanned_new_credential_turns_red(tmp_path: Path) -> None:
    """真·新凭据仍抓得住：往被扫集合落一枚册外高熵假凭据，经真尺扫出后喂进锁①的两腿差集
    ⇒ 「回潮」腿必非空（等价于未在册 (件,指纹) 使锁①当场红）。不落真树写入。"""
    fake = _fake_prefixed_key()
    poison = tmp_path / "poison_new_debt.py"
    poison.write_text(f'API_KEY = "{fake}"\n', encoding="utf-8")
    hits = f1_findings(scan_paths(tmp_path, ["poison_new_debt.py"]))
    assert hits, "注入的假凭据未被 F1 认出——尺瞎"
    tree = _roster_counts() + Counter((f.path, f.digest) for f in hits)
    extra, _missing = _debt_delta(tree, _roster_counts())
    assert extra, "册外新 (件,指纹) 未被判为回潮——去脆化把锁①的牙拔了"


def test_lock1_teeth_existing_debt_extra_copy_turns_red() -> None:
    """既有在册凭据被多印一份 = 计数超 ⇒ 「回潮」腿非空（不靠行号也拦得住）。"""
    roster = _roster_counts()
    key = min(roster)
    tree = roster.copy()
    tree[key] += 1
    extra, _missing = _debt_delta(tree, roster)
    assert extra and extra[key] == 1, "同值多印未判为回潮"


def test_lock1_teeth_cannot_self_exempt_by_deleting_roster_entry() -> None:
    """不许自我豁免：把某枚从名单删掉、但该凭据今天仍在树上 ⇒ 「回潮」腿（树上多出的）必红。

    即：不能靠删点名册条目把一枚活着的凭据洗绿——它还落在树上，就会作为册外/超次被抓。
    """
    roster = _roster_counts()
    tree = roster.copy()  # 树上原样还在（含被删那一枚）
    key = min(roster)
    shrunk = roster.copy()
    del shrunk[key]  # 名单被偷偷删一枚
    extra, _missing = _debt_delta(tree, shrunk)
    assert extra and extra[key] == roster[key], (
        "删册即自我豁免未被回潮腿抓住——白名单能被删条目洗绿，牙断了"
    )


def test_lock1_teeth_cannot_pad_roster_with_ghost_entry() -> None:
    """反查·每枚今天仍在：往名单塞一枚树上并不存在的幽灵 (件,指纹)（预豁免未来凭据）
    ⇒ 「missing」腿必红。点名册只能是「树上真实存在的已知债」，不许虚报。
    """
    roster = _roster_counts()
    tree = roster.copy()  # 树上正常，没有幽灵
    ghost = ("tests/__ghost_pad__.py", "0" * 16)
    padded = roster.copy()
    padded[ghost] = 1  # 名单虚报一枚树上没有的
    _extra, missing = _debt_delta(tree, padded)
    assert missing and missing[ghost] == 1, (
        "幽灵点名未被反查腿抓住——名单可以虚填达标值，牙断了"
    )


# ------------------------------------------------------------------ 夹具级豁免的三条牙
def test_fixture_exemption_entries_are_justified_and_do_not_move_the_ceiling() -> None:
    """豁免面自锁：逐枚理由要点名它属于哪条断言；名册与上限**一字未动**（豁免不是还债通道）。"""
    bad = _exemption_reasons_are_written()
    assert not bad, "夹具豁免条目不合法：" + "｜".join(bad)
    assert not (set(FIXTURE_FAKE_EXEMPTIONS) & set(F1_DEBT_ROSTER)), (
        "同一枚 (件,指纹) 既进豁免又进欠账名册＝两本账互相补洞，先判它到底是哪一种"
    )
    total = sum(c for (c, _nav) in F1_DEBT_ROSTER.values())
    assert total <= ROSTER_CEILING, "豁免面被拿去当抬上限的台阶——棘轮锁②仍按建账现值执法"


def test_fixture_exemption_teeth_extra_copy_still_red() -> None:
    """豁免只按枚数放行：同一枚被多印 ⇒ 超出的份数照旧落回潮腿（绝不扩成「整件免检」）。"""
    exempt = _exempt_counts()
    assert exempt, "豁免表为空 ⇒ 本条牙在空跑（先把该登记的夹具登记回来再谈）"
    key = min(exempt)
    tree = _roster_counts() + exempt
    padded = tree.copy()
    padded[key] += 1  # 同值多印一份
    extra, _missing = _debt_delta(_tree_after_fixture_exemption(padded)[0], _roster_counts())
    assert extra and extra[key] == 1, (
        f"多印的豁免夹具未被判为回潮（应只放行豁免枚数）：{sorted(extra.items())}"
    )


def test_fixture_exemption_teeth_other_digest_in_same_file_still_red() -> None:
    """同件另一枚（指纹不同）不在豁免面内 ⇒ 仍落回潮腿：豁免逐枚生效，不是按件免检。"""
    exempt = _exempt_counts()
    assert exempt
    (path, _digest), _n = min(exempt.items())
    other = (path, "f" * 16)  # 同件、不同指纹
    tree = _roster_counts() + exempt + Counter({other: 1})
    extra, _missing = _debt_delta(_tree_after_fixture_exemption(tree)[0], _roster_counts())
    assert other in extra and extra[other] == 1, (
        f"同件另一枚凭据被豁免洗绿了：{sorted(extra.items())}"
    )


def test_fixture_exemption_teeth_ghost_entry_turns_red() -> None:
    """豁免条目在今天的树上扫不到 ⇒ stale 腿非空（不许留着当未来凭据的预豁免）。"""
    exempt = _exempt_counts()
    assert exempt
    tree = _roster_counts()  # 树上只有名册那批，豁免那枚不见了
    _after, stale = _tree_after_fixture_exemption(tree)
    assert stale and set(dict(stale)) == set(exempt), (
        f"消失的夹具豁免未被反查腿抓住：{stale}"
    )


def test_fixture_exemption_does_not_blind_the_seeded_poison() -> None:
    """注毒联动：豁免面存在时，新种一枚高熵假凭据仍必须落回潮腿（尺没被豁免面洗瞎）。"""
    fake = _fake_prefixed_key()
    probe = ("tests/test_poison_probe.py", fingerprint(fake))
    tree = _roster_counts() + _exempt_counts() + Counter({probe: 1})
    extra, _missing = _debt_delta(_tree_after_fixture_exemption(tree)[0], _roster_counts())
    assert extra and probe in extra, "注入的新凭据被豁免面洗绿——豁免扩成免检了"
