"""Respaldo secuencial de /s: Chrome remoto conserva su perfil y su única pestaña."""
import html as html_lib
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import requests

from .events import emit_event, action


class ChromeBlocked(RuntimeError):
    def __init__(self, reason, http=None):
        super().__init__(reason)
        self.http = http


class ChromeLocationError(RuntimeError):
    pass


SEARCH_READY = r"""() => {
    const text = document.documentElement.innerHTML;
    return !!document.querySelector('[data-component-type="s-search-result"], [data-component-type="s-result-info-bar"]')
        || /validateCaptcha|captchacharacters|Sorry! Something went wrong|gokuProps|awsWafCookieDomainList|bm-verify/.test(text)
        || /\/ap\/signin/.test(location.pathname);
}"""

CHANGE_LOCATION = r"""async ({token}) => {
    const headers = {'anti-csrftoken-a2z': token, 'x-requested-with': 'XMLHttpRequest'};
    const modal = await fetch('/portal-migration/hz/glow/get-rendered-address-selections?deviceType=desktop&pageType=Detail&storeContext=generic&actionSource=desktop-modal',
        {credentials: 'same-origin', headers});
    if (!modal.ok) return false;
    const text = await modal.text();
    const match = text.match(/CSRF_TOKEN\s*:\s*"([^"]+)"/);
    headers['anti-csrftoken-a2z'] = match ? match[1] : token;
    headers['content-type'] = 'application/json';
    const response = await fetch('/portal-migration/hz/glow/address-change?actionSource=glow', {
        method: 'POST', credentials: 'same-origin', headers,
        body: JSON.stringify({locationType: 'COUNTRY', district: 'AR', countryCode: 'AR',
            deviceType: 'web', storeContext: 'generic', pageType: 'Detail', actionSource: 'glow'})
    });
    if (!response.ok) return false;
    const body = await response.json();
    return !!(body.isAddressUpdated || body.successful)
        && (!body.address || body.address.countryCode === 'AR');
}"""


def blocked_reason(content, status, url):
    from amazon import fetch
    if fetch.is_signin(url):
        return 'requiere iniciar sesión'
    response = SimpleNamespace(text=content, status_code=status)
    return (fetch._blocked_reason(response)
            or ('AWS WAF challenge' if 'gokuProps' in content or 'awsWafCookieDomainList' in content else None)
            or ('página de perros' if fetch.is_dogs(content) else None)
            or ('intersticial bm-verify' if fetch.is_pow(content) else None)
            or (f'HTTP {status}' if status in (403, 429, 503) else None))


class ChromeSearch:
    def __init__(self, endpoint, *, start=None):
        self.endpoint = endpoint.rstrip('/')
        self.start = start
        self.playwright = self.browser = self.context = self.page = None
        self.located_origin = None

    def _connect(self):
        if self.page is not None:
            return
        if self.start is None:
            from playwright.sync_api import sync_playwright
            self.start = lambda: sync_playwright().start()
        # Chrome exige Host localhost/IP. Su discovery puede anunciar un WS de
        # loopback: conservamos el path pero usamos la autoridad del endpoint.
        response = requests.get(self.endpoint + '/json/version', headers={'Host': 'localhost:9222'}, timeout=30)
        response.raise_for_status()
        endpoint = urlsplit(self.endpoint)
        websocket = urlsplit(response.json()['webSocketDebuggerUrl'])
        # El handshake WS también manda Host: con un nombre (weboffers-chrome) Chrome lo rechaza
        # («Host header is specified and is not an IP address», medido 07/11). Se usa la IP resuelta.
        import socket
        host = endpoint.hostname or 'localhost'
        try:
            socket.inet_aton(host)
            ip = host
        except OSError:
            try:
                ip = socket.gethostbyname(host)
            except OSError:
                ip = host  # sin DNS (tests): se deja el nombre; Chrome real exige IP

        netloc = f"{ip}:{endpoint.port}" if endpoint.port else ip
        websocket_url = urlunsplit(('wss' if endpoint.scheme == 'https' else 'ws', netloc,
                                   websocket.path, websocket.query, ''))
        try:
            self.playwright = self.start()
            self.browser = self.playwright.chromium.connect_over_cdp(websocket_url, timeout=30000)
            self.context = self.browser.contexts[0]
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(30000)
        except Exception:
            self.close()
            raise

    def _is_ar(self):
        label = self.page.locator('#glow-ingress-line2').text_content() or ''
        return 'argentina' in label.casefold()

    def _ensure_ar(self, site):
        """El COUNTRY/AR es el mismo contrato de amazon_shipping.apply_ar_location."""
        try:
            with action('confirmando destino Argentina en Chrome'):
                if self.located_origin == site['base']:
                    return
                self.page.goto(site['base'] + '/', wait_until='domcontentloaded', timeout=30000)
                if self._is_ar():
                    self.located_origin = site['base']
                    return
                from amazon import fetch
                match = fetch._GLOW_TOKEN_RE.search(html_lib.unescape(self.page.content()))
                if not match or not self.page.evaluate(CHANGE_LOCATION, {'token': match.group(1)}):
                    raise ChromeLocationError('Amazon no confirmó el cambio de destino a Argentina')
                self.page.reload(wait_until='domcontentloaded', timeout=30000)
                if not self._is_ar():
                    raise ChromeLocationError('El destino visible de Chrome no confirma Argentina')
                self.located_origin = site['base']
        except Exception as exc:
            emit_event('BARRIDO_UBICACION_FALLIDA', motivo=type(exc).__name__)
            raise ChromeLocationError('No se pudo confirmar Argentina en Chrome; se detiene la tienda') from exc

    def search(self, url, site, *, reason):
        started = time.monotonic()
        content, status, blocked, error = '', None, None, None
        emit_event('BARRIDO_CHROME_INICIO', url=url, motivo_fallback=reason)
        try:
            self._connect()
            # Inicializa el destino antes de la primera búsqueda. Después se
            # exige que cada página de resultados vuelva a confirmar Argentina.
            self._ensure_ar(site)
            with action('navegando busqueda Amazon en Chrome'):
                response = self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
                status = response.status if response else None
                content = self.page.content()
                blocked = blocked_reason(content, status, self.page.url)
                if not blocked:
                    self.page.wait_for_function(SEARCH_READY, timeout=30000)
                    content = self.page.content()
                    blocked = blocked_reason(content, status, self.page.url)
                if blocked:
                    raise ChromeBlocked(blocked, http=status)
                if status != 200:
                    raise RuntimeError(f'HTTP {status} en búsqueda Chrome')
                try:
                    located = self._is_ar()
                except Exception:
                    located = False
                if not located:
                    emit_event('BARRIDO_UBICACION_FALLIDA', motivo='destino_cambió_en_busqueda')
                    raise ChromeLocationError('La búsqueda Chrome perdió el destino Argentina')
                return content, status
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            raise
        finally:
            emit_event('BARRIDO_CHROME_FIN', url=url, motivo_fallback=reason,
                       ms=round((time.monotonic() - started) * 1000), bytes=len(content.encode('utf-8')),
                       http=status, bloqueo=blocked, error=error)

    def close(self):
        if self.playwright is not None:
            # Desconecta el cliente; el Chrome remoto conserva perfil y pestaña.
            self.playwright.stop()
        self.playwright = self.browser = self.context = self.page = None
        self.located_origin = None
