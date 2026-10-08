"""Blender MCP inspection and native background sequence rendering.

The desktop add-on uses NUL-delimited JSON, not HTTP. Rendering runs in a
separate Blender process so it cannot overwrite the user's open project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

from .storage import atomic_write


def renderer_modules(scene_graph: str) -> tuple[str, str]:
    if scene_graph == 'energy-transport-blender-v1':
        return 'energy_transport', 'EnergyTransportGallery'
    if scene_graph == 'typhoon-beta-blender-v1':
        return 'typhoon_beta', 'TyphoonBetaGallery'
    if scene_graph == 'saturn-rings-blender-v1':
        return 'saturn_rings', 'SaturnRingsGallery'
    if scene_graph == 'adiabatic-expansion-blender-v1':
        return 'adiabatic', 'AdiabaticGallery'
    if scene_graph == 'virial-galaxy-story-blender-v1':
        return 'virial_galaxy', 'VirialGalaxyStoryGallery'
    if scene_graph == 'transfer-equation-story-blender-v1':
        return 'transfer_equation_story', 'TransferEquationStoryGallery'
    if scene_graph == 'optical-depth-story-blender-v2':
        return 'optical_depth_story', 'OpticalDepthStoryGallery'
    if scene_graph == 'optical-depth-blender-v1':
        return 'optical_depth', 'OpticalDepthGallery'
    if scene_graph == 'phantom-jam-blender-v1':
        return 'phantom_jam', 'PhantomJamGallery'
    if scene_graph == 'coriolis-story-blender-v1':
        return 'coriolis_story', 'CoriolisStoryGallery'
    if scene_graph == 'vorticity-story-blender-v2':
        return 'vorticity_story', 'VorticityStoryGallery'
    if scene_graph == 'bonding-flow-blender-v2':
        return 'bonding_flow', 'BondingFlowGallery'
    if scene_graph == 'bonding-blender-v1':
        return 'bonding', 'BondingGallery'
    if scene_graph == 'vorticity-blender-v1':
        return 'vorticity', 'VorticityGallery'
    if scene_graph == 'sun-earth-moon-blender-v1':
        return 'eclipse', 'EclipseGallery'
    if scene_graph == 'stellar-spectra-blender-v1':
        return 'scene', 'SpectralGallery'
    raise ValueError(f'Unsupported Blender scene_graph: {scene_graph}')


def validate_blender_job(job: dict) -> None:
    renderer_modules(job.get('scene_graph'))
    if job['scene_graph'] == 'energy-transport-blender-v1':
        from .blender_renderer.energy_transport_math import validate_job
    elif job['scene_graph'] == 'typhoon-beta-blender-v1':
        from .blender_renderer.typhoon_beta_math import validate_job
    elif job['scene_graph'] == 'saturn-rings-blender-v1':
        from .blender_renderer.saturn_rings_math import validate_job
    elif job['scene_graph'] == 'adiabatic-expansion-blender-v1':
        from .blender_renderer.adiabatic_math import validate_job
    elif job['scene_graph'] == 'virial-galaxy-story-blender-v1':
        from .blender_renderer.virial_galaxy_math import validate_job
    elif job['scene_graph'] == 'transfer-equation-story-blender-v1':
        from .blender_renderer.transfer_equation_story_math import validate_job
    elif job['scene_graph'] == 'optical-depth-story-blender-v2':
        from .blender_renderer.optical_depth_story_math import validate_job
    elif job['scene_graph'] == 'optical-depth-blender-v1':
        from .blender_renderer.optical_depth_math import validate_job
    elif job['scene_graph'] == 'phantom-jam-blender-v1':
        from .blender_renderer.phantom_jam_math import validate_job
    elif job['scene_graph'] == 'coriolis-story-blender-v1':
        from .blender_renderer.coriolis_story_math import validate_job
    elif job['scene_graph'] == 'vorticity-story-blender-v2':
        from .blender_renderer.vorticity_story_math import validate_job
    elif job['scene_graph'] in {'bonding-blender-v1', 'bonding-flow-blender-v2'}:
        from .blender_renderer.bonding_math import validate_job
    elif job['scene_graph'] == 'vorticity-blender-v1':
        from .blender_renderer.vorticity_math import validate_job
    elif job['scene_graph'] == 'sun-earth-moon-blender-v1':
        from .blender_renderer.eclipse_math import validate_job
    else:
        from .blender_renderer.spectra import validate_job
    validate_job(job)


class BlenderMCPClient:
    def __init__(self, host: str = 'localhost', port: int = 9876, timeout: float = 30):
        if host not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Blender MCP must use a loopback host')
        self.host, self.port, self.timeout = host, port, timeout

    def execute(self, code: str) -> dict:
        request = json.dumps({'type':'execute', 'code':code, 'strict_json':True}).encode() + b'\0'
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
            connection.sendall(request)
            data = bytearray()
            while b'\0' not in data:
                chunk = connection.recv(65536)
                if not chunk:
                    raise RuntimeError('Blender MCP closed without a complete response')
                data.extend(chunk)
                if len(data) > 16 * 1024 * 1024:
                    raise RuntimeError('Blender MCP response exceeds 16 MiB')
        response = json.loads(data.split(b'\0', 1)[0])
        if response.get('status') != 'ok':
            raise RuntimeError(response.get('message', 'Blender MCP failed'))
        result = response.get('result')
        if not isinstance(result, dict):
            raise RuntimeError('Blender MCP returned an invalid result')
        return result

    def status(self) -> dict:
        return self.execute("import bpy; result = {'version': bpy.app.version_string, "
            "'binary': bpy.app.binary_path, 'filepath': bpy.data.filepath, "
            "'scene': bpy.context.scene.name, 'objects': len(bpy.data.objects)}")

    def prepare_scene(self, job: dict, destination: Path) -> dict:
        """Build an additional scene in the desktop app, save a copy, no render."""
        validate_blender_job(job)
        module_name, class_name = renderer_modules(job['scene_graph'])
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        job_path=destination.with_suffix('.job.json')
        atomic_write(job_path,json.dumps(job,ensure_ascii=False,indent=2)+'\n')
        renderer_root = str(Path(__file__).resolve().parent / 'blender_renderer')
        code = (
            f"import sys, json, bpy\nsys.path.insert(0, {renderer_root!r})\n"
            "from pathlib import Path\n"
            f"import importlib, {module_name}\nimportlib.reload({module_name})\n"
            f"gallery = {module_name}.{class_name}(json.loads(Path({str(job_path)!r}).read_text()))\n"
            "gallery.bake()\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={str(destination)!r}, copy=True)\n"
            "for screen in bpy.data.screens:\n"
            "    for area in screen.areas:\n"
            "        if area.type == 'VIEW_3D':\n"
            "            area.spaces.active.region_3d.view_perspective = 'CAMERA'\n"
            "result = {'scene': gallery.scene.name, 'objects': len(gallery.scene.objects), "
            f"'blend_file': {str(destination)!r}, 'frames': gallery.scene.frame_end, 'rendered': False}}"
        )
        return self.execute(code)


def blender_binary() -> Path:
    candidates = [os.environ.get('VG_BLENDER_BINARY'), shutil.which('blender'),
                  '/Applications/Blender.app/Contents/MacOS/Blender']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError('Blender is missing; set VG_BLENDER_BINARY to its executable')


class BlenderSequenceRenderBackend:
    def __init__(self):
        self.renderer_dir = Path(__file__).parent / 'blender_renderer'

    @property
    def version(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(p for p in self.renderer_dir.rglob('*')
                           if p.is_file() and p.suffix in {'.py', '.png', '.jpg'}):
            digest.update(str(path.relative_to(self.renderer_dir)).encode())
            digest.update(path.read_bytes())
        binary = blender_binary()
        digest.update(str(binary).encode())
        digest.update(str(binary.stat().st_mtime_ns).encode())
        return 'blender-eevee-v1-' + digest.hexdigest()

    def check_dependencies(self) -> None:
        blender_binary()
        for command in ('ffmpeg', 'ffprobe'):
            if not shutil.which(command):
                raise RuntimeError(f'Missing {command}')

    def render_frames(self, job: dict, cache_dir: Path) -> Path:
        validate_blender_job(job)
        cache_dir = cache_dir.resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        job = {**job, 'output_directory': str(cache_dir)}
        job_path = cache_dir / 'render-job.json'
        atomic_write(job_path, json.dumps(job, ensure_ascii=False, indent=2) + '\n')
        with (cache_dir / 'blender-render.log').open('w') as log:
            completed = subprocess.run([str(blender_binary()), '--background', '--factory-startup',
                '--python-exit-code', '1', '--python', str(self.renderer_dir / 'worker.py'),
                '--', str(job_path)], stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode:
            tail = (cache_dir / 'blender-render.log').read_text(errors='replace')[-4000:]
            raise RuntimeError(f'Blender render failed ({completed.returncode}):\n{tail}')
        report_path = cache_dir / 'frame-report.json'
        if not report_path.is_file():
            raise RuntimeError('Blender did not write frame-report.json')
        report = json.loads(report_path.read_text())
        if report.get('backend', {}).get('actual') != 'blender_eevee':
            raise RuntimeError('Blender render engine attestation is missing')
        requested = sorted({int(i) for i in job.get('sample_frames') or range(job['frame_count'])})
        if len(report.get('frames', [])) != len(requested):
            raise RuntimeError('Blender frame count differs from job')
        for frame in requested:
            path = cache_dir / f'frame-{frame:06d}.png'
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f'Missing Blender frame: {path}')
        if not (cache_dir / 'scene.blend').is_file():
            raise RuntimeError('Blender did not save its editable scene')
        return report_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Inspect the local Blender MCP connection')
    parser.add_argument('action', choices=['status', 'prepare'])
    parser.add_argument('run_directory', type=Path, nargs='?')
    parser.add_argument('--port', type=int, default=9876)
    args = parser.parse_args(argv)
    try:
        client = BlenderMCPClient(port=args.port, timeout=300)
        if args.action == 'status':
            result = client.status()
        else:
            if args.run_directory is None:
                raise ValueError('prepare requires a run directory')
            from .pipeline import load_pipeline_context, validate_pipeline_inputs
            from .settings import resolve_run_settings
            from .sequence_render import _canonical_state_cache
            from .simulation import load_simulation
            context=load_pipeline_context(args.run_directory)
            issues=validate_pipeline_inputs(context,resolve_run_settings(args.run_directory))
            if issues: raise ValueError(f'Invalid production inputs: {issues}')
            sequences=[s for s in context.local.sequences if (s.renderer or context.local.renderer)=='blender']
            if not sequences: raise ValueError('Plan does not select Blender')
            for sequence in sequences:
                destination=args.run_directory/'blender'/f'{sequence.sequence_id}-editable.blend'
                if destination.exists():raise FileExistsError(destination)
            simulation=load_simulation(context.run_dir,context.script)
            prepared=[]
            for sequence in sequences:
                job=dict(sequence_id=sequence.sequence_id,scene_graph=sequence.scene_graph,
                    frame_count=sequence.duration_frames,duration_frames=sequence.duration_frames,
                    canonical_fps=context.local.defaults.fps,
                    output=dict(width=context.local.defaults.width,height=context.local.defaults.height,fps=context.local.defaults.fps),
                    timeline=[beat.model_dump(mode='json') for beat in sequence.timeline],
                    canonical_state_cache=_canonical_state_cache(sequence),style=simulation.style.model_dump(mode='json'))
                destination=args.run_directory/'blender'/f'{sequence.sequence_id}-editable.blend'
                prepared.append(client.prepare_scene(job,destination))
            result=prepared[0] if len(prepared)==1 else {'sequences':prepared,'rendered':False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Blender: {error}')
        return 1
    return 0
