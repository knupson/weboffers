"""Destacados oficiales y ofertas locales nuevas; sin sites/MLA/search."""
import time
import requests
from .amazon_source import SourceError
from .events import emit_event
from .models import normalize_product, positive


class MLSource:
    def __init__(self, date, rate, config, known=(), get=None, sleep=time.sleep):
        import ml_prices
        self.ml, self.date, self.rate, self.config = ml_prices, date, rate, config
        self.known, self.get, self.sleep = set(known), get or ml_prices.get_json, sleep
        self.products_cache, self.offer_pages = {}, {}

    def request(self, path, params=None):
        self.sleep(self.config.ml_pause)
        try:
            return self.get(path, params=params)
        except requests.HTTPError as exc:
            r = exc.response
            raise SourceError(f"{exc}: {r.text if r is not None else ''}",
                              http=r.status_code if r is not None else None,
                              blocked=r is not None and r.status_code in (403, 429)) from exc

    def walk_categories(self, definition):
        seen, result = set(), []
        excluded = set(definition.get("exclude", []))

        def walk(node):
            try:
                visit(node)
            except Exception as exc:
                result.append({**node, '_discovery_error': exc})

        def visit(node):
            if node["id"] in seen or node["id"] in excluded:
                return
            seen.add(node["id"])
            if node["kind"] == "leaf":
                result.append(node)
                return
            # 07/11: el recorrido del árbol tardaba >10 min sin una línea de log; avance cada 25 nodos.
            if len(seen) % 25 == 0:
                emit_event("BARRIDO_DESCUBRIENDO", tienda="ML", consultadas=len(seen), hojas=len(result))
            body = self.request("/categories/" + node["id"])
            if "children_categories" not in body:
                raise SourceError(f"Categoría ML sin children_categories: {body}")
            children = body["children_categories"]
            if not children:
                result.append({**node, "kind": "leaf"})
            for child in children:
                walk(dict(id=child["id"], name=child["name"], kind="root"))

        for node in definition["nodes"]:
            walk(node)
        return result

    def fetch_product_offers(self, identity):
        if identity in self.products_cache:
            return self.products_cache[identity]
        detail = self.request("/products/" + identity)
        offers, offset, seen, pages = [], 0, set(), []
        while True:
            try:
                body = self.request(f"/products/{identity}/items", {"offset": offset, "limit": 100})
            except SourceError as exc:
                if exc.http == 404 and "no winners" in str(exc).lower():
                    break
                raise
            batch = body.get("results")
            pages.append(body)
            if not isinstance(batch, list):
                raise SourceError(f"Ofertas ML sin results: {body}")
            fingerprint = repr(batch)
            if batch and fingerprint in seen:
                raise SourceError(f"Ofertas ML repetidas: {identity} offset={offset}")
            seen.add(fingerprint)
            offers.extend(batch)
            paging = body.get("paging") or {}
            total = paging.get("total", len(offers))
            if len(offers) >= total:
                break
            if not batch:
                raise SourceError(f"Ofertas ML incompletas: {identity} offset={offset}")
            offset += len(batch)
        self.products_cache[identity] = detail, offers
        self.offer_pages[identity] = pages
        return detail, offers

    def fetch_search_page(self, category, page, stamp):
        if page != 1:
            raise ValueError("Highlights tiene una sola página")
        highlights = self.request("/highlights/MLA/category/" + category["id"])
        if not isinstance(highlights.get("content"), list):
            raise SourceError(f"Highlights sin content: {highlights}")
        rows, seen = [], set()
        for product in highlights["content"]:
            if product.get("type") != "PRODUCT" or product["id"] in seen:
                continue
            identity = product["id"]
            seen.add(identity)
            detail, offers = self.fetch_product_offers(identity)
            valid = [item for item in offers if item.get("condition") == "new" and item.get("currency_id") == "ARS"
                     and not self.ml.is_international(item) and positive(item.get("price"))]
            offer = min(valid, key=lambda item: item["price"]) if valid else {}
            shipping = offer.get("shipping") or {}
            shipping_class = "desconocido"
            if shipping.get("free_shipping") is True:
                shipping_class = "gratis"
            elif shipping.get("free_shipping") is False:
                shipping_class = "pago"
            raw = {"name": detail.get("name"), "price": offer.get("price"), "highlights": product,
                   "detail": detail, "offers": offers, "offer_pages": self.offer_pages[identity], "selected_offer": offer}
            row = normalize_product(raw, store="ML", identity=identity, stamp=stamp, currency="ARS", rate=self.rate,
                provenance=dict(category_id=category["id"], category_name=category["name"], page=1,
                                url="https://api.mercadolibre.com/highlights/MLA/category/" + category["id"]),
                shipping={"shipping_class": shipping_class, "text": None}, condition="new" if offer else None,
                known=identity in self.known, min_usd=self.config.min_usd, max_usd=self.config.max_usd)
            rows.append(row)
        return dict(products=rows, raw={"highlights": highlights}, http=200, count=len(rows), total_pages=1, current_page=1, has_next=False)
