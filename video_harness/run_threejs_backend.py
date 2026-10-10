"""Build trusted run TypeScript inside its input snapshot, then render natively."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
import subprocess

from .render_sources import assert_source_current, create_source_snapshot, resolve_render_source
from .render_runtime.source_loader import load_source_symbol
from .sequence_render import LocalSequenceRenderBackend
from .storage import atomic_write


class RunThreeJSSequenceRenderBackend(LocalSequenceRenderBackend):
    def __init__(self, source):
        super().__init__()
        self.source = source

    @property
    def version(self):
        current = resolve_render_source(self.source.run_dir, self.source.graph, engine='threejs')
        if current is None:
            raise ValueError('Render source manifest was removed')
        return 'run-threejs-source-v1-' + current.sha256

    def render_frames(self, job, cache_dir):
        assert_source_current(self.source)
        if job.get('scene_graph') != self.source.graph:
            raise ValueError('Job scene_graph differs from render source')
        snapshot = create_source_snapshot(self.source)
        validator = load_source_symbol(snapshot, self.source.spec.validator, namespace=self.source.namespace)
        prepared = {**job, 'output_directory': str(Path(cache_dir).resolve())}
        validator(prepared)
        create_source_snapshot(self.source)
        entrypoint, symbol = self.source.spec.entrypoint.rsplit(':', 1)
        build = snapshot / 'build'
        build.mkdir(exist_ok=True)
        bundle = build / 'browser.js'
        descriptor = build / 'descriptor.json'
        atomic_write(descriptor, json.dumps({'snapshot_root':str(snapshot), 'entrypoint':entrypoint,
            'export_name':symbol, 'output_path':str(bundle),
            'renderer_root':str(snapshot / '_harness/science_renderer')}) + '\n')
        # Always rebuild: an interrupted build or a modified bundle is not a cache hit.
        subprocess.run(['npm', 'exec', '--', 'tsx', 'src/build-run-source.ts', str(descriptor)],
                       cwd=self.renderer_dir, capture_output=True, text=True, check=True)
        prepared['run_source_bundle'] = str(bundle)
        prepared['run_source_asset_urls'] = {
            name: 'data:' + (mimetypes.guess_type(name)[0] or 'application/octet-stream') + ';base64,' +
                  base64.b64encode((snapshot / name).read_bytes()).decode()
            for name in self.source.spec.assets}
        version = self.version
        report_path = super().render_frames(prepared, Path(cache_dir))
        assert_source_current(self.source)
        create_source_snapshot(self.source)
        report = json.loads(report_path.read_text())
        if report.get('backend', {}).get('actual') != prepared.get('renderer_backend', 'swiftshader'):
            raise RuntimeError('Three.js render engine attestation differs from requested backend')
        if report.get('frame_count') != job['frame_count']:
            raise RuntimeError('Three.js frame count differs from job')
        report['renderer_version'] = version
        report['render_source_sha256'] = self.source.sha256
        atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        return report_path
