"""Run-owned rendering inputs, content identity, and immutable input snapshots."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Literal

import jsonschema
from pydantic import Field, model_validator

from .models import StrictModel

ROOT = Path(__file__).resolve().parent
HELPERS = ('animated_materials.py', 'callout.py', 'callout_math.py', 'continuity_capture.py')


def _relative(value: str, directory: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or '\\' in value or '..' in path.parts or path.parts[:1] != (directory,) or str(path) != value:
        raise ValueError(f'Expected a relative {directory}/ path: {value}')
    return value


class RenderSourceSpec(StrictModel):
    engine: Literal['blender', 'threejs']
    entrypoint: str
    validator: str
    source_files: list[str] = Field(min_length=1)
    assets: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_paths(self):
        for path in self.source_files:
            _relative(path, 'scripts')
        for path in self.assets:
            _relative(path, 'assets')
        for ref, suffixes in ((self.entrypoint, ('.py',) if self.engine == 'blender' else ('.ts', '.js')),
                              (self.validator, ('.py',))):
            path, sep, name = ref.partition(':')
            if not sep or not re.fullmatch(r'[A-Za-z_]\w*', name) or path not in self.source_files or Path(path).suffix not in suffixes:
                raise ValueError(f'Entrypoint/validator must name a declared source file and exported symbol: {ref}')
        if len(set(self.source_files + self.assets)) != len(self.source_files + self.assets):
            raise ValueError('Duplicate source dependency')
        return self


class RenderSourceManifest(StrictModel):
    schema_version: Literal[1] = 1
    simulation_schema: str
    graphs: dict[str, RenderSourceSpec] = Field(min_length=1)

    @model_validator(mode='after')
    def check_schema(self):
        _relative(self.simulation_schema, 'scripts')
        return self


@dataclass(frozen=True)
class ResolvedRenderSource:
    run_dir: Path
    graph: str
    spec: RenderSourceSpec
    simulation_schema: Path
    # snapshot-relative name, original file, expected SHA256
    dependencies: tuple[tuple[str, Path, str], ...]
    sha256: str

    @property
    def files(self):
        return tuple(p for _, p, _ in self.dependencies)

    @property
    def namespace(self):
        return hashlib.sha256(f'{self.run_dir}:{self.graph}:{self.sha256}'.encode()).hexdigest()


def _file(root, relative):
    path = root / relative
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Missing or escaping render dependency: {relative}')
    return path


def _read_schema(path: Path):
    schema = json.loads(path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    def check(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'$ref', '$dynamicRef'} and not child.startswith('#'):
                    raise ValueError('Run simulation schema references must use local #/$defs entries')
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(schema)
    return schema


def runtime_files(engine: str):
    files = [(f'_harness/render_runtime/{p.name}', p) for p in sorted((ROOT / 'render_runtime').glob('*.py'))]
    files += [(f'_harness/{name}', ROOT / 'blender_renderer' / name) for name in HELPERS]
    files += [(f'_harness/{name}', ROOT / name) for name in ('render_sources.py', f'run_{engine}_backend.py') if (ROOT / name).exists()]
    if engine == 'threejs':
        renderer = ROOT / 'science_renderer'
        files += [(f'_harness/science_renderer/{p.relative_to(renderer)}', p) for p in sorted((renderer / 'src').rglob('*.ts'))]
        files += [(f'_harness/science_renderer/{name}', renderer / name) for name in ('package.json', 'package-lock.json', 'tsconfig.json')]
    return files


def simulation_input_path(run_dir: Path) -> Path:
    root = Path(run_dir).resolve()
    name = 'simulation.json'
    plan = root / 'local-sequence-plan.json'
    if plan.is_file():
        name = json.loads(plan.read_text()).get('simulation_config_file', name)
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name:
        raise ValueError(f'Invalid run simulation path: {name}')
    return _file(root, name)


def resolve_render_source(run_dir: Path, scene_graph: str, *, engine: str) -> ResolvedRenderSource | None:
    root = Path(run_dir).resolve()
    manifest_path = root / 'render-source.json'
    if not manifest_path.exists():
        return None
    manifest = RenderSourceManifest.model_validate_json(_file(root, 'render-source.json').read_text())
    # Validate the entire manifest even when this graph uses a builtin renderer.
    schema_path = _file(root, manifest.simulation_schema)
    _read_schema(schema_path)
    for spec in manifest.graphs.values():
        for name in spec.source_files + spec.assets:
            _file(root, name)
    spec = manifest.graphs.get(scene_graph)
    if spec is None:
        return None
    if spec.engine != engine:
        raise ValueError(f'{scene_graph}: manifest engine {spec.engine} differs from plan {engine}')
    files = [(n, _file(root, n)) for n in sorted(set(spec.source_files + spec.assets + [manifest.simulation_schema]))]
    if (root / 'simulation.json').exists() or (root / 'local-sequence-plan.json').exists():
        files.append(('_inputs/simulation.json', simulation_input_path(root)))
    if (root / 'run-settings.json').exists():
        files.append(('_inputs/run-settings.json', _file(root, 'run-settings.json')))
    files += runtime_files(engine)
    dependencies = tuple((n, p, hashlib.sha256(p.read_bytes()).hexdigest()) for n, p in sorted(files))
    identity = {'graph': scene_graph, 'spec': spec.model_dump(mode='json'),
                'schema': manifest.simulation_schema, 'files': [(n, h) for n, _, h in dependencies]}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return ResolvedRenderSource(root, scene_graph, spec, schema_path, dependencies, digest)


def assert_source_current(source: ResolvedRenderSource):
    current = resolve_render_source(source.run_dir, source.graph, engine=source.spec.engine)
    if current is None or current.sha256 != source.sha256:
        raise ValueError('Render source changed; regenerate and review the preview before rendering')


def create_source_snapshot(source: ResolvedRenderSource) -> Path:
    assert_source_current(source)
    parent = source.run_dir / '.render-cache/source-snapshots'
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / source.sha256
    if not destination.exists():
        staging = Path(tempfile.mkdtemp(prefix='.copy-', dir=parent))
        try:
            for name, path, expected in source.dependencies:
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError(f'Render source changed during snapshot: {name}')
                target.write_bytes(data)
            assert_source_current(source)
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    for name, _, expected in source.dependencies:
        target = _file(destination, name)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Render snapshot was modified: {name}')
    declared = {name for name, _, _ in source.dependencies}
    for path in destination.rglob('*'):
        relative = path.relative_to(destination)
        if relative.parts[0] != 'build' and path.is_file() and relative.as_posix() not in declared:
            raise ValueError(f'Undeclared file in render snapshot: {relative}')
    return destination


def validate_source_simulation(run_dir: Path, payload: dict):
    manifest = RenderSourceManifest.model_validate_json((run_dir / 'render-source.json').read_text())
    schema = _read_schema(_file(run_dir, manifest.simulation_schema))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as error:
        location = '.'.join(str(p) for p in error.absolute_path)
        raise ValueError(f'Run simulation {location}: {error.message}') from error


def run_source_policy_issues(source: ResolvedRenderSource) -> list[str]:
    patterns = {
        '.py': r"\b(self|g|gallery)\.text\(|\bcaption\(|\bhud\(|\btitle\(|^\s*LABELS\s*=|\bsmall\(",
        '.ts': r"\bthis\.text\(|\bfillText\(|titles\s*:\s*Record<string,\s*string\[\]>",
    }
    issues = []
    for name in source.spec.source_files:
        pattern = patterns.get(Path(name).suffix)
        if pattern and re.search(pattern, (source.run_dir / name).read_text(), re.M):
            issues.append(f'{name}: use CalloutLayer for planned text')
    return issues


def run_plan_source_issues(run_dir: Path, local=None) -> list[str]:
    if not (Path(run_dir) / 'render-source.json').exists():
        return []
    try:
        if local is None:
            from .sequence_plans import load_local_sequence_plan
            local = load_local_sequence_plan(Path(run_dir) / 'local-sequence-plan.json')
        issues = []
        for sequence in local.sequences:
            source = resolve_render_source(run_dir, sequence.scene_graph, engine=sequence.renderer or local.renderer)
            if source is not None:
                issues.extend(run_source_policy_issues(source))
        simulation = json.loads(simulation_input_path(run_dir).read_text())
        if simulation.get('preset') == 'run-scene':
            validate_source_simulation(Path(run_dir), simulation)
        return issues
    except (OSError, ValueError, jsonschema.SchemaError) as error:
        return [f'render_source_invalid: {error}']


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect run render sources without executing them')
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args(argv)
    try:
        path = args.run_directory / 'render-source.json'
        if not path.is_file():
            print(json.dumps({'legacy': True, 'graphs': {}}))
            return 0
        manifest = RenderSourceManifest.model_validate_json(path.read_text())
        result = {}
        for graph, spec in manifest.graphs.items():
            source = resolve_render_source(args.run_directory, graph, engine=spec.engine)
            result[graph] = {**spec.model_dump(), 'sha256': source.sha256,
                             'dependencies': [n for n, _, _ in source.dependencies]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, jsonschema.exceptions.SchemaError) as error:
        print(f'Render source: {error}')
        return 1
