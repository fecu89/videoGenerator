from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from video_harness.pacing_presets import apply_pacing_preset
from video_harness.settings import (
    HarnessSettings,
    settings_sha256,
    write_project_settings,
)
from video_harness.settings_ui import (
    MAX_REQUEST_BYTES,
    SettingsUiServer,
    build_parser,
    create_server,
)


@pytest.fixture
def running_server(tmp_path: Path) -> Iterator[SettingsUiServer]:
    settings_file = tmp_path / "settings.json"
    write_project_settings(HarnessSettings(), settings_file)
    server = create_server(
        settings_file=settings_file,
        token="test-session-token",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def api_headers(server: SettingsUiServer) -> dict[str, str]:
    host, port = server.server_address
    return {
        "Origin": f"http://{host}:{port}",
        "X-Settings-Token": server.session_token,
    }


def request(
    server: SettingsUiServer,
    method: str,
    path: str,
    *,
    body: object | str | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], http.client.HTTPMessage]:
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=3)
    actual_headers = dict(headers or {})
    if isinstance(body, (dict, list)):
        encoded: str | bytes | None = json.dumps(body)
        actual_headers.setdefault("Content-Type", "application/json")
    else:
        encoded = body
    connection.request(method, path, body=encoded, headers=actual_headers)
    response = connection.getresponse()
    raw = response.read()
    response_headers = response.headers
    connection.close()
    payload = json.loads(raw) if raw else {}
    return response.status, payload, response_headers


def get_payload(server: SettingsUiServer) -> dict[str, object]:
    status, payload, _ = request(
        server,
        "GET",
        "/api/settings",
        headers=api_headers(server),
    )
    assert status == 200
    return payload


def test_get_settings_returns_document_catalog_sections_and_revision(
    running_server: SettingsUiServer,
):
    status, payload, headers = request(
        running_server,
        "GET",
        "/api/settings",
        headers=api_headers(running_server),
    )

    assert status == 200
    assert payload["settings"] == HarnessSettings().model_dump(mode="json")
    assert payload["recommended_settings"] == apply_pacing_preset(HarnessSettings(), "shorts").model_dump(mode="json")
    assert payload["revision"] == settings_sha256(HarnessSettings())
    assert len(payload["catalog"]) == 60
    assert [section["id"] for section in payload["sections"]] == ["pace", "basic", "sound", "output", "advanced"]
    assert [profile["id"] for profile in payload["output_profiles"]] == ["landscape", "portrait", "square"]
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_api_rejects_missing_token_with_403(running_server: SettingsUiServer):
    headers = api_headers(running_server)
    headers.pop("X-Settings-Token")

    status, payload, _ = request(
        running_server,
        "GET",
        "/api/settings",
        headers=headers,
    )

    assert status == 403
    assert payload["error"] == "forbidden"


def test_api_rejects_wrong_origin_with_403(running_server: SettingsUiServer):
    headers = api_headers(running_server)
    headers["Origin"] = "https://example.com"

    status, payload, _ = request(
        running_server,
        "GET",
        "/api/settings",
        headers=headers,
    )

    assert status == 403
    assert payload["error"] == "forbidden"


def test_api_rejects_wrong_host_with_403(running_server: SettingsUiServer):
    headers = api_headers(running_server)
    headers["Host"] = "example.com"

    status, payload, _ = request(
        running_server,
        "GET",
        "/api/settings",
        headers=headers,
    )

    assert status == 403
    assert payload["error"] == "forbidden"


def test_put_rejects_non_json_and_oversized_bodies(running_server: SettingsUiServer):
    headers = api_headers(running_server)
    headers["Content-Type"] = "text/plain"
    status, payload, _ = request(
        running_server,
        "PUT",
        "/api/settings",
        body="not json",
        headers=headers,
    )
    assert status == 415
    assert payload["error"] == "unsupported_media_type"

    headers["Content-Type"] = "application/json"
    status, payload, _ = request(
        running_server,
        "PUT",
        "/api/settings",
        body=b"x" * (MAX_REQUEST_BYTES + 1),
        headers=headers,
    )
    assert status == 413
    assert payload["error"] == "request_too_large"


def test_put_invalid_settings_returns_422_without_changing_file(
    running_server: SettingsUiServer,
):
    before = running_server.settings_file.read_bytes()
    current = get_payload(running_server)
    settings = current["settings"]
    settings["voice"]["max_scene_seconds"] = 14.5
    settings["local_video"]["scene_gap_seconds"] = 0.65
    settings["local_video"]["max_scene_seconds"] = 15.0

    status, payload, _ = request(
        running_server,
        "PUT",
        "/api/settings",
        body={"settings": settings, "base_revision": current["revision"]},
        headers=api_headers(running_server),
    )

    assert status == 422
    assert payload["error"] == "validation_error"
    assert any(
        detail["path"] == "local_video.max_scene_seconds"
        for detail in payload["details"]
    )
    assert running_server.settings_file.read_bytes() == before


def test_put_stale_revision_returns_409_without_changing_file(
    running_server: SettingsUiServer,
):
    current = get_payload(running_server)
    externally_changed = HarnessSettings(voice={"temperature": 0.8})
    write_project_settings(externally_changed, running_server.settings_file)
    before = running_server.settings_file.read_bytes()

    status, payload, _ = request(
        running_server,
        "PUT",
        "/api/settings",
        body={"settings": current["settings"], "base_revision": current["revision"]},
        headers=api_headers(running_server),
    )

    assert status == 409
    assert payload["error"] == "revision_conflict"
    assert running_server.settings_file.read_bytes() == before


def test_put_valid_settings_atomically_saves_and_returns_new_revision(
    running_server: SettingsUiServer,
):
    current = get_payload(running_server)
    settings = current["settings"]
    settings["voice"]["temperature"] = 0.8

    status, payload, _ = request(
        running_server,
        "PUT",
        "/api/settings",
        body={"settings": settings, "base_revision": current["revision"]},
        headers=api_headers(running_server),
    )

    saved = HarnessSettings.model_validate_json(
        running_server.settings_file.read_text(encoding="utf-8")
    )
    assert status == 200
    assert saved.voice.temperature == 0.8
    assert payload["settings"] == saved.model_dump(mode="json")
    assert payload["revision"] == settings_sha256(saved)
    assert not running_server.settings_file.with_suffix(".json.tmp").exists()


def test_server_serves_only_allowlisted_local_assets(running_server: SettingsUiServer):
    expected = {
        "/": "text/html; charset=utf-8",
        "/settings.css": "text/css; charset=utf-8",
        "/settings.js": "text/javascript; charset=utf-8",
    }
    host, port = running_server.server_address
    for path, content_type in expected.items():
        connection = http.client.HTTPConnection(host, port, timeout=3)
        connection.request("GET", path)
        response = connection.getresponse()
        content = response.read()
        connection.close()
        assert response.status == 200
        assert response.headers["Content-Type"] == content_type
        assert content


def test_unknown_and_traversal_routes_are_404(running_server: SettingsUiServer):
    for path in ("/unknown", "/../settings.json", "/%2e%2e/settings.json"):
        status, payload, _ = request(running_server, "GET", path)
        assert status == 404
        assert payload["error"] == "not_found"


def test_shutdown_route_stops_only_after_authenticated_request(
    running_server: SettingsUiServer,
):
    status, _, _ = request(running_server, "POST", "/api/shutdown", headers={})
    assert status == 403
    assert not running_server.shutdown_requested.is_set()

    status, payload, _ = request(
        running_server,
        "POST",
        "/api/shutdown",
        headers=api_headers(running_server),
    )

    assert status == 200
    assert payload["status"] == "closing"
    assert running_server.shutdown_requested.wait(timeout=1)


def test_parser_defaults_to_port_zero_and_can_disable_browser_opening():
    defaults = build_parser().parse_args([])
    explicit = build_parser().parse_args(["--port", "32123", "--no-open"])

    assert defaults.port == 0
    assert defaults.no_open is False
    assert explicit.port == 32123
    assert explicit.no_open is True
