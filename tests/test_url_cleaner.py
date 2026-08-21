from plugins.wuwa_unified_runtime.sources.url_cleaner import (
    clean_tracking_url,
    clean_urls_in_text,
)


def test_clean_tracking_url_strips_common_trackers():
    result = clean_tracking_url(
        "https://www.bilibili.com/video/BV1xx411c7mD"
        "?spm_id_from=333.999.0.0&vd_source=abc123&p=2"
    )

    assert result.changed is True
    assert result.reason == "ok"
    assert "spm_id_from" in result.removed_params
    assert "vd_source" in result.removed_params
    assert "p=2" in result.url
    assert result.url.startswith("https://www.bilibili.com/video/BV1xx411c7mD")


def test_clean_tracking_url_keeps_business_params_and_fragment():
    url = (
        "https://www.example.com/article/1?utm_source=twitter&"
        "category=tech#section-2"
    )
    result = clean_tracking_url(url)

    assert result.changed is True
    assert "utm_source" in result.removed_params
    assert "category=tech" in result.url
    assert result.url.endswith("#section-2")


def test_clean_tracking_url_no_tracking_params_is_no_change():
    url = "https://www.example.com/article/1?category=tech"
    result = clean_tracking_url(url)

    assert result.changed is False
    assert result.reason == "no_tracking_params"
    assert result.url == url


def test_clean_tracking_url_invalid_url_is_untouched():
    result = clean_tracking_url("not a url at all")

    assert result.changed is False
    assert result.reason == "invalid_url"
    assert result.url == "not a url at all"


def test_clean_tracking_url_non_http_scheme_is_untouched():
    result = clean_tracking_url("ftp://example.com/file?utm_source=x")

    assert result.changed is False
    assert result.reason == "non_http_url"


def test_clean_tracking_url_extra_params_are_case_insensitive():
    result = clean_tracking_url(
        "https://example.com/?RefId=abc&refid=def",
        extra_params=["refid"],
    )

    assert result.changed is True
    assert result.removed_params == ("RefId", "refid")


def test_clean_urls_in_text_replaces_links_only():
    text = "看这个 https://b23.tv/abc?utm_source=share 和 https://example.com/?fbclid=1 链接"
    cleaned = clean_urls_in_text(text)

    assert "utm_source" not in cleaned
    assert "fbclid" not in cleaned
    assert "https://b23.tv/abc" in cleaned
    assert "https://example.com/" in cleaned
