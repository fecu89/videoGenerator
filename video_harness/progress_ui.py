"""Read-only, local render monitor. Polling runs in the browser, not the agent."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def signature(path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def describe_postprocess(command):
    """Describe observed work without inventing a percentage for FFmpeg/QA."""
    if '/shorts/' in command:
        return '쇼츠 만들기', '완성된 영상으로 언어별 세로 쇼츠를 만들고 있습니다.'
    if '/onlineReferences/' in command:
        return '장면별 참고 클립 만들기', '완성된 영상에서 장면별 클립을 추출하고 있습니다.'
    if '/previews/half-second/' in command:
        return '검사용 이미지 만들기', '영상 전 구간에서 이미지를 추출해 화면을 확인하고 있습니다.'
    if 'blackframe=' in command or 'framehash' in command:
        return '화면 품질 검사', '검은 화면과 장면 연결부의 멈춤을 확인하고 있습니다.'
    if 'ffprobe' in command:
        return '영상 길이·프레임 검사', '영상 파일을 읽으며 프레임 수와 음성 길이를 확인하고 있습니다.'
    if 'amix=' in command or '.m4a' in command or 'loudnorm=' in command:
        return '음성·배경음악 합치기', '나레이션과 배경음악, 언어별 음성을 정리하고 있습니다.'
    if '-f concat' in command or 'concat=' in command:
        return '영상 합치기', '렌더된 장면을 하나의 영상 파일로 합치고 있습니다.'
    if 'ffmpeg' in command:
        return '영상 파일 처리', '영상과 음성을 인코딩하고 저장하고 있습니다.'
    return '최종 후처리', '다음 처리 단계와 결과 파일을 확인하고 있습니다.'


class ProgressMonitor:
    def __init__(self, run, staging, pid, total, quality, *, alive=None):
        self.run, self.staging = Path(run), Path(staging)
        self.pid, self.total, self.quality = pid, total, quality
        self.video = self.run / ('final.mp4' if quality == 'final' else 'final-draft.mp4')
        self.language_videos = {}
        if (self.run / 'run-settings.json').is_file():
            from .localize import delivery_mode, final_name, language_outputs
            from .settings import resolve_run_settings
            settings = resolve_run_settings(self.run, persist=False)
            delivery = delivery_mode(settings)
            if delivery != 'audio_tracks':
                self.language_videos = {lang: self.run / final_name(lang, quality, delivery)
                                        for lang in language_outputs(settings)}
        self.report = self.run / 'pipeline-report.json'
        self.qa = self.run / ('qa-report.json' if quality == 'final' else 'videoFiles/sequences/draft/qa-report.json')
        self.initial = {p: signature(p) for p in (self.video, self.report, self.qa, *self.language_videos.values())}
        self.delivery_report = self.run / 'delivery-report.json'
        self.initial_delivery = signature(self.delivery_report)
        self.failure_report = self.run / 'production-failure.json'
        self.initial_failure = signature(self.failure_report)
        self.alive = alive or self.process_alive
        self.counts = {}
        self.process_identity = self.process_info()
        self.ended = False

    def process_info(self):
        result = subprocess.run(['ps', '-p', str(self.pid), '-o', 'lstart=', '-o', 'stat='], capture_output=True, text=True)
        return result.stdout.strip()

    def process_alive(self):
        current = self.process_info()
        return bool(current and current.rsplit(None, 1)[0] == self.process_identity.rsplit(None, 1)[0]
                    and not current.split()[-1].startswith('Z'))

    def upload(self):
        """Copy-ready titles and descriptions for the finished film; empty when they cannot be read."""
        from .upload_text import upload_sheet
        try:
            return upload_sheet(self.run)
        except (OSError, ValueError, KeyError) as error:
            return {'title': self.run.name, 'warnings': [f'업로드 문구를 만들지 못했습니다: {error}'], 'languages': []}

    def postprocess(self):
        result = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 2)
            if len(fields) == 3 and fields[1] == str(self.pid):
                return describe_postprocess(fields[2])
        return describe_postprocess('')

    def status(self):
        cache = self.staging / '.render-cache/sequences' / self.quality
        for log in cache.glob('*/blender-render.log'):
            try:
                # Only the tail is needed, even for hours-long renders.
                with log.open('rb') as source:
                    source.seek(max(0, log.stat().st_size - 65536))
                    frames = re.findall(rb'Saved:[^\n]*frame-(\d+)\.png', source.read())
                if frames:
                    self.counts[log.parent.name] = max(self.counts.get(log.parent.name, 0), int(frames[-1]) + 1)
            except OSError:
                pass  # Publication can move the staging directory between polls.
        completed = min(self.total, sum(self.counts.values()))
        self.ended = self.ended or not self.alive()
        state = 'finishing' if completed >= self.total else 'rendering'
        issues = []
        if self.ended:
            report, qa = read_json(self.report), read_json(self.qa)
            fresh = all(signature(p) is not None and signature(p) != self.initial[p] for p in self.initial)
            try:
                script_hash = hashlib.sha256((self.run / 'script.json').read_bytes()).hexdigest()
            except OSError:
                script_hash = None
            valid = (fresh and all(p.stat().st_size > 0 for p in (self.video, *self.language_videos.values())) and report.get('quality') == self.quality
                     and report.get('status') == 'complete' and qa.get('status') == 'passed'
                     and script_hash and report.get('script_sha256') == script_hash)
            state = 'complete' if valid else 'stopped'
            if not valid:
                staged_qa = read_json(self.staging / self.qa.relative_to(self.run))
                issues = staged_qa.get('issues', []) if staged_qa.get('status') == 'failed' else []
                if not issues and signature(self.failure_report) != self.initial_failure:
                    failure = read_json(self.failure_report)
                    if failure.get('pid') == self.pid and failure.get('quality') == self.quality:
                        issues = failure.get('issues') or [{'code': 'production_failed', 'message': failure.get('error', '제작 실패')}]
            if valid:
                completed = self.total
        stage, detail = self.postprocess() if state == 'finishing' else ('', '')
        delivery = read_json(self.delivery_report) if signature(self.delivery_report) != self.initial_delivery else {}
        if state == 'finishing' and delivery.get('status') in ('preparing', 'uploading'):
            stage = '완성 영상 업로드'
            done = sum(item.get('status') == 'uploaded' for item in delivery.get('items', []))
            detail = f'언어별 채널에 영상을 업로드하고 있습니다. 완료 {done}개'
        return {'state': state, 'completed_frames': completed, 'total_frames': self.total,
                'percent': round(100 * completed / self.total, 1), 'name': self.run.name,
                'quality': self.quality, 'sequences': self.counts.copy(), 'issues': issues,
                'stage': stage, 'detail': detail, 'delivery': delivery,
                'videos': [{'lang': lang, 'file': path.name, 'url': f'/videos/{lang}.mp4'}
                           for lang, path in self.language_videos.items()] if state == 'complete' else []}


def handler_for(monitor):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == '/api/status':
                self.send_data(json.dumps(monitor.status()).encode(), 'application/json')
            elif path == '/':
                self.send_data((Path(__file__).parent / 'progress_web/index.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/video.mp4' and monitor.status()['state'] == 'complete':
                self.send_video(monitor.video)
            elif (localized := re.fullmatch(r'/videos/([a-z-]{2,8})\.mp4', path)) and monitor.status()['state'] == 'complete':
                file = monitor.language_videos.get(localized[1])
                self.send_video(file) if file and file.is_file() else self.send_error(404)
            elif path == '/api/upload' and monitor.quality == 'final' and monitor.status()['state'] == 'complete':
                self.send_data(json.dumps(monitor.upload(), ensure_ascii=False).encode(), 'application/json')
            elif (short := re.fullmatch(r'/shorts/([a-z-]{2,8})\.mp4', path)) and monitor.status()['state'] == 'complete':
                from .shorts import SHORTS_DIR, shorts_name
                file = monitor.run / SHORTS_DIR / shorts_name(short[1], monitor.quality)
                self.send_video(file) if file.is_file() else self.send_error(404)
            else:
                self.send_error(404)

        def send_data(self, data, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def send_video(self, video):
            size = video.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                if not match:
                    self.send_error(416)
                    return
                start = int(match[1])
                end = min(int(match[2]), end) if match[2] else end
                if start > end:
                    self.send_error(416)
                    return
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with video.open('rb') as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description='실행 중인 렌더의 자동 갱신 로딩창')
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--staging', type=Path, required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--total-frames', type=int, required=True)
    parser.add_argument('--quality', choices=('draft', 'final'), default='final')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args(argv)
    if args.total_frames <= 0 or args.pid <= 0 or not args.run_directory.is_dir():
        parser.error('실행 폴더, 양수 PID와 전체 프레임 수가 필요합니다.')
    monitor = ProgressMonitor(args.run_directory.resolve(), args.staging.resolve(), args.pid, args.total_frames, args.quality)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(monitor))
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Render progress: {url}', flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
