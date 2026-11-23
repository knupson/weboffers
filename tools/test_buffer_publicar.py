import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buffer_publicar as bp  # noqa: E402

CAPTION = """¿Amazon o Mercado Libre? Depende del producto.

Logitech G Yeti GX: $249.611 en Mercado Libre vs ~$340.000 de Amazon. Gana Mercado Libre.

Comparamos 174 productos con los precios de hoy: link en la bio.
La mejor oferta del día, todos los días a las 12 y a las 20, en Telegram: t.me/franquicia400

Voz: Piper «es_AR-daniela-high» (CC BY-SA 4.0). Música: «Hip Hop 02», Mixkit.

#amazonargentina #mercadolibre #comprasalexterior #franquicia400 #tecnologia
"""
AHORA = datetime.datetime(2026, 11, 17, 18, 20, tzinfo=bp.ART)
VIDEO = "https://lista.blackseam.knunet.com/descargas/redes/f400-reel-17-11/reel-17-11.mp4"


def test_programa_a_las_19_con_metadatos_legales():
    i = bp.armar_inputs("reel-17-11", "2026-11-17T19:00:00-03:00", VIDEO, CAPTION, AHORA)
    yt, x = i["youtube"], i["x"]
    assert yt["mode"] == x["mode"] == "customScheduled"
    assert yt["dueAt"] == "2026-11-17T19:00:00-03:00"
    m = yt["metadata"]["youtube"]
    assert m["madeForKids"] is False and m["isAiGenerated"] is True and m["privacy"] == "public"
    assert len(m["title"]) <= 100 and "17/11" in m["title"]
    assert yt["channelId"] == bp.CANALES["youtube"] and x["channelId"] == bp.CANALES["x"]
    assert yt["assets"] == [{"video": {"url": VIDEO}}] == x["assets"]
    assert yt["schedulingType"] == "automatic"
    json.dumps(i)  # serializable


def test_descripcion_youtube_lleva_link_utm_y_aviso_de_afiliados():
    d = bp.texto_youtube(CAPTION, "reel-17-11")
    assert "link en la bio" not in d
    assert "utm_source=youtube&utm_medium=social&utm_campaign=reel-diario&utm_content=reel-17-11" in d
    assert bp.AVISO_AFILIADOS in d
    assert "Mixkit" in d and "CC BY-SA" in d  # créditos de música y voz


def test_post_x_entra_en_280_y_declara_afiliados():
    t = bp.texto_x(CAPTION, "reel-17-11")
    largo = len(t) - len(bp.utm("x", "reel-17-11")) + 23
    assert largo <= 280
    assert "afiliado" in t and "174 productos" in t
    assert t.rstrip().endswith("utm_content=reel-17-11")
    assert t.count("#") <= 2


def test_horario_vencido_publica_ya():
    i = bp.armar_inputs("reel-17-11", "2026-11-17T18:21:00-03:00", VIDEO, CAPTION, AHORA)
    assert i["youtube"]["mode"] == "shareNow" and "dueAt" not in i["youtube"]


def test_caption_sin_link_en_la_bio_falla():
    try:
        bp.texto_youtube("sin link", "reel-17-11")
    except ValueError:
        return
    raise AssertionError("debía fallar")


def test_idempotente_no_repite_post(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bp, "ESTADO", str(tmp_path / "estado.json"))
    monkeypatch.setattr(bp, "ENV_BUFFER", str(tmp_path / "buffer.env"))
    (tmp_path / "buffer.env").write_text("BUFFER_API_KEY=x\n")
    (tmp_path / "estado.json").write_text(json.dumps({"reel-17-11|youtube": {"post_id": "a"}, "reel-17-11|x": {"post_id": "b"}}))
    txt = tmp_path / "c.txt"
    txt.write_text(CAPTION, encoding="utf-8")
    llamados = []
    monkeypatch.setattr(bp, "crear_post", lambda *a: llamados.append(a) or ({"id": "z"}, None))
    assert bp.main(["--id", "reel-17-11", "--cuando", "2030-01-01T19:00:00-03:00", "--video", VIDEO, "--texto", str(txt)]) == 0
    assert llamados == []
    assert capsys.readouterr().out.count("BUFFER_YA") == 2


def test_falla_avisa_y_sale_1(tmp_path, monkeypatch):
    monkeypatch.setattr(bp, "ESTADO", str(tmp_path / "estado.json"))
    monkeypatch.setattr(bp, "ENV_BUFFER", str(tmp_path / "buffer.env"))
    (tmp_path / "buffer.env").write_text("BUFFER_API_KEY=x\n")
    txt = tmp_path / "c.txt"
    txt.write_text(CAPTION, encoding="utf-8")
    avisos = []
    monkeypatch.setattr(bp, "alertar", lambda t, a: avisos.append(t))
    monkeypatch.setattr(bp, "crear_post", lambda clave, e: (None, "LimitReachedError: lleno") if e["channelId"] == bp.CANALES["x"] else ({"id": "p1", "status": "scheduled"}, None))
    assert bp.main(["--id", "reel-17-11", "--cuando", "2030-01-01T19:00:00-03:00", "--video", VIDEO, "--texto", str(txt)]) == 1
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["reel-17-11|youtube"]["post_id"] == "p1" and "reel-17-11|x" not in estado
    assert avisos and "X" in avisos[0]
