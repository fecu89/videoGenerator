from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_benchmark_report_validator_enforces_the_checked_in_selection_rule(tmp_path: Path) -> None:
    """A report that names a slower valid method must not pass schema validation."""
    report = tmp_path / "capture-benchmark.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backend": {"requested": "metal", "actual": "metal", "vendor": "Apple", "renderer": "ANGLE Metal"},
                "input": {"width": 1920, "height": 1080, "fps": 30, "frame_count": 8},
                "candidates": [
                    {
                        "method": "locator-png", "supported": True, "median_wall_ms": 100,
                        "peak_rss": {"node_bytes": 10, "chromium_bytes": 90}, "transferred_bytes": 1,
                        "decoded_rgba_hash": "a", "integrity": True, "alpha": True, "frame_order": True, "complete": True,
                        "failed_trials": 0, "trials": [],
                    },
                    {
                        "method": "data-url-png", "supported": True, "median_wall_ms": 70,
                        "peak_rss": {"node_bytes": 10, "chromium_bytes": 90}, "transferred_bytes": 1,
                        "decoded_rgba_hash": "a", "integrity": True, "alpha": True, "frame_order": True, "complete": True,
                        "failed_trials": 0, "trials": [],
                    },
                    {
                        "method": "blob-array-buffer-png", "supported": False, "median_wall_ms": 0,
                        "peak_rss": {"node_bytes": 0, "chromium_bytes": 0}, "transferred_bytes": 0,
                        "decoded_rgba_hash": "", "integrity": False, "alpha": False, "frame_order": False, "complete": False,
                        "failed_trials": 3, "trials": [],
                    },
                    {
                        "method": "blob-base64-png", "supported": True, "median_wall_ms": 79,
                        "peak_rss": {"node_bytes": 10, "chromium_bytes": 90}, "transferred_bytes": 1,
                        "decoded_rgba_hash": "a", "integrity": True, "alpha": True, "frame_order": True, "complete": True,
                        "failed_trials": 0, "trials": [],
                    },
                    {
                        "method": "loopback-blob-png", "supported": True, "median_wall_ms": 60,
                        "peak_rss": {"node_bytes": 10, "chromium_bytes": 90}, "transferred_bytes": 1,
                        "decoded_rgba_hash": "a", "integrity": True, "alpha": True, "frame_order": False, "complete": True,
                        "failed_trials": 0, "trials": [],
                    },
                ],
                "production_method": "blob-base64-png",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["npm", "run", "benchmark-capture", "--silent", "--", "--validate", str(report)],
        cwd=Path(__file__).parents[1] / "science_renderer",
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "production method" in result.stderr
