"""Native selectors for paths used by the local settings server."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

from .settings import PROJECT_ROOT

BGMUSIC_DIR = PROJECT_ROOT / "bgmusic"

PICKERS = {
    "bgmusic": 'choose file with prompt "배경음악 파일을 선택하세요" of type {"public.audio"}',
}


def _picker_script(kind: str) -> str:
    """Fixed application code; the only interpolated value is the project's own bgmusic/ path."""
    script = PICKERS[kind]
    if kind == "bgmusic":
        BGMUSIC_DIR.mkdir(parents=True, exist_ok=True)
        location = str(BGMUSIC_DIR).replace("\\", "\\\\").replace('"', '\\"')
        script += f' default location (POSIX file "{location}")'
    return script


def choose_local_path(kind: str) -> str | None:
    if kind not in PICKERS:
        raise ValueError("지원하지 않는 파일 선택 요청입니다.")
    if sys.platform != "darwin":
        raise RuntimeError("현재 파일 선택창은 macOS에서 지원합니다.")
    # All AppleScript is fixed application code; no request data is interpolated.
    script = ('try\nactivate\nset selectedItem to (' + _picker_script(kind)
              + ')\nreturn POSIX path of selectedItem\non error number -128\n'
                'return ""\nend try')
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True,
            timeout=300, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("파일 선택 시간이 지났습니다. 다시 선택하세요.") from error
    except OSError as error:
        raise RuntimeError("파일 선택창을 열 수 없습니다.") from error
    if result.returncode:
        raise RuntimeError("파일 선택창을 열 수 없습니다. 다시 시도하세요.")
    # osascript adds one newline; preserve whitespace in the selected filename.
    selected = result.stdout.removesuffix("\n")
    if not selected:
        return None
    path = Path(selected)
    if not path.is_absolute():
        raise ValueError("선택한 경로를 확인할 수 없습니다.")
    if kind == "bgmusic":
        if not path.is_file():
            raise ValueError("선택한 배경음악 파일이 없습니다.")
        # Settings store only the file name; a track picked elsewhere is copied into the library.
        target = BGMUSIC_DIR / path.name
        if path.resolve() != target.resolve():
            BGMUSIC_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        return path.name
    return str(path)
