"""Reusable local preview review: fixed web assets, run-specific JSON and feedback."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import secrets
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .storage import atomic_write

WEB_ROOT = Path(__file__).with_name('review_web')
SOURCE_FILES = ('script.json', 'production-plan.json', 'local-sequence-plan.json', 'preview-report.json')
FEEDBACK_FILE = 'preview-feedback.json'
REGENERATION_FILE = 'preview-regeneration-request.json'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def revision(run, mode='preview'):
    digest = hashlib.sha256()
    names = SOURCE_FILES if mode == 'preview' else ('script.json', 'story-review.md', 'story.md')
    for name in names:
        if mode == 'story' and not (run / name).exists():
            continue
        digest.update(name.encode())
        digest.update((run / name).read_bytes())
    return digest.hexdigest()


def media_path(run, name):
    path = (run / name).resolve()
    if not path.is_relative_to(run.resolve()) or not path.is_file():
        raise ValueError('프로젝트 내부의 미디어 파일만 열 수 있습니다.')
    if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.mp3', '.mp4', '.wav', '.m4a'}:
        raise ValueError('지원하지 않는 미디어 파일입니다.')
    return path


def build_review(run, mode='preview'):
    run = Path(run).resolve()
    if mode == 'preview':
        script, production, local, report = [read_json(run / n) for n in SOURCE_FILES]
    else:
        script = read_json(run / 'script.json')
        production, local, report = {}, {'sequences': [], 'defaults': {'fps': 30}}, {'sequences': []}
    reports = {s['sequence_id']: s for s in report['sequences']}
    beats = {b['beat_id']: b for b in production.get('visual_beats', [])}
    scenes = []
    fps = local['defaults']['fps']
    for scene in script['scenes']:
        row = {k: scene.get(k) for k in ('scene_id', 'title', 'narration', 'duration_seconds')}
        row.update(shots=[], frames=[], audio=None)
        row['visual_subject'] = scene.get('visual_subject', '')
        row['sentence_pauses'] = scene.get('sentence_pauses', [])
        if scene.get('audio_file'):
            try:
                media_path(run, scene['audio_file'])
                row['audio'] = '/media/' + quote(scene['audio_file'])
            except ValueError:
                pass
        for sequence in local['sequences']:
            spans = [s for s in sequence['scene_spans'] if s['scene_id'] == scene['scene_id']]
            for span in spans:
                for b in sequence['timeline']:
                    if b['end_frame'] <= span['start_frame'] or b['start_frame'] >= span['end_frame']:
                        continue
                    options = b.get('controller_options', {})
                    row['shots'].append(dict(
                        id=b['beat_id'],
                        start=max(0, b['start_frame'] - span['start_frame']) / fps,
                        end=(min(b['end_frame'], span['end_frame']) - span['start_frame']) / fps,
                        direction=options.get('review_visual_description', beats.get(b['beat_id'], {}).get('primary_event', '연출 설명 없음')),
                        camera=options.get('review_camera_movement', ''),
                        framing=options.get('review_framing', ''),
                    ))
                rendered = reports.get(sequence['sequence_id'], {})
                for file, state in zip(rendered.get('frames', []), rendered.get('state_samples', [])):
                    frame = state['canonical_frame']
                    if span['start_frame'] <= frame < span['end_frame']:
                        media_path(run, file)
                        beat = next((b for b in sequence['timeline'] if b['start_frame'] <= frame < b['end_frame']), {})
                        row['frames'].append(dict(url='/media/' + quote(file), time=(frame - span['start_frame']) / fps, beat_id=beat.get('beat_id')))
        row['frames'].sort(key=lambda f: f['time'])
        scenes.append(row)
    feedback_path = run / ('story-feedback.json' if mode == 'story' else FEEDBACK_FILE)
    feedback = read_json(feedback_path) if feedback_path.exists() else None
    current = revision(run, mode)
    stale = bool(feedback and feedback.get('revision') != current)
    previous_feedback = feedback if stale else None
    if stale:
        # Retain the original file until the next save, but don't resubmit old
        # change requests against newly rendered material.
        feedback = {'comments': {}, 'overall': '', 'visual_brief': feedback.get('visual_brief', '')}
    title = script.get('selected_topic') or run.name
    if isinstance(title, dict):
        title = title.get('title', run.name)
    story = next((p.read_text(encoding='utf-8') for p in (run / 'story-review.md', run / 'story.md') if p.exists()), '')
    return dict(title=title, run=run.name, revision=current, mode=mode, story=story,
                scenes=scenes, feedback=feedback, feedback_stale=stale, previous_feedback=previous_feedback,
                regeneration=read_json(run / REGENERATION_FILE) if mode == 'preview' and (run / REGENERATION_FILE).exists() else None,
                text_gate=read_json(run / 'text-preview-gate.json').get('status') if (run / 'text-preview-gate.json').exists() else 'unchecked')


def save_feedback(run, payload, mode='preview'):
    request_path = run / REGENERATION_FILE
    if payload.get('action') == 'regenerate' and mode == 'preview' and request_path.exists():
        existing = read_json(request_path)
        previous = existing.get('feedback', {})
        if existing.get('status') in ('queued', 'applying', 'rendering') and all(
                previous.get(k, {} if k == 'comments' else '') == payload.get(k, {} if k == 'comments' else '')
                for k in ('revision', 'comments', 'overall', 'visual_brief')):
            return {**previous, 'regeneration': existing}
    if payload.get('revision') != revision(run, mode):
        raise ValueError('대본이나 프리뷰가 변경되었습니다. 새로고침한 뒤 수정 의견을 확인해 주세요.')
    ids = {str(s['scene_id']) for s in read_json(run / 'script.json')['scenes']}
    comments = payload.get('comments')
    if not isinstance(comments, dict) or any(k not in ids or not isinstance(v, str) or len(v) > 10000 for k, v in comments.items()):
        raise ValueError('장면별 수정 의견을 확인해 주세요.')
    overall = payload.get('overall', '')
    if not isinstance(overall, str) or len(overall) > 10000:
        raise ValueError('전체 의견은 10,000자 이내로 입력해 주세요.')
    brief = payload.get('visual_brief', '')
    if not isinstance(brief, str) or len(brief) > 20000:
        raise ValueError('영상 아이디어는 20,000자 이내로 입력해 주세요.')
    record = dict(schema_version=1, revision=payload['revision'], status='changes_requested',
                  saved_at=datetime.now(timezone.utc).isoformat(), comments=comments, overall=overall, visual_brief=brief)
    action = payload.get('action')
    has_changes = any(v.strip() for v in comments.values()) or bool(overall.strip())
    if action == 'approve' and has_changes:
        raise ValueError('수정 의견이 남아 있어 승인할 수 없습니다. «수정 반영 후 프리뷰 다시 만들기»를 눌러 주세요.')
    if action == 'regenerate':
        if mode != 'preview':
            raise ValueError('프리뷰 검토 화면에서 재생성을 요청해 주세요.')
        existing = read_json(run / REGENERATION_FILE) if (run / REGENERATION_FILE).exists() else None
        if existing and existing.get('status') in ('queued', 'applying', 'rendering'):
            previous = existing.get('feedback', {})
            if all(previous.get(k, '' if k != 'comments' else {}) == record[k] for k in ('revision', 'comments', 'overall', 'visual_brief')):
                return {**previous, 'regeneration': existing}
            raise ValueError('이미 프리뷰 재생성 요청을 처리하고 있습니다.')
    if action == 'approve':
        if mode == 'preview':
            request = read_json(run / REGENERATION_FILE) if (run / REGENERATION_FILE).exists() else None
            if request and request.get('status') in ('queued', 'applying', 'rendering'):
                raise ValueError('프리뷰 재생성 중에는 승인할 수 없습니다. 새 프리뷰를 확인한 뒤 승인해 주세요.')
            from .stage_approvals import approve_preview
            from .video_plan_approval import require_current_video_plan_approval
            require_current_video_plan_approval(run)
            approve_preview(run)
        else:
            from .creative_gates import require_story_chain
            require_story_chain(run)
            atomic_write(run / 'story-approval.json', json.dumps(dict(
                schema_version=1, approved_at=record['saved_at'], revision=record['revision'],
                script_sha256=hashlib.sha256((run / 'script.json').read_bytes()).hexdigest(),
                source='story-ui'), ensure_ascii=False, indent=2) + '\n')
        record['status'] = 'approved'
    elif action not in (None, 'save', 'request_changes', 'regenerate'):
        raise ValueError('지원하지 않는 검토 동작입니다.')
    filename = 'story-feedback.json' if mode == 'story' else FEEDBACK_FILE
    destination = run / filename
    if destination.exists():
        previous = destination.read_bytes()
        history = run / 'review-history' / f'{Path(filename).stem}-{hashlib.sha256(previous).hexdigest()}.json'
        history.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(history, previous.decode('utf-8'))
    atomic_write(destination, json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    if record['status'] == 'changes_requested' and (any(v.strip() for v in comments.values()) or overall.strip()):
        # A newly requested edit revokes the earlier approval, even if the
        # source files have not been edited by the agent yet.
        approval = run / ('story-approval.json' if mode == 'story' else 'preview-approval.json')
        if approval.exists():
            previous = approval.read_bytes()
            archive = run / 'review-history' / f'{approval.stem}-{hashlib.sha256(previous).hexdigest()}.json'
            archive.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(archive, previous.decode('utf-8'))
            approval.unlink()
    if action == 'regenerate':
        request = dict(schema_version=1, request_id=secrets.token_hex(12), status='queued',
                       requested_at=record['saved_at'], source_revision=record['revision'],
                       feedback=dict(record), message='수정 반영 대기 중')   # a copy: the reply nests this request
        atomic_write(run / REGENERATION_FILE, json.dumps(request, ensure_ascii=False, indent=2) + '\n')
        record['regeneration'] = request
    return record


def update_regeneration(run, status, message):
    """Agent applies edits first; the preview renderer then tracks its own stage."""
    path = Path(run) / REGENERATION_FILE
    if not path.exists():
        return
    request = read_json(path)
    if request.get('status') not in ('queued', 'applying', 'rendering'):
        return
    request.update(status=status, message=message, updated_at=datetime.now(timezone.utc).isoformat())
    if status == 'completed':
        request['result_revision'] = revision(Path(run))
    atomic_write(path, json.dumps(request, ensure_ascii=False, indent=2) + '\n')


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, run, port=0, mode='preview'):
        self.run = Path(run).resolve()
        self.mode = mode
        build_review(self.run, mode)
        self.token = secrets.token_urlsafe(24)
        self.save_lock = threading.Lock()
        super().__init__(('127.0.0.1', port), ReviewHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, data, kind='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') == urlsplit(self.server.origin).netloc

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': '허용되지 않은 호스트입니다.'})
        path = unquote(urlsplit(self.path).path)
        try:
            if path == '/api/review':
                return self.send(200, {**build_review(self.server.run, self.server.mode), 'token': self.server.token})
            if path == '/api/regeneration':
                request = self.server.run / REGENERATION_FILE
                return self.send(200, read_json(request) if request.exists() else None)
            if path.startswith('/media/'):
                target = media_path(self.server.run, path[len('/media/'):])
            elif path in ('/', '/review.css', '/review.js'):
                target = WEB_ROOT / ('index.html' if path == '/' else path[1:])
            else:
                return self.send(404, {'error': '페이지를 찾을 수 없습니다.'})
            return self.send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        except (OSError, ValueError, KeyError) as error:
            return self.send(400, {'error': str(error)})

    def do_POST(self):
        if (not self.valid_host() or self.headers.get('Origin') != self.server.origin
                or self.headers.get('X-Review-Token') != self.server.token):
            return self.send(403, {'error': '검토 화면에서 다시 저장해 주세요.'})
        if self.path != '/api/feedback':
            return self.send(404, {'error': '요청을 찾을 수 없습니다.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                raise ValueError('요청 크기를 확인해 주세요.')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('수정 의견 형식을 확인해 주세요.')
            with self.server.save_lock:
                result = save_feedback(self.server.run, payload, self.server.mode)
            print(f'검토 입력 저장: {self.server.mode}-feedback.json ({result["status"]})', flush=True)
            # An approval or a rebuild request ends this review: tell the page to close
            # and stop serving, so the waiting agent is released like the settings screen does.
            rebuild = payload.get('action') == 'regenerate'
            closing = result['status'] == 'approved' or rebuild
            self.send(200, {**result, 'closing': closing})
            if closing:
                print('프리뷰 재생성 요청: 검토 화면을 닫습니다.' if rebuild else '승인 완료: 검토 화면을 닫습니다.', flush=True)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
        except (ValueError, OSError) as error:
            self.send(400, {'error': str(error)})


def serve_review(run, *, port=0, open_browser=True, mode='preview'):
    server = ReviewServer(run, port, mode)
    print(f'{"대본" if mode == "story" else "프리뷰"} 검토: {server.origin}', flush=True)
    if open_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None, *, mode='preview'):
    parser = argparse.ArgumentParser(description='대본·영상대본·프리뷰를 함께 검토하고 수정 의견을 저장합니다.')
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args(argv)
    return serve_review(args.run_directory, port=args.port, open_browser=not args.no_open, mode=mode)


def story_main(argv=None):
    return main(argv, mode='story')


if __name__ == '__main__':
    raise SystemExit(main())
