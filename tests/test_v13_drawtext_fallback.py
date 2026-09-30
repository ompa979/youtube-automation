from pathlib import Path
from unittest.mock import patch
import pipeline.motion_graphics as mg


def test_motion_graphics_is_drawtext_free_by_default():
    f = mg.build_motion_graphics_filter(2.0, "0xFFFFFF", 0, 6, True, "hook", "HOOK")
    assert "drawtext" not in f.lower()


def test_motion_graphics_allow_drawtext_does_not_break_runtime_contract():
    f = mg.build_motion_graphics_filter(2.0, "0xFFFFFF", 0, 6, True, "hook", "HOOK", allow_drawtext=True)
    assert "drawbox" in f.lower()
