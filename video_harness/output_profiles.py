"""Combined output size and frame-rate choices; custom values remain intact."""
from copy import deepcopy

OUTPUT_PROFILES = (
    {'id': 'landscape', 'label': '가로 · 1920×1080 · 30fps', 'values': {'final_width': 1920, 'final_height': 1080, 'final_fps': 30}},
    {'id': 'portrait', 'label': '세로 · 1080×1920 · 30fps', 'values': {'final_width': 1080, 'final_height': 1920, 'final_fps': 30}},
    {'id': 'square', 'label': '정사각형 · 1080×1080 · 30fps', 'values': {'final_width': 1080, 'final_height': 1080, 'final_fps': 30}},
)


def output_profiles_payload():
    return deepcopy(OUTPUT_PROFILES)
