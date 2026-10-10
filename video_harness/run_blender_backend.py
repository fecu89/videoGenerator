"""Run-source and settings-aware Blender execution, leaving legacy hashes intact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from .blender_backend import BlenderSequenceRenderBackend, blender_binary, renderer_modules, validate_blender_job
from .render_sources import assert_source_current, create_source_snapshot, resolve_render_source, runtime_files
from .render_runtime.source_loader import load_source_symbol
from .settings import HarnessSettings, resolve_run_settings
from .storage import atomic_write

RUNTIME = Path(__file__).parent / 'render_runtime'


class ConfiguredBlenderSequenceRenderBackend(BlenderSequenceRenderBackend):
    def __init__(self, *, settings=None, run_dir=None):
        super().__init__()
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.settings = settings or resolve_run_settings(self.run_dir)

    def current_settings(self):
        return resolve_run_settings(self.run_dir) if self.run_dir is not None else self.settings

    def blender_settings(self):
        value = getattr(self.current_settings(), 'blender', None)
        # Explicit opt-in run sources on old runs keep the previous 512 MB default.
        return value.model_dump(mode='json') if value is not None else {'shadow_pool_mb': 512}

    @property
    def version(self):
        digest = hashlib.sha256(super().version.encode())
        for name, path in runtime_files('blender'):
            digest.update(name.encode()); digest.update(path.read_bytes())
        digest.update(json.dumps(self.blender_settings(), sort_keys=True).encode())
        return 'blender-eevee-v2-' + digest.hexdigest()

    def prepare_job(self, job):
        validate_blender_job(job)
        module, symbol = renderer_modules(job['scene_graph'])
        return {**job, 'blender_settings': self.blender_settings(),
                'builtin_source': {'root': str(self.renderer_dir.resolve()), 'module': module, 'symbol': symbol}}

    def worker_path(self, job):
        if 'run_source' in job:
            return Path(job['run_source']['snapshot_root']) / '_harness/render_runtime/blender_worker.py'
        return RUNTIME / 'blender_worker.py'

    def assert_current(self):
        pass

    def render_frames(self, job, cache_dir):
        self.assert_current()
        version = self.version
        cache_dir = Path(cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        prepared = {**self.prepare_job(job), 'output_directory': str(cache_dir), 'renderer_version': version}
        job_path = cache_dir / 'render-job.json'
        atomic_write(job_path, json.dumps(prepared, ensure_ascii=False, indent=2) + '\n')
        with (cache_dir / 'blender-render.log').open('w') as log:
            completed = subprocess.run([str(blender_binary()), '--background', '--factory-startup',
                '--python-exit-code', '1', '--python', str(self.worker_path(prepared)), '--', str(job_path)],
                stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            tail = (cache_dir / 'blender-render.log').read_text(errors='replace')[-4000:]
            raise RuntimeError(f'Blender render failed ({completed.returncode}):\n{tail}')
        self.assert_current()
        if version != self.version:
            raise ValueError('Render inputs changed during rendering; output cannot be accepted')
        report_path = cache_dir / 'frame-report.json'
        report = json.loads(report_path.read_text())
        if report.get('backend', {}).get('actual') != 'blender_eevee':
            raise RuntimeError('Blender render engine attestation is missing')
        if report.get('blender_settings') != prepared['blender_settings']:
            raise RuntimeError('Blender Shadow Pool attestation differs from requested settings')
        if report.get('renderer_version') != version:
            raise RuntimeError('Blender renderer version attestation differs from source')
        from .blender_renderer.callout_math import select_sample_frames
        selected = select_sample_frames(prepared)
        if len(report.get('frames', [])) != len(selected) or report.get('sample_frames') != selected:
            raise RuntimeError('Blender frame count differs from job')
        for frame in selected:
            path = cache_dir / f'frame-{frame:06d}.png'
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f'Missing Blender frame: {path}')
        if not (cache_dir / 'scene.blend').is_file():
            raise RuntimeError('Blender did not save its editable scene')
        return report_path

    def prepare_scene(self, job, destination, client):
        self.assert_current()
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        prepared = self.prepare_job(job)
        prepared['renderer_version'] = self.version
        path = destination.with_suffix('.job.json')
        atomic_write(path, json.dumps(prepared, ensure_ascii=False, indent=2) + '\n')
        # A long-lived desktop process may already hold helpers from another
        # snapshot. Temporarily install this snapshot's modules and import path.
        code = ("import runpy, json, bpy, sys\nfrom pathlib import Path\n"
                "def _prepare_run_scene():\n"
                "    prefixes = ('render_runtime', 'callout', 'callout_math', 'continuity_capture', 'animated_materials')\n"
                "    owned = lambda name: any(name == p or name.startswith(p + '.') for p in prefixes)\n"
                "    saved = {name: value for name, value in sys.modules.items() if owned(name)}\n"
                "    previous_path, previous_bytecode = list(sys.path), sys.dont_write_bytecode\n"
                "    for name in saved: del sys.modules[name]\n"
                "    try:\n"
                f"        runtime = runpy.run_path({str(self.worker_path(prepared))!r})\n"
                f"        job = json.loads(Path({str(path)!r}).read_text())\n"
                "        gallery, applied = runtime['build_gallery'](job)\n"
                f"        bpy.ops.wm.save_as_mainfile(filepath={str(destination)!r}, copy=True)\n"
                f"        return {{'scene': gallery.scene.name, 'blend_file': {str(destination)!r}, "
                "'rendered': False, 'blender_settings': applied, 'renderer_version': job['renderer_version']}\n"
                "    finally:\n"
                "        sys.path[:] = previous_path\n"
                "        sys.dont_write_bytecode = previous_bytecode\n"
                "        for name in list(sys.modules):\n"
                "            if owned(name): del sys.modules[name]\n"
                "        sys.modules.update(saved)\n"
                "result = _prepare_run_scene()\n")
        result = client.execute(code)
        self.assert_current()
        return result


class RunBlenderSequenceRenderBackend(ConfiguredBlenderSequenceRenderBackend):
    def __init__(self, source, *, settings=None):
        super().__init__(settings=settings or resolve_run_settings(source.run_dir))
        self.source = source

    def current_settings(self):
        if (self.source.run_dir / 'run-settings.json').is_file():
            return resolve_run_settings(self.source.run_dir)
        return self.settings

    @property
    def version(self):
        source = resolve_render_source(self.source.run_dir, self.source.graph, engine='blender')
        if source is None:
            raise ValueError('Render source manifest was removed')
        binary = blender_binary()
        inputs = (source.sha256, str(binary), binary.stat().st_mtime_ns, self.blender_settings())
        return 'run-blender-source-v1-' + hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()

    def assert_current(self):
        create_source_snapshot(self.source)

    def prepare_job(self, job):
        if job.get('scene_graph') != self.source.graph:
            raise ValueError('Job scene_graph differs from render source')
        snapshot = create_source_snapshot(self.source)
        validator = load_source_symbol(snapshot, self.source.spec.validator, namespace=self.source.namespace)
        prepared = {**job, 'blender_settings': self.blender_settings(),
                    'run_source': {'snapshot_root': str(snapshot), 'namespace': self.source.namespace,
                                   'entrypoint': self.source.spec.entrypoint, 'sha256': self.source.sha256},
                    'assets': {n: str(snapshot / n) for n in self.source.spec.assets}}
        validator(prepared)
        create_source_snapshot(self.source)
        return prepared


def prepare_run_blender_scene(job, destination, source, client):
    return RunBlenderSequenceRenderBackend(source).prepare_scene(job, destination, client)
