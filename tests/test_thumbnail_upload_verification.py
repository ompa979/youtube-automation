"""Regression tests for YouTube custom-thumbnail upload + verification."""
from pathlib import Path

import pipeline.upload as upload


class _Execute:
    def __init__(self, value=None, exc=None):
        self.value = value
        self.exc = exc

    def execute(self):
        if self.exc:
            raise self.exc
        return self.value


class _Thumbs:
    def __init__(self, set_response):
        self.set_response = set_response

    def set(self, **kwargs):
        return _Execute(self.set_response)


class _Videos:
    def __init__(self, response):
        self.response = response

    def list(self, **kwargs):
        return _Execute(self.response)


class _YT:
    def __init__(self, set_response, video_response):
        self._thumbs = _Thumbs(set_response)
        self._videos = _Videos(video_response)

    def thumbnails(self):
        return self._thumbs

    def videos(self):
        return self._videos


def test_thumbnail_is_verified_only_when_remote_url_matches(monkeypatch, tmp_path):
    thumb = tmp_path / "thumbnail.jpg"
    thumb.write_bytes(b"x" * 6000)
    remote = "https://i.ytimg.com/vi/abc/maxresdefault.jpg"
    yt = _YT(
        {"items": [{"maxres": {"url": remote}}]},
        {"items": [{"snippet": {"thumbnails": {"maxres": {"url": remote}}}}]},
    )

    monkeypatch.setattr(upload, "MediaFileUpload", lambda *a, **k: object())
    monkeypatch.setattr(upload.time, "sleep", lambda *_: None)

    result = upload._set_thumbnail(yt, "abc", thumb)
    assert result["status"] == "VERIFIED"


def test_thumbnail_is_not_falsely_verified_from_generated_frame(monkeypatch, tmp_path):
    thumb = tmp_path / "thumbnail.jpg"
    thumb.write_bytes(b"x" * 6000)
    custom = "https://i.ytimg.com/vi/abc/maxresdefault.jpg"
    generated = "https://i.ytimg.com/vi/abc/hqdefault.jpg"
    yt = _YT(
        {"items": [{"maxres": {"url": custom}}]},
        {"items": [{"snippet": {"thumbnails": {"high": {"url": generated}}}}]},
    )

    monkeypatch.setattr(upload, "MediaFileUpload", lambda *a, **k: object())
    monkeypatch.setattr(upload.time, "sleep", lambda *_: None)

    result = upload._set_thumbnail(yt, "abc", thumb)
    assert result["status"] == "UPLOADED_UNVERIFIED"


def test_permission_failure_is_explicit_and_nonfatal(monkeypatch, tmp_path):
    thumb = tmp_path / "thumbnail.jpg"
    thumb.write_bytes(b"x" * 6000)

    class _RejectingThumbs:
        def set(self, **kwargs):
            return _Execute(
                exc=Exception(
                    "<HttpError 403> The authenticated user doesn't have permissions "
                    "to upload and set custom video thumbnails."
                )
            )

    class _RejectingYT:
        def thumbnails(self):
            return _RejectingThumbs()

    monkeypatch.setattr(upload, "MediaFileUpload", lambda *a, **k: object())
    monkeypatch.setattr(upload.time, "sleep", lambda *_: None)

    result = upload._set_thumbnail(_RejectingYT(), "abc", thumb)
    assert result["status"] == "FAILED_PERMISSION"
