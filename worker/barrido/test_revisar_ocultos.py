from barrido import revisar_ocultos, shipping


class FakeProducts:
    def __init__(self, ofertas):
        self.ofertas = ofertas
        self.llamadas = []

    def offers(self, asin, country, condition=None, postal_code=None):
        self.llamadas.append((asin, country, condition, postal_code))
        return {"title": "x", "offers": self.ofertas}

    def details(self, *a, **k):
        raise AssertionError("revisar_ocultos ya no usa la ficha")


def oferta(precio, texto, condicion="New", vendedor="v"):
    return {"price": {"amount": precio}, "delivery": {"text": texto}, "condition": condicion, "seller": {"name": vendedor}}


def test_elige_la_oferta_elegible_mas_barata_y_pide_nuevo_en_ar():
    # Caso real B004HS7T7S (10/11): las baratas sin envío gratis o sin texto, gana la gratis más barata.
    products = FakeProducts([
        oferta(119.55, "Delivery Monday, November 23"),
        oferta(210.57, None, vendedor="Amazon Germany"),
        oferta(259.82, "FREE delivery Monday, November 23", vendedor="Zentra"),
        oferta(225.0, "FREE delivery Monday, November 23", vendedor="Fabulous Yarn"),
    ])
    resultado, _ = revisar_ocultos.revisar_ofertas("B004HS7T7S", products, shipping, lambda *a, **k: None)
    assert products.llamadas == [("B004HS7T7S", "US", "new", "AR")]
    assert resultado["elegible"] is True
    assert resultado["precio"] == 225.0
    assert resultado["vendedor"] == "Fabulous Yarn"


def test_sin_ofertas_y_sin_oferta_elegible():
    log = lambda *a, **k: None
    vacio, _ = revisar_ocultos.revisar_ofertas("A", FakeProducts([]), shipping, log)
    assert vacio == {"elegible": False, "motivos": ["sin_ofertas_producto_nuevo"]}
    usada, _ = revisar_ocultos.revisar_ofertas("B", FakeProducts([oferta(150.0, "FREE delivery Monday", condicion="Used - Good")]), shipping, log)
    assert usada == {"elegible": False, "motivos": ["sin_oferta_elegible"]}


def test_los_dos_tipos_usan_el_panel_de_ofertas():
    assert not hasattr(revisar_ocultos, "revisar_precio_oculto")
    assert not hasattr(revisar_ocultos, "revisar_opciones")
