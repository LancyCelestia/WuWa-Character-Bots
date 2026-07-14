from plugins.wuwa_unified_runtime.capabilities.memory import route_memory_command
from plugins.wuwa_unified_runtime.character.memory import SQLiteMemoryRepository


def test_memory_add_command_writes_current_user_fact(tmp_path):
    db_path = tmp_path / "memory.sqlite3"

    result = route_memory_command(
        "memory add 用户喜欢鸣潮和守岸人安静的陪伴",
        sender_id="42",
        session_id="private:42",
        db_path=db_path,
    )
    memory = SQLiteMemoryRepository(db_path).retrieve(
        request_id="req_test",
        requester_id="42",
        subject_user_id="42",
        session_id="private:42",
        query_text="鸣潮",
        max_items=5,
        max_chars=500,
    )

    assert result.capability_id == "wuwa.memory"
    assert "已记住" in result.body
    assert memory.facts[0]["text"] == "用户喜欢鸣潮和守岸人安静的陪伴"


def test_memory_list_command_returns_scoped_facts(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    repository.upsert_fact(
        fact_id="fact_1",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="manual",
        text="用户希望被称呼为漂泊者。",
    )
    repository.upsert_fact(
        fact_id="fact_other",
        subject_user_id="99",
        session_id="private:99",
        memory_kind="manual",
        text="其他用户的记忆不能列出。",
    )

    result = route_memory_command(
        "memory list",
        sender_id="42",
        session_id="private:42",
        db_path=db_path,
    )

    assert "fact_1" in result.body
    assert "用户希望被称呼为漂泊者" in result.body
    assert "其他用户" not in result.body


def test_memory_list_command_does_not_publish_personal_facts_in_group(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    repository.upsert_fact(
        fact_id="fact_private",
        subject_user_id="42",
        session_id="group:100",
        memory_kind="manual",
        text="用户的私人偏好不能在群里公开。",
    )

    result = route_memory_command(
        "memory list",
        sender_id="42",
        session_id="group:100",
        db_path=db_path,
    )

    assert "请在私聊中查看个人记忆" in result.body
    assert "fact_private" not in result.body
    assert "私人偏好" not in result.body


def test_memory_list_command_only_publishes_group_safe_facts_in_group(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    repository.upsert_fact(
        fact_id="fact_private",
        subject_user_id="42",
        session_id="group:100",
        memory_kind="manual",
        text="用户的私人偏好不能在群里公开。",
        sensitivity="personal",
    )
    repository.upsert_fact(
        fact_id="fact_group",
        subject_user_id="42",
        session_id="group:100",
        memory_kind="manual",
        text="这个群喜欢简短的鸣潮活动提醒。",
        sensitivity="group",
    )

    result = route_memory_command(
        "memory list",
        sender_id="42",
        session_id="group:100",
        db_path=db_path,
    )

    assert "fact_group" in result.body
    assert "这个群喜欢简短的鸣潮活动提醒" in result.body
    assert "fact_private" not in result.body
    assert "私人偏好" not in result.body


def test_memory_add_command_accepts_sensitivity_parameter(tmp_path):
    db_path = tmp_path / "memory.sqlite3"

    route_memory_command(
        "memory add --sensitivity=group 这个群喜欢简短的鸣潮活动提醒",
        sender_id="42",
        session_id="group:100",
        db_path=db_path,
    )
    memory = SQLiteMemoryRepository(db_path).retrieve(
        request_id="req_test",
        requester_id="42",
        subject_user_id="42",
        session_id="group:100",
        query_text="鸣潮",
        max_items=5,
        max_chars=500,
    )

    assert memory.facts[0]["text"] == "这个群喜欢简短的鸣潮活动提醒"
    assert memory.facts[0]["sensitivity"] == "group"
    assert memory.facts[0]["scope_key"] == "session:group:100"


def test_memory_delete_command_removes_scoped_fact(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    repository.upsert_fact(
        fact_id="fact_1",
        subject_user_id="42",
        session_id="private:42",
        memory_kind="manual",
        text="用户希望被称呼为漂泊者。",
    )

    result = route_memory_command(
        "memory delete fact_1",
        sender_id="42",
        session_id="private:42",
        db_path=db_path,
    )
    memory = SQLiteMemoryRepository(db_path).retrieve(
        request_id="req_test",
        requester_id="42",
        subject_user_id="42",
        session_id="private:42",
        query_text="称呼",
        max_items=5,
        max_chars=500,
    )

    assert "已删除" in result.body
    assert memory.facts == []


def test_memory_command_rejects_missing_db_path():
    result = route_memory_command(
        "memory add 用户喜欢鸣潮",
        sender_id="42",
        session_id="private:42",
        db_path="",
    )

    assert result.capability_id == "wuwa.memory"
    assert "记忆数据库未配置" in result.body
