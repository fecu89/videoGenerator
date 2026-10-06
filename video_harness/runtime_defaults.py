"""Fixed preview policy for settings schema v6.

These are implementation defaults, not per-video options. Older run snapshots
keep their serialized values through ArchivedRenderSettings.
"""
from typing import Final

PREVIEW_LONG_EDGE: Final = 384
PREVIEW_FPS: Final = 9
PREVIEW_INTERVAL_SECONDS: Final = 0.5
CONTACT_SHEET_COLUMNS: Final = 8
