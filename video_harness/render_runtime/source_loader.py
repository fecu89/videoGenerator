"""Load trusted run code under an isolated package, without writing bytecode.

This isolates module names, not permissions. Run scripts have the same authority
as other authored project code. Use relative imports for sibling scripts.
"""
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import types


class _SourceLoader(importlib.abc.SourceLoader):
    def __init__(self, path):
        self.path = path

    def get_filename(self, fullname):
        return str(self.path)

    def get_data(self, path):
        return Path(path).read_bytes()

    def set_data(self, path, data, **kwargs):
        pass  # Snapshot/source trees never receive pyc files.


class _RunFinder(importlib.abc.MetaPathFinder):
    def __init__(self, namespace, root):
        self.namespace, self.root = namespace, root

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.namespace + '.'):
            return None
        parts = fullname[len(self.namespace) + 1:].split('.')
        if parts[0] != 'scripts':
            raise ImportError('Run Python imports must stay under scripts/')
        candidate = self.root.joinpath(*parts)
        if candidate.is_dir():
            init = candidate / '__init__.py'
            if init.is_file():
                return importlib.util.spec_from_file_location(fullname, init, loader=_SourceLoader(init), submodule_search_locations=[str(candidate)])
            spec = importlib.util.spec_from_loader(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = [str(candidate)]
            return spec
        candidate = candidate.with_suffix('.py')
        if candidate.is_file():
            return importlib.util.spec_from_file_location(fullname, candidate, loader=_SourceLoader(candidate))
        return None


def load_source_symbol(snapshot_root: Path, reference: str, *, namespace: str):
    relative, symbol = reference.rsplit(':', 1)
    root = Path(snapshot_root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix != '.py':
        raise ValueError(f'Invalid Python source: {reference}')
    package = '_run_' + namespace
    if package not in sys.modules:
        module = types.ModuleType(package)
        module.__path__ = [str(root)]
        sys.modules[package] = module
        # Retain the scoped finder for lazy relative imports during rendering.
        # It never handles other modules or modifies sys.path.
        sys.meta_path.insert(0, _RunFinder(package, root))
    name = package + '.' + '.'.join(Path(relative).with_suffix('').parts)
    module = __import__(name, fromlist=[symbol])
    result = getattr(module, symbol)
    if not callable(result):
        raise ValueError(f'Source symbol is not callable: {reference}')
    return result
