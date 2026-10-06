from __future__ import annotations

import re
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "settings_web"


def asset(name: str) -> str:
    return (WEB_ROOT / name).read_text(encoding="utf-8")


def test_workbench_has_approved_landmarks_and_korean_actions():
    html = asset("settings.html")

    for landmark in (
        'id="settings-nav"',
        'id="settings-main"',
        'id="settings-search"',
        'id="restore-recommended"',
        'id="save-settings"',
        'id="save-and-close"',
        'aria-live="polite"',
    ):
        assert landmark in html
    for phrase in (
        "Video Generator 설정",
        "권장값 복원",
        "저장",
        "저장 후 닫기",
    ):
        assert phrase in html


def test_workbench_uses_only_local_assets():
    html = asset("settings.html")

    assert 'href="/settings.css"' in html
    assert 'src="/settings.js"' in html
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()


def test_script_uses_catalog_safe_text_rendering_and_duration_contract():
    script = asset("settings.js")

    assert "payload.catalog" in script
    assert "payload.sections" in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "beforeunload" in script
    assert "voice.max_scene_seconds" in script
    assert "local_video.scene_gap_seconds" in script
    assert "local_video.max_scene_seconds" in script
    assert "X-Settings-Token" in script
    assert 'method: "PUT"' in script
    assert 'method: "POST"' in script


def test_css_matches_approved_instrument_palette_and_responsive_contract():
    css = asset("settings.css")

    for token in (
        "#172a38",
        "#eef3f5",
        "#2f6f91",
        "#b85f3b",
        "#3f7656",
        "#1c3443",
    ):
        assert token in css.lower()
    assert "@media (max-width: 760px)" in css
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css
    assert "min-height: 48px" in css
    assert "gradient(" not in css.lower()


def test_html_has_no_inline_event_handlers_or_inline_scripts():
    html = asset("settings.html")

    assert not re.search(r"\son[a-z]+=", html, flags=re.IGNORECASE)
    assert not re.search(r"<script(?![^>]+src=)", html, flags=re.IGNORECASE)
