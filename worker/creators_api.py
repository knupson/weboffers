"""Adaptador de Creators API. El contrato remoto requiere verificación."""

from datetime import datetime, timezone
import math
import os

import requests


# TODO: verificar URL en https://affiliate-program.amazon.com/creatorsapi/docs/
TOKEN_BASE_URL = "https://api.amazon.com"
# TODO: verificar ruta en https://affiliate-program.amazon.com/creatorsapi/docs/
TOKEN_PATH = "/auth/o2/token"
# TODO: verificar URL en https://affiliate-program.amazon.com/creatorsapi/docs/
API_BASE_URL = "https://creatorsapi.amazon"
# TODO: verificar ruta en https://affiliate-program.amazon.com/creatorsapi/docs/
ITEMS_PATH = "/catalog/v1/getItems"


def is_configured(store):
    if store not in ("US", "ES"):
        raise ValueError("La tienda debe ser US o ES")
    return all(os.environ.get(key, "").strip() for key in (
        "CREATORS_CLIENT_ID", "CREATORS_CLIENT_SECRET", f"CREATORS_PARTNER_TAG_{store}"
    ))


def empty_item(asin, store):
    return dict(asin=asin, store=store, title=None, priceUsd=None,
                priceFetchedAt=None, imageUrl=None, availability=None)


def fetch_items(asins, store):
    items = [empty_item(asin, store) for asin in asins]
    if not is_configured(store):
        print(f"Modo offline para {store}: faltan credenciales de Creators API.", flush=True)
        return items
    if not items:
        return items
    try:
        token_response = requests.post(
            TOKEN_BASE_URL + TOKEN_PATH,
            data={"grant_type": "client_credentials",
                  "client_id": os.environ["CREATORS_CLIENT_ID"],
                  "client_secret": os.environ["CREATORS_CLIENT_SECRET"]},
            timeout=30,
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        response = requests.post(
            API_BASE_URL + ITEMS_PATH,
            headers={"Authorization": f"Bearer {token}"},
            json={"itemIds": list(asins), "marketplace": store,
                  "partnerTag": os.environ[f"CREATORS_PARTNER_TAG_{store}"]},
            timeout=30,
        )
        response.raise_for_status()
        # TODO: verificar cuerpo y respuesta en https://affiliate-program.amazon.com/creatorsapi/docs/
        remote_items = response.json()["items"]
        fetched_at = datetime.now(timezone.utc).isoformat()
        by_asin = {item["asin"]: item for item in remote_items}
        for item in items:
            remote = by_asin.get(item["asin"])
            if remote is None:
                continue
            for field in ("title", "imageUrl", "availability"):
                value = remote.get(field)
                item[field] = value if isinstance(value, str) else None
            price = remote.get("price", {})
            amount = price.get("amount") if isinstance(price, dict) else None
            if (isinstance(price, dict) and price.get("currency") == "USD"
                    and isinstance(amount, (int, float)) and not isinstance(amount, bool)
                    and math.isfinite(amount) and amount >= 0):
                item["priceUsd"] = amount
                item["priceFetchedAt"] = fetched_at
        return items
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        print(f"No se pudieron consultar los productos de {store}; se publican sin precio.", flush=True)
        return [empty_item(asin, store) for asin in asins]
