"""Historias por la API de Meta (17/11): IG con media_type=STORIES y FB con /video_stories. Sin red."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("meta_historia", Path(__file__).with_name("meta_publicar.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

URL = "https://lista.blackseam.knunet.com/descargas/redes/f400-historia-18-11/historia-18-11.mp4"
ENTRY = {"id": "historia-18-11", "cuando": "2026-11-18T12:30:00-03:00", "tipo": "historia",
         "destinos": ["ig", "fb"], "media": [URL], "texto_ig": "", "texto_fb": ""}


@pytest.fixture
def llamadas(monkeypatch):
    log = []
    monkeypatch.setattr(m, "ENV", {"META_IG_USER_ID": "IG1", "META_PAGE_ID": "PAG1"})

    def post(path, data, token):
        log.append(("post", path, dict(data)))
        if path.endswith("/media"):
            return {"id": "CONT1"}
        if path.endswith("/media_publish"):
            return {"id": "STORY_IG"}
        if data.get("upload_phase") == "start":
            return {"video_id": "VID1", "upload_url": "https://rupload.facebook.com/video-upload/v21.0/VID1"}
        if data.get("upload_phase") == "finish":
            return {"success": True, "post_id": "STORY_FB"}
        raise AssertionError(path)

    monkeypatch.setattr(m, "graph_post", post)
    monkeypatch.setattr(m, "esperar_finished", lambda c, t: log.append(("espera", c)))
    monkeypatch.setattr(m, "rupload", lambda vid, url, token, que: log.append(("rupload", vid, url)))
    return log


def test_historia_ig_usa_stories_sin_caption(llamadas):
    assert m.publicar(ENTRY, "ig", "tok") == "STORY_IG"
    _, path, data = llamadas[0]
    assert path == "/IG1/media"
    assert data == {"media_type": "STORIES", "video_url": URL}  # sin caption ni sticker: la API no los admite
    assert ("espera", "CONT1") in llamadas
    assert llamadas[-1][1] == "/IG1/media_publish" and llamadas[-1][2] == {"creation_id": "CONT1"}


def test_historia_fb_start_rupload_finish(llamadas):
    assert m.publicar(ENTRY, "fb", "tok") == "STORY_FB"
    assert [c[1] for c in llamadas] == ["/PAG1/video_stories", "VID1", "/PAG1/video_stories"]
    assert llamadas[0][2] == {"upload_phase": "start"}
    assert llamadas[1] == ("rupload", "VID1", URL)
    assert llamadas[2][2] == {"upload_phase": "finish", "video_id": "VID1"}


def test_historia_fb_finish_sin_success_falla(llamadas, monkeypatch):
    original = m.graph_post

    def post(path, data, token):
        if data.get("upload_phase") == "finish":
            return {"success": False}
        return original(path, data, token)

    monkeypatch.setattr(m, "graph_post", post)
    with pytest.raises(m.MetaError):
        m.publicar(ENTRY, "fb", "tok")


def test_reel_no_cambia(llamadas):
    reel = dict(ENTRY, tipo="reel", texto_ig="hola")
    m.publicar(reel, "ig", "tok")
    assert llamadas[0][2]["media_type"] == "REELS"
