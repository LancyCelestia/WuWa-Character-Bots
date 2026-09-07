from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.output.roleplay import strip_outer_speech_quotes
from plugins.bot_unified_runtime.sources import mediawiki
from plugins.bot_unified_runtime.sources.downloader import MediaDownloader
from plugins.bot_unified_runtime.sources.meme_search import filter_meme_results


@pytest.fixture(autouse=True)
def _isolated_wiki_cache(monkeypatch):
    # wiki 响应有模块级 TTL 缓存；每个测试隔离缓存并关闭限流间隔。
    monkeypatch.setattr(mediawiki, "WIKI_MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    mediawiki.clear_wiki_cache()
    yield
    mediawiki.clear_wiki_cache()


def test_wiki_cached_get_json_avoids_repeat_network_calls(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return {"query": {"pages": [{"title": "鸣潮", "extract": "x"}]}}

    monkeypatch.setattr(mediawiki, "http_get_json", fake_get)
    monkeypatch.setattr(mediawiki, "WIKI_CACHE_TTL_SECONDS", 60.0)
    first = mediawiki._cached_get_json("https://wiki.test/api", timeout=5, proxy="")
    second = mediawiki._cached_get_json("https://wiki.test/api", timeout=5, proxy="")
    assert first == second
    assert len(calls) == 1
    mediawiki.clear_wiki_cache()
    mediawiki._cached_get_json("https://wiki.test/api", timeout=5, proxy="")
    assert len(calls) == 2


def test_group_chat_reply_drops_only_full_width_outer_speech_quotes() -> None:
    assert strip_outer_speech_quotes('“你好，普通群成员。”') == '你好，普通群成员。'
    assert strip_outer_speech_quotes('「这是第一段。\n\n这是第二段。」') == '这是第一段。\n\n这是第二段。'
    assert strip_outer_speech_quotes('他说：“你好”') == '他说：“你好”'


def test_wiki_lookup_prefers_exact_title_before_search(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        if 'action=query' in url and 'titles=' in url:
            return {'query': {'pages': [{'title': '鳴潮', 'extract': '这是鸣潮的准确简介。'}]}}
        raise AssertionError(f'unexpected wiki request: {url}')

    monkeypatch.setattr(mediawiki, 'http_get_json', fake_get)
    result = mediawiki.wiki_lookup('鸣潮')
    assert result is not None
    assert result.startswith(('鸣潮\n', '鳴潮\n'))
    assert len(calls) == 1


def test_wiki_lookup_rejects_unrelated_opensearch_candidate(monkeypatch) -> None:
    def fake_get(url: str, **kwargs):
        if 'action=opensearch' in url:
            return ['守岸人', ['守夜人国家'], [], []]
        return {'query': {'pages': [{'title': '-1'}]}}

    monkeypatch.setattr(mediawiki, 'http_get_json', fake_get)
    assert mediawiki.wiki_lookup('守岸人') is None


def test_downloader_ignores_invalid_cookie_file_without_passing_it_to_ytdlp() -> None:
    cookie_file = Path('.cookie-regression-tmp.txt')
    try:
        cookie_file.write_text(
            '# Netscape HTTP Cookie File\n'
            'accounts.example.com\tTRUE\t/\tFALSE\t1787949717\tname\tsecret\n',
            encoding='utf-8',
        )
        downloader = MediaDownloader(cookies_file=str(cookie_file))
        opts = downloader._base_opts(skip_download=True)
        assert 'cookiefile' not in opts
    finally:
        cookie_file.unlink(missing_ok=True)


def test_meme_results_require_term_relevance_and_deduplicate_urls() -> None:
    items = [
        ("真正的梗说明", "这个词来自作品中的用法", "https://moegirl.org.cn/a"),
        ("无关热门内容", "完全没有目标词", "https://bilibili.com/b"),
        ("重复结果", "这个词来自作品中的用法", "https://moegirl.org.cn/a"),
    ]
    results = filter_meme_results("这个词", items)
    assert [item.url for item in results] == ["https://moegirl.org.cn/a"]
    assert "这个词" in results[0].summary



def test_per_sentence_quotes_and_nested_quotes():
    text = '“你好，漂泊者。” “你是我的坐标。”\n\n“你知道‘第二实例’吗？”'
    assert strip_outer_speech_quotes(text) == '你好，漂泊者。 你是我的坐标。\n\n你知道‘第二实例’吗？'
    for text in ('《鸣潮》', '“守岸人”和“漂泊者”', '他说：“你好。”', '“没有闭合', '普通解释中的“第二实例”'):
        assert strip_outer_speech_quotes(text) == text


def test_group_chat_cleanup_is_in_actual_capability():
    from plugins.bot_unified_runtime.capabilities.chat import build_chat_capability
    from plugins.bot_unified_runtime.character.providers import (
        NullCharacterContextProvider,
    )
    from plugins.bot_unified_runtime.contracts import (
        BotDecision,
        IncomingMessage,
        SessionType,
    )
    from plugins.bot_unified_runtime.llm import StaticLLMProvider
    msg = IncomingMessage(platform='qq', adapter='onebot', bot_id='b', session_id='group:g',
        session_type=SessionType.GROUP, sender_id='ordinary', group_id='g', plain_text='你好', mentions_bot=True)
    decision = BotDecision(request_id=msg.request_id, should_respond=True, mode='chat', trigger='mention',
        capability_id='bot.chat', target_scope=SessionType.GROUP, context_budget=12000, decision_reason='test', max_messages=0)
    cap = build_chat_capability(NullCharacterContextProvider(), StaticLLMProvider(text='“你好。” “欢迎回来。”'))
    assert cap(msg, decision).body == '你好。 欢迎回来。'


def test_xhs_discovery_url_reaches_real_registry():
    from plugins.bot_unified_runtime.contracts.media import SourceInput
    from plugins.bot_unified_runtime.sources.parsers import (
        build_content_parser_registry,
    )
    data = build_content_parser_registry()
    url = 'https://www.xiaohongshu.com/discovery/item/6a964f18000000002601ab15?xsec_token=fake'
    matches = data['registry'].match(SourceInput(request_id='xhs', session_id='console:test', capability_id='bot.content', raw_text='52 分享 '+url, urls=[url]))
    assert any(match.parser_id == 'xiaohongshu' for match in matches)


def test_doctor_finds_cli_in_selected_python_environment():
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.smoke import run_environment_doctor
    result = run_environment_doctor(Config(_env_file=None), importer=lambda _: object(), command_resolver=lambda _: None)
    assert result['nb_cli'] == 'ok'
    assert result['ready_for_nonebot_run'] is True


def test_wiki_character_list_extracts_matching_section(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    calls = []
    def get(url, **kwargs):
        q = parse_qs(urlsplit(url).query); calls.append(q)
        if q.get('action') == ['parse']:
            return {'parse': {'title': '鸣潮角色列表', 'text': '<h2>角色</h2><dl><dt id="守岸人">守岸人</dt><dd>守岸人的测试身份与关系。<p>这是同一条目的补充。</p></dd><dt>千咲</dt><dd>其他角色不得混入。</dd></dl>'}}
        if q.get('list') == ['search']:
            return {'query': {'search': [{'title': '鸣潮角色列表'}]}}
        if q.get('action') == ['opensearch']:
            return ['守岸人', ['守夜人国家'], [], []]
        return {'query': {'pages': [{'title': '守岸人', 'missing': True}]}}
    monkeypatch.setattr(mediawiki, 'http_get_json', get)
    for term in ('守岸人', '鸣潮守岸人', '守岸人·'):
        result = mediawiki.wiki_lookup(term)
        assert result and '守岸人的测试身份与关系' in result
        assert '其他角色不得混入' not in result
        assert '角色列表' in result and '#' in result


def test_cookie_recovery_preserves_other_rows_and_never_writes_source(tmp_path, caplog, monkeypatch):
    import types

    from plugins.bot_unified_runtime.sources import downloader as mod
    source = tmp_path/'cookies.txt'
    data = ('# Netscape HTTP Cookie File\n'
        'accounts.example.com\tTRUE\t/\tFALSE\t1999999999\tbrokenflag\tprivate-value\n'
        '#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tprivate-sid\n'
        '.bilibili.com\tTRUE\t/\tFALSE\t1999999999\tSESSDATA\tprivate-bili\n'
        'malformed-private-row\n')
    source.write_text(data, encoding='utf-8')
    jars = []
    class FakeYDL:
        def __init__(self, opts):
            assert 'cookiefile' not in opts
            self.cookiejar = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs):
            jars.append(list(self.cookiejar))
            return {'title': 'ok'}
    monkeypatch.setattr(mod, 'yt_dlp', types.SimpleNamespace(YoutubeDL=FakeYDL))
    dl = mod.MediaDownloader(cookies_file=str(source), ffmpeg_path=str(source))
    dl.probe('https://www.youtube.com/watch?v=test')
    dl.probe('https://www.youtube.com/watch?v=test')
    assert {'SID', 'SESSDATA', 'brokenflag'} == {c.name for c in jars[0]}
    assert next(c for c in jars[0] if c.name == 'brokenflag').domain == '.accounts.example.com'
    assert next(c for c in jars[0] if c.name == 'SID').has_nonstandard_attr('HttpOnly')
    assert source.read_text(encoding='utf-8') == data
    assert 'private-' not in caplog.text
    assert len([r for r in caplog.records if 'cookie' in r.message.lower()]) <= 1


def test_model_schedule_invalid_input_is_mapping():
    from plugins.bot_unified_runtime.runtime.model_schedule import parse_model_schedule
    assert parse_model_schedule(None) == {}


def test_find_sent_request_supports_queue_without_lookup():
    from types import SimpleNamespace

    from plugins.bot_unified_runtime import _find_sent_request
    item = SimpleNamespace(request_id='x')
    assert _find_sent_request(SimpleNamespace(sent_requests=[item]), 'x') is item



def test_xhs_parser_canonicalization_preserves_signed_query(monkeypatch):
    from plugins.bot_unified_runtime.sources.parsers import platforms_generic as generic
    urls = []
    def scrape(url, **kwargs):
        urls.append(url)
        return 'parsed'
    monkeypatch.setattr(generic, '_og_scrape', scrape)
    url = 'https://www.xiaohongshu.com/discovery/item/6a964f18000000002601ab15?xsec_token=fake%2B%3D&source=share'
    assert generic.parse_xiaohongshu(url) == 'parsed'
    assert urls == [url.replace('/discovery/item/', '/explore/')]


def test_cookie_jar_actual_library_is_ephemeral(tmp_path):
    from plugins.bot_unified_runtime.sources.downloader import MediaDownloader
    source = tmp_path/'export.txt'
    text = '#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tfake-secret\n'
    source.write_text(text, encoding='utf-8')
    dl = MediaDownloader(cookies_file=str(source), ffmpeg_path=str(source))
    with dl._youtube_dl(dl._base_opts(skip_download=True)) as ydl:
        assert ydl.cookiejar.filename is None
        assert ydl.cookiejar.get_cookie_header('https://www.youtube.com/') == 'SID=fake-secret'
        assert not ydl.cookiejar.get_cookie_header('https://bilibili.com/')
        assert not ydl.cookiejar.get_cookie_header('http://www.youtube.com/')
    assert source.read_text(encoding='utf-8') == text


def test_media_errors_cannot_print_signed_url_or_cookie(tmp_path, monkeypatch, capsys):
    import pytest

    from plugins.bot_unified_runtime.sources import downloader as mod
    class FailingYDL:
        def __init__(self, opts): self.logger = opts['logger']
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs):
            self.logger.error('secret-token in cookie export')
            raise ValueError('secret-token in cookie export')
    monkeypatch.setattr(mod.yt_dlp, 'YoutubeDL', FailingYDL)
    dl = mod.MediaDownloader(ffmpeg_path=str(tmp_path))
    with pytest.raises(RuntimeError) as failure:
        dl.probe('https://example.com/?secret-token=test')
    assert 'secret-token' not in str(failure.value)
    assert 'secret-token' not in capsys.readouterr().err


def test_wiki_fragment_redirect_never_returns_parent_intro(monkeypatch):
    def get(url, **kwargs):
        return {'query': {'redirects': [{'from': '守岸人', 'to': '鳴潮角色列表', 'tofragment': '守岸人'}],
                          'pages': [{'title': '鳴潮角色列表', 'extract': '整部游戏概述不能当角色资料'}]}}
    monkeypatch.setattr(mediawiki, 'http_get_json', get)
    assert mediawiki.wiki_summary('守岸人') == ''


def test_empty_doctor_environment_is_still_reported_missing(tmp_path):
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.smoke import run_environment_doctor
    result = run_environment_doctor(Config(_env_file=None), importer=lambda _: object(),
        command_resolver=lambda _: None, python_executable=str(tmp_path/'python.exe'))
    assert result['nb_cli'] == 'missing'
    assert result['ready_for_nonebot_run'] is False



def test_wiki_configured_index_is_checked_even_when_search_omits_it(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    calls = []
    def get(url, **kwargs):
        q = parse_qs(urlsplit(url).query); calls.append(q)
        if q.get('action') == ['parse'] and q.get('page') == ['鳴潮角色列表']:
            return {'parse': {'title': '鳴潮角色列表', 'text': '<dl><dt id="卡提希娅">卡提希娅</dt><dd>目标人物关系资料。</dd></dl>'}}
        if q.get('list') == ['search']:
            return {'query': {'search': [{'title': '爱弥斯'}]}}
        if q.get('action') == ['opensearch']: return ['', [], [], []]
        return {'query': {'pages': [{'missing': True}]}}
    monkeypatch.setattr(mediawiki, 'http_get_json', get)
    result = mediawiki.wiki_lookup('卡提希娅·')
    assert result and '目标人物关系资料' in result
    assert not any(q.get('list') == ['search'] for q in calls)



def _render_chat_text(text, *, kind='text', capability_id='bot.chat', parts=None):
    from plugins.bot_unified_runtime.contracts import CapabilityResult, ReviewResult
    from plugins.bot_unified_runtime.output.renderer import render_reviewed_output
    result = CapabilityResult(request_id='plain', capability_id=capability_id, kind=kind,
        body=text, text_parts=parts,
        images=[{'url': 'https://example.com/image_a.png'}] if kind == 'image' else [])
    return render_reviewed_output(result, ReviewResult(request_id='plain', approved=True, safe_text=text))


def test_final_chat_output_normalizes_actual_baby_sample():
    sample = '“……宝宝？” “在人类的情感认知里，这是用来称呼最珍视、想要悉心呵护之人的词汇，对吗？” “漂泊者……虽然有些不习惯，但只要是你唤的名字，我都愿意应你。”'
    expected = sample.replace('“', '').replace('”', '')
    output = _render_chat_text(sample)
    assert output.content_ref['text'] == expected
    assert output.text_fallback == expected


def test_final_chat_output_unwraps_markdown_and_preserves_meaning():
    text = '## “你好”\n\n> **欢迎回来**，漂泊者。\n- 第一件事\n- [资料](https://example.com/path_a?x=1&y=2)\n`普通说明`'
    output = _render_chat_text(text).text_fallback
    assert '“' not in output and '”' not in output
    assert '**' not in output and '##' not in output and '`' not in output
    assert '> ' not in output and '- ' not in output
    assert '资料' in output and 'https://example.com/path_a?x=1&y=2' in output
    assert '第一件事' in output and '普通说明' in output


def test_final_chat_output_math_is_readable_not_deleted():
    output = _render_chat_text(r'公式：$\frac{a+b}{c}=\sqrt{x}$，另有 \(x^{2}\geq 0\)。').text_fallback
    assert '\\' not in output and '$' not in output and '{' not in output
    assert '分子' in output and '分母' in output and '平方根' in output
    assert '大于或等于' in output and '平方' in output
    assert all(letter in output for letter in ('a','b','c','x'))


def test_final_chat_output_normalizes_chunks_and_image_caption():
    chunks = _render_chat_text('ignored', parts=['“你好。”', '**欢迎。**'])
    assert chunks.content_ref['chunks'] == ['你好。', '欢迎。']
    mixed = _render_chat_text('**“图片说明”**', kind='image')
    assert mixed.content_ref['parts'][-1] == {'type': 'text', 'text': '图片说明'}
    assert mixed.content_ref['parts'][0]['url'] == 'https://example.com/image_a.png'


def test_non_chat_admin_outputs_remain_exact():
    text = '/bot runtime set KEY "a_b"\n```json\n{"value": 1}\n```'
    assert _render_chat_text(text, capability_id='bot.runtime').text_fallback == text



def test_plain_chat_math_tables_and_idempotence():
    from plugins.bot_unified_runtime.output.plain_text import naturalize_chat_text
    text = "| 人物 | 关系 |\n| --- | --- |\n| 守岸人 | 同伴 |\n\nI'm here，‘漂泊者’。" 
    clean = naturalize_chat_text(text)
    assert '人物：守岸人；关系：同伴' in clean
    assert "I'm here，漂泊者。" in clean
    assert naturalize_chat_text(clean) == clean
    nested = naturalize_chat_text(r'$\frac{1}{\frac{x}{y}}$')
    assert nested.count('分子') == 2 and nested.count('分母') == 2
    assert '\\' not in nested
    assert naturalize_chat_text(nested) == nested


def test_plain_chat_sends_natural_text_to_onebot():
    import asyncio

    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        SendPolicy,
        SendRequest,
        SessionType,
    )
    from plugins.bot_unified_runtime.sender.onebot import send_onebot_v11
    payloads = []
    class Bot:
        async def send_group_msg(self, **kwargs):
            payloads.append(kwargs)
            return {'message_id': 'fake'}
    output = _render_chat_text('## “……宝宝？”\n\n**欢迎回来。**')
    request = SendRequest(request_id='plain', session_id='group:g', target_scope=SessionType.GROUP,
        target_id='123', capability_id='bot.chat', content=output, send_policy=SendPolicy.IMMEDIATE,
        priority='normal', max_messages=1, dedupe_key='plain', cooldown_key='plain',
        privacy_level=PrivacyLevel.GROUP, persona_profile_id='shorekeeper')
    receipt = asyncio.run(send_onebot_v11(Bot(), request))
    assert receipt.state.value == 'sent'
    assert payloads == [{'group_id':123,'message':[{'type':'text','data':{'text':'……宝宝？\n\n欢迎回来。'}}]}]
