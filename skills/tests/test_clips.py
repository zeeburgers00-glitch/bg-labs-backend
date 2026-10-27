"""Clip bounds and report validation, independent of the real media tests."""
import json

import pytest

from vimax_skills import clips


def test_clip_is_capped_and_uses_no_shell(tmp_path, monkeypatch):
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'not decoded by this bounded-command unit test')
    (tmp_path / 'scene-detection.json').write_text(json.dumps({'scenes': [
        {'start_seconds': 4, 'end_seconds': 60}
    ]}))
    calls = []

    def fake_run(command, *, cwd, timeout):
        calls.append((command, cwd, timeout))
        (cwd / command[-1]).write_bytes(b'test clip')

    monkeypatch.setattr(clips, '_run', fake_run)
    temporary, metadata = clips.extract_clip(video, 1, 'ffmpeg')
    command, cwd, timeout = calls[0]
    assert command[command.index('-ss') + 1] == '4.000'
    assert command[command.index('-t') + 1] == '30.000'
    assert cwd == tmp_path and timeout == 120
    assert metadata['limited_to_30_seconds'] and metadata['duration_seconds'] == 30
    assert temporary.parent == tmp_path and temporary.is_file()


@pytest.mark.parametrize('start,end', [(-1, 10), (5, 5), (1, 182), (float('nan'), 3), (0, float('inf'))])
def test_clip_rejects_invalid_time_bounds(tmp_path, start, end):
    video = tmp_path / 'video.mp4'
    video.touch()
    (tmp_path / 'scene-detection.json').write_text(json.dumps({'scenes': [
        {'start_seconds': start, 'end_seconds': end}
    ]}))
    with pytest.raises(ValueError):
        clips.extract_clip(video, 1, 'ffmpeg')
