"""K1B-G1：`_is_admin_origin` 必须走中央跨平台角色判定，禁再裸比 QQ 名单。

来源＝`logs/SEAT-ATK-K1b.md`（Important）。根 `_is_admin_origin(event)` 今天写的是
`user_id in {str(item).strip() for item in config.bot_admin_user_ids}` ——
**只看数字 ID、不看平台域**：Telegram 侧与 QQ 管理员同号即可驱动 cookie 导入/登录、
昵称设置（可指任意目标）、文件导出、群文件统计、文件通知这五条腿。
中央真身 `domains/chat_reply/policy/roles.py::is_admin_message` 内含
`platform_domain_of` 归一＋空域 fail-closed，主链 resolve_roles 走的也是它。

行为腿做不了（本仓禁 `import plugins.bot_unified_runtime`——它会在 `data/` 落 sqlite），
故用结构锁补，三腿缺一即红：
 ① `_is_admin_origin` 体内必须出现 `is_admin_message` 调用；
 ② 同一体内禁再现 `config.bot_admin_user_ids` 直读；
 ③ 根文件全域禁再出现「裸比名单」那一句原形（防拆了正门另开一窗）。

量具口径（别再收窄）：①② 里的"体内"由 `_func_source` 取，而 `_is_admin_origin` 是
 `_register_nonebot_handlers` 的**嵌套**函数——只扫模块顶层（`tree.body`）＝这把锁自己
 失明。盘上曾出现这种收窄，判明是 wave-2 replay 把**入库前的旧稿**盖回已提交件
 （台账 #68 同型 stale-base），不是"要求顶层定义"的有意加严；全案与注毒自证见
 `.superpowers/sdd/2026-09-27-fullload/reports-m2/S-FIX-K1B-LOCK.md`。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
FUNC = "_is_admin_origin"
BARE_FORM = "user_id in {str(item).strip() for item in config.bot_admin_user_ids}"


def _root_text() -> str:
    return ROOT_INIT.read_text(encoding="utf-8-sig")


def _func_source(text: str) -> str:
    # 量具口径＝扫**全树**，不是只扫模块顶层：真身 `_is_admin_origin` 是
    # `_register_nonebot_handlers` 的**嵌套**函数（现算尺：ast.walk 命中 1、tree.body
    # 命中 0），只扫顶层＝本锁对自己失明——判不出委托，也判不出没判据。
    # 更坏的一种静默：顶层若冒出同名空壳（垫片/复刻），tree.body 会拿空壳当证据读，
    # 嵌套真身退回裸比名单反而绿着过关。
    # 同族坑＝台账 #50★：单尺必漏一维（行号会漂移、局部名要并 co_cellvars），
    # 故这里既不写死行号，也不接受"命中多枚随便挑一枚"——唯一性断言钉死可判前提。
    cands = [
        n
        for n in ast.walk(ast.parse(text))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == FUNC
    ]
    assert len(cands) == 1, (
        f"根文件里 {FUNC} 锚点现算命中 {len(cands)} 枚（实读行号 "
        f"{[getattr(n, 'lineno', None) for n in cands]}）：0 枚＝坐标已漂、本锁失明；"
        "≥2 枚＝同名遮蔽或另开一窗——两种都不许猜着往下判，先修锚点"
    )
    return ast.get_source_segment(text, cands[0]) or ""


def test_admin_origin_delegates_to_central_role_judgment() -> None:
    body = _func_source(_root_text())
    assert body, f"{FUNC} 取不到函数体源码＝锁在空跑"
    assert "is_admin_message(" in body, (
        f"{FUNC} 没走中央真身 is_admin_message（跨平台同号提权缺口 K1B-G1 复发）"
    )
    assert "config.bot_admin_user_ids" not in body, (
        f"{FUNC} 仍在直读 QQ 名单：平台域没进判定"
    )


def test_bare_admin_list_membership_gone_from_root() -> None:
    text = _root_text()
    assert BARE_FORM not in text, (
        "根文件再现「裸比 admin 名单」原形＝拆了正门开了窗（K1B-G1）"
    )


def test_lock_bites_on_poisoned_copy(tmp_path: Path) -> None:
    """注毒打在 tmp 副本：把中央调用从函数体里抹掉，判据①必须看不见过得去。

    生产文件零接触。若门还没落（①此刻本就红），这发毒退化成"能认出缺失"的自证。
    """
    text = _root_text()
    body = _func_source(text)
    assert "is_admin_message(" in body, "门未落或已漂形——注毒腿此刻无意义，先修锚点"
    poisoned = text.replace(body, body.replace("is_admin_message(", "raw_id_check(", 1), 1)
    assert poisoned != text, "注毒未落到真身文本＝空跑"
    copy = tmp_path / "root_poisoned.py"
    copy.write_text(poisoned, encoding="utf-8")
    poisoned_body = _func_source(copy.read_text(encoding="utf-8-sig"))
    assert "is_admin_message(" not in poisoned_body, "注毒没打掉中央调用＝这发毒无效"
    assert "raw_id_check(" in poisoned_body, "副本读回的不是被注毒的函数体＝量具错位"
