from fastapi.testclient import TestClient
import app.api.routes_v3 as r
from app.main import app
from app.trajectory.composer_v4 import PlaylistResult
from app.trajectory.intent import PlaylistIntent


def _fake_result(mode_tag):
    intent = PlaylistIntent(raw_prompt="p", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    from app.trajectory.candidates import CandidateTrack
    t = CandidateTrack(id="1", title="x", artist_name="a", artist_id="a1",
                       album_name="al", album_id="al1", year=1985, duration_ms=200000)
    return PlaylistResult(tracks=[t], intent=intent,
                          metrics={"mode": mode_tag}, generation_time_ms=1)


def _patch_composers(monkeypatch, called):
    def fake_v4(prompt, size):
        called["v4"] = True
        return _fake_result("arc")

    def fake_snapshot(prompt, soft_cap=None, strict_niche=False):
        called["snap"] = True
        called["strict"] = strict_niche
        return _fake_result("snapshot")

    monkeypatch.setattr(r, "compose_playlist_v4", fake_v4)
    monkeypatch.setattr(r, "compose_snapshot", fake_snapshot)
    monkeypatch.setattr(r, "generate_playlist_title", lambda *a, **k: "T")
    monkeypatch.setattr(r, "_save_playlist", lambda *a, **k: "pid")


def test_mode_defaults_to_arc_and_calls_v4(monkeypatch):
    called = {}
    _patch_composers(monkeypatch, called)

    client = TestClient(app)
    resp = client.post("/generate-playlist", json={"prompt": "evil 80s thrash", "save": False})
    assert resp.status_code == 200
    assert called.get("v4") and not called.get("snap")


def test_mode_snapshot_calls_compose_snapshot(monkeypatch):
    called = {}
    _patch_composers(monkeypatch, called)

    client = TestClient(app)
    resp = client.post("/generate-playlist",
                       json={"prompt": "evil 80s thrash", "mode": "snapshot",
                             "size": 120, "save": False})
    assert resp.status_code == 200
    assert called.get("snap") and not called.get("v4")
