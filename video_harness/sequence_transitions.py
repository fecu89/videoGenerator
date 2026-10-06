"""Composite short incoming transitions without moving any narration boundaries."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from .storage import atomic_write

STYLES = {'fade', 'smoothleft', 'smoothright', 'smoothup', 'smoothdown', 'circleopen', 'zoomin'}


def apply_entry_transitions(job: dict, report_path: Path, *, previous_frame: Path | None = None) -> None:
    entries = [(beat, beat.get('controller_options', {}).get('entry_transition')) for beat in job['timeline']]
    entries = [(beat, transition) for beat, transition in entries if transition]
    for _, transition in entries:
        if transition['style'] not in STYLES:
            raise ValueError(f"unsupported entry transition: {transition['style']}")
        if not 0 < transition['duration_seconds'] <= 1:
            raise ValueError('entry transition duration must be in (0, 1]')
    if not entries:
        return
    report = json.loads(report_path.read_text())
    frames = [Path(p) if Path(p).is_absolute() else report_path.parent / p for p in report['frames']]
    fps = job['output']['fps']
    for beat, transition in entries:
        start = math.ceil(beat['start_frame'] * fps / job['canonical_fps'])
        end = min(len(frames), math.ceil(beat['end_frame'] * fps / job['canonical_fps']))
        count = min(end - start, math.ceil(transition['duration_seconds'] * fps))
        outgoing = frames[start - 1] if start else previous_frame
        if outgoing is None or count < 2:
            continue
        style = transition['style']
        with tempfile.TemporaryDirectory(prefix='.transition-', dir=report_path.parent) as directory:
            temporary = Path(directory)
            # Frozen outgoing frame overlays the incoming scene's real moving frames.
            # Both streams have identical clocks; no overlap removes timeline frames.
            filters = '[0:v]format=gbrp,settb=AVTB,setpts=PTS-STARTPTS[a];[1:v]format=gbrp,settb=AVTB,setpts=PTS-STARTPTS[b];'
            filters += f'[a][b]xfade=transition={style}:duration={(count-1)/fps}:offset=0[v]'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-framerate', str(fps), '-i', str(outgoing),
                '-framerate', str(fps), '-start_number', str(start), '-i', str(frames[start].parent / 'frame-%06d.png'),
                '-filter_complex', filters, '-map', '[v]', '-frames:v', str(count), '-start_number', '0',
                str(temporary / 'frame-%06d.png')], check=True, capture_output=True)
            for index in range(count):
                rendered = temporary / f'frame-{index:06d}.png'
                if not rendered.is_file():
                    raise RuntimeError('transition did not render every requested frame')
            for index in range(count):
                target = frames[start + index]
                shutil.copyfile(temporary / f'frame-{index:06d}.png', target)
                sample = report['state_samples'][start + index]
                sample['state_fingerprint'] = hashlib.sha256(sample['state_fingerprint'].encode() + target.read_bytes()).hexdigest()
                sample['geometry_operation_keys'].append(f'editorial_transition:{style}')
    atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
