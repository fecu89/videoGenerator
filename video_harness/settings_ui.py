from __future__ import annotations

import argparse
import base64
import json
import secrets
import threading
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from pydantic import ValidationError

from .file_picker import choose_local_path
from .output_profiles import output_profiles_payload

from .settings import (
    PROJECT_SETTINGS_FILE,
    HarnessSettings,
    load_project_settings,
    settings_sha256,
    write_project_settings,
)
from .pacing_presets import pacing_payload, apply_pacing_preset
from .speech_test import DEFAULT_SAMPLE, SpeechTester
from .settings_catalog import (
    settings_catalog,
    settings_catalog_payload,
    settings_sections_payload,
)


MAX_REQUEST_BYTES = 64 * 1024
WEB_ROOT = Path(__file__).with_name("settings_web")
ASSETS: dict[str, tuple[str, str]] = {
    "/": ("settings.html", "text/html; charset=utf-8"),
    "/settings.css": ("settings.css", "text/css; charset=utf-8"),
    "/settings.js": ("settings.js", "text/javascript; charset=utf-8"),
}
CATALOG_BY_KEY = {item.key: item for item in settings_catalog()}


class SettingsUiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        settings_file: Path,
        token: str,
    ) -> None:
        super().__init__(address, SettingsUiHandler)
        self.settings_file = settings_file
        self.session_token = token
        host, port = self.server_address
        self.allowed_origin = f"http://{host}:{port}"
        self.allowed_host = f"{host}:{port}"
        self.shutdown_requested = threading.Event()
        self.picker_lock = threading.Lock()
        # Keeps a loaded TTS model between test presses; closed when the screen closes.
        self.speech_tester = SpeechTester()


class SettingsUiHandler(BaseHTTPRequestHandler):
    server: SettingsUiServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/settings":
            if not self._authenticate_api():
                return
            settings = load_project_settings(self.server.settings_file)
            self._send_json(
                HTTPStatus.OK,
                {
                    "settings": settings.model_dump(mode="json"),
                    "recommended_settings": apply_pacing_preset(HarnessSettings(), "shorts").model_dump(mode="json"),
                    "sections": settings_sections_payload(),
                    "catalog": settings_catalog_payload(),
                    "revision": settings_sha256(settings),
                    "pacing_presets": pacing_payload(),
                    "output_profiles": output_profiles_payload(),
                    "speech_test_sample": DEFAULT_SAMPLE,
                },
            )
            return
        if path in ASSETS:
            self._serve_asset(path)
            return
        self._not_found()

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        if path != "/api/settings":
            self._not_found()
            return
        if not self._authenticate_api():
            return
        if self.headers.get_content_type() != "application/json":
            self._send_error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "unsupported_media_type",
                "JSON 요청만 허용됩니다.",
            )
            return
        length = self._content_length()
        if length is None:
            return
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            self._send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "request_too_large",
                "설정 요청이 허용 크기를 초과했습니다.",
            )
            return
        try:
            body = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "올바른 JSON 요청이 아닙니다.",
            )
            return
        if not isinstance(body, dict):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "설정 요청은 JSON 객체여야 합니다.",
            )
            return

        current = load_project_settings(self.server.settings_file)
        if body.get("base_revision") != settings_sha256(current):
            self._send_error(
                HTTPStatus.CONFLICT,
                "revision_conflict",
                "설정 파일이 다른 곳에서 변경되었습니다. 새로고침 후 다시 시도하세요.",
            )
            return
        try:
            settings = HarnessSettings.model_validate(body.get("settings"))
        except ValidationError as error:
            self._send_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "error": "validation_error",
                    "message": "입력값을 확인해 주세요.",
                    "details": _validation_details(error),
                },
            )
            return

        write_project_settings(settings, self.server.settings_file)
        self._send_json(
            HTTPStatus.OK,
            {
                "settings": settings.model_dump(mode="json"),
                "revision": settings_sha256(settings),
            },
        )

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        pickers = {
            "/api/pick-bgmusic": "bgmusic",
        }
        if path in pickers:
            if not self._authenticate_api():
                return
            if not self.server.picker_lock.acquire(blocking=False):
                self._send_error(HTTPStatus.CONFLICT, "picker_busy", "열려 있는 선택창을 닫은 뒤 다시 시도하세요.")
                return
            try:
                selected = choose_local_path(pickers[path])
                self._send_json(HTTPStatus.OK, {"path": selected, "cancelled": selected is None})
            except (RuntimeError, ValueError) as error:
                self._send_error(HTTPStatus.BAD_REQUEST, "picker_error", str(error))
            finally:
                self.server.picker_lock.release()
            return
        if path == "/api/speech-test":
            self._speech_test()
            return
        if path != "/api/shutdown":
            self._not_found()
            return
        if not self._authenticate_api():
            return
        self.server.shutdown_requested.set()
        self._send_json(HTTPStatus.OK, {"status": "closing"})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _speech_test(self) -> None:
        """Speak a sample with the unsaved settings on screen; nothing is written."""
        if not self._authenticate_api():
            return
        length = self._content_length()
        if length is None:
            return
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "요청이 너무 큽니다.")
            return
        try:
            body = json.loads(self.rfile.read(length))
            settings = HarnessSettings.model_validate(body.get("settings"))
            text = str(body.get("text") or "")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json", "올바른 JSON 요청이 아닙니다.")
            return
        except ValidationError as error:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {
                "error": "validation_error", "message": "입력값을 확인해 주세요.",
                "details": _validation_details(error)})
            return
        try:
            audio, seconds = self.server.speech_tester.speak(settings.voice, text)
        except Exception as error:  # model/ffmpeg failures are reported, not raised
            self._send_error(HTTPStatus.UNPROCESSABLE_ENTITY, "speech_test_failed", str(error))
            return
        self._send_json(HTTPStatus.OK, {
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "mime": "audio/mpeg",
            "seconds": round(seconds, 2),
        })

    def _authenticate_api(self) -> bool:
        host_matches = self.headers.get("Host") == self.server.allowed_host
        token_matches = (
            self.headers.get("X-Settings-Token") == self.server.session_token
        )
        origin = self.headers.get("Origin")
        referer = self.headers.get("Referer")
        same_origin = origin == self.server.allowed_origin or (
            origin is None
            and (
                (referer is not None and referer.startswith(self.server.allowed_origin + "/"))
                or self.headers.get("Sec-Fetch-Site") == "same-origin"
            )
        )
        if host_matches and token_matches and same_origin:
            return True
        self._send_error(
            HTTPStatus.FORBIDDEN,
            "forbidden",
            "이 설정 세션에서 보낸 요청만 허용됩니다.",
        )
        return False

    def _content_length(self) -> int | None:
        raw = self.headers.get("Content-Length")
        if raw is None:
            self._send_error(
                HTTPStatus.LENGTH_REQUIRED,
                "length_required",
                "요청 크기 정보가 필요합니다.",
            )
            return None
        try:
            length = int(raw)
        except ValueError:
            length = -1
        if length < 0:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "invalid_content_length",
                "요청 크기 정보가 올바르지 않습니다.",
            )
            return None
        return length

    def _serve_asset(self, path: str) -> None:
        filename, content_type = ASSETS[path]
        asset = WEB_ROOT / filename
        if not asset.is_file():
            self._not_found()
            return
        content = asset.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _not_found(self) -> None:
        self._send_error(
            HTTPStatus.NOT_FOUND,
            "not_found",
            "요청한 설정 화면 경로가 없습니다.",
        )

    def _send_error(self, status: HTTPStatus, error: str, message: str) -> None:
        self._send_json(status, {"error": error, "message": message})

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        content = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            .encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _validation_details(error: ValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for item in error.errors(include_url=False):
        path = ".".join(str(part) for part in item["loc"])
        raw_message = str(item["msg"])
        if not path and "voice maximum" in raw_message:
            path = "local_video.max_scene_seconds"
            message = "최대 음성 길이와 씬 사이 쉼의 합보다 커야 합니다."
        elif not path and "voice minimum" in raw_message:
            path = "voice.max_scene_seconds"
            message = "최소 음성 길이보다 크거나 같아야 합니다."
        elif not path and "local minimum" in raw_message:
            path = "local_video.max_scene_seconds"
            message = "최소 장면 길이보다 커야 합니다."
        elif item["type"] == "extra_forbidden":
            message = "지원하지 않는 설정 항목입니다."
        else:
            message = f"허용 범위와 형식을 확인하세요. ({raw_message})"
        presentation = CATALOG_BY_KEY.get(path)
        details.append(
            {
                "path": path or "settings",
                "label": presentation.label if presentation is not None else "설정",
                "message": message,
            }
        )
    return details


def create_server(
    *,
    settings_file: Path,
    token: str,
    port: int = 0,
) -> SettingsUiServer:
    if not token:
        raise ValueError("settings UI token must not be empty")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return SettingsUiServer(("127.0.0.1", port), settings_file, token)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="127.0.0.1에서 Video Generator 설정 화면을 엽니다."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="로컬 포트입니다. 기본값 0은 사용 가능한 포트를 자동 선택합니다.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="브라우저를 자동으로 열지 않고 URL만 표시합니다.",
    )
    parser.add_argument(
        "--settings-file",
        type=Path,
        default=PROJECT_SETTINGS_FILE,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    load_project_settings(arguments.settings_file)
    token = secrets.token_urlsafe(32)
    server = create_server(
        settings_file=arguments.settings_file,
        token=token,
        port=arguments.port,
    )
    host, port = server.server_address
    url = f"http://{host}:{port}/?token={quote(token)}"
    print(url, flush=True)
    if not arguments.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.speech_tester.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
