from app.config import load_settings
from app.tools.registry import build_default_registry


def test_datetime_and_stats():
    settings = load_settings()
    reg = build_default_registry(settings)
    dt = reg.call("get_datetime", {})
    assert dt.ok
    assert "utc" in dt.data
    stats = reg.call("get_system_stats", {})
    assert stats.ok
    assert "memory" in stats.data


def test_allowlist_rejects_unknown():
    settings = load_settings()
    reg = build_default_registry(settings)
    result = reg.call("run_allowlisted_command", {"name": "not-a-real-command"})
    assert not result.ok
    assert "allowlist" in result.data["error"].lower() or "not on the allowlist" in result.data["error"]


def test_open_url_requires_http():
    settings = load_settings()
    reg = build_default_registry(settings)
    bad = reg.call("open_url", {"url": "javascript:alert(1)"})
    assert not bad.ok
    good = reg.call("open_url", {"url": "https://x.ai"})
    assert good.ok
    assert good.ui_event == "open_url"


def test_play_music_rejects_path_escape():
    settings = load_settings()
    reg = build_default_registry(settings)
    sneaky = reg.call("play_music", {"filename": "../etc/passwd"})
    assert not sneaky.ok
