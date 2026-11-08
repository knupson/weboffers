"""Identidad Amazon y filtro local de catálogo, sin consultas adicionales."""
import re
import unicodedata


TOKEN = re.compile(r'[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*')
# Consumir la medida ENTERA antes de tokenizar: 1,050MB/s no puede volverse 050MB/s.
MEASURE = re.compile(
    r'(?<!\w)\d+(?:[.,]\d+)*(?:\s*-\s*|\s*)(?:[kmgt]i?b(?:\s*/\s*s)?|[kmgt]?bps|'
    r'[kmg]?hz|mah|wh|[kmg]?w|[kmg]?v|[kcm]?m|inch(?:es)?|pulgadas?|'
    r'fps|dpi|[48]k|k|p|%|["″])(?=$|[^\w])', re.I)
MODEL_KEYS = ('part_number', 'manufacturer_part_number', 'manufacturer_item',
              'manufacturer_item_number', 'item_model_number', 'model_number', 'model')
GENERIC_MODELS = {'usb-c', 'usb-a', 'usbc', 'usba', 'wi-fi', 'wifi', 'bluetooth',
                  'ddr4', 'ddr5', 'pcie4', 'pcie5', 'nvme'}
TYPE_WORDS = {
    'dock': {'dock', 'docking', 'docks', 'replicador', 'acoplamiento'},
    'mochila': {'mochila', 'backpack', 'backpacks'},
    'mouse': {'mouse', 'raton', 'mice'},
    'teclado': {'keyboard', 'teclado', 'keyboards'},
    'bungee': {'bungee'},
    'toner': {'toner', 'cartucho', 'cartridge'},
    'ssd': {'ssd'},
    'tablet': {'tablet', 'tableta'},
    'drum': {'drum', 'tambor'},
    'webcam': {'webcam'},
    'camara_deportiva': {'actioncam'},
    'monitor': {'monitor', 'monitors', 'pantalla'},
    'auriculares': {'headphones', 'headphone', 'headset', 'auriculares'},
}
FILLER = {'wireless', 'wired', 'inalambrico', 'inalambricos', 'gaming', 'mmo',
          'black', 'white', 'negro', 'blanco', 'original', 'high', 'performance',
          'up', 'to', 'hasta', 'with', 'con', 'for', 'para', 'the', 'and', 'de',
          'series', 'serie', 'universal', 'station', 'usb', 'usb-c', 'usb-a'}
QUALIFIERS = {'pro', 'plus', 'ultra', 'max', 'mini', 'super', 'lite', 'se', 'flex', 'duo'}
AFTERMARKET = {'compatible', 'compatibles', 'alternativo', 'alternativa', 'alternativos',
               'generico', 'generica', 'generic', 'remanufacturado', 'remanufacturada',
               'remanufactured', 'alternative'}
PACK = {'combo', 'pack', 'multipack', 'kit'}
# Componentes de equipos: no son el modelo del producto que los contiene.
COMPONENT = re.compile(
    r'\b(?:Mali[- ]?[A-Z]?\d+|Snapdragon(?:\s+\d+[A-Z]*|\s+Gen\s+\d+)*'
    r'|Helio(?:\s+[A-Z]?\d+)?|Ryzen(?:\s+\d+\w*)*'
    r'|Intel\s+Core(?:\s+(?:i[3579][- ]?\d*\w*|Ultra|\d+\w*))*'
    r'|(?:GeForce\s+)?(?:RTX|GTX)(?:\s*\d+\w*)?(?:\s+Ti)?|GeForce)\b', re.I)


def words(text):
    plain = ''.join(c for c in unicodedata.normalize('NFKD', str(text or '').lower())
                    if not unicodedata.combining(c))
    return re.findall(r'[a-z0-9]+', plain)


def code(text):
    return ''.join(words(text))


def model_tokens(text):
    return [t for t in TOKEN.findall(MEASURE.sub(' ', str(text or '')))
            if re.search('[A-Za-z]', t) and re.search(r'\d', t)
            and t.lower() not in GENERIC_MODELS]


def field_model(value):
    if not isinstance(value, str):
        return ''
    tokens = model_tokens(value)
    if tokens:
        return max(tokens, key=len)
    # Un número de pieza puede ser completamente numérico; sólo de campos explícitos.
    if re.fullmatch(r'\d+(?:-\d+)*', value.strip()):
        return value.strip()
    return ''


def _sources(row):
    """Sólo contenedores de identidad; nunca card_html ni descripciones."""
    if not isinstance(row, dict):
        return
    yield row
    for key in ('raw', 'detail', 'detail_data', 'details', 'identifiers', 'overview'):
        value = row.get(key)
        if isinstance(value, dict):
            yield from _sources(value)


def _brand(value):
    if isinstance(value, dict):
        value = value.get('name')
    return value.strip() if isinstance(value, str) else ''


def _clean_title(title):
    title = MEASURE.sub(lambda m: m.group() if re.fullmatch(r'\d+(?:[.,]\d+)*[\s-]*[TGM]B', m.group(), re.I) else ' ', title)
    title = re.sub(r'\([^)]*\)|\[[^]]*\]', ' ', title)
    title = re.sub(r"\b(?:Amazon'?s Choice|Best Seller|Limited time deal)\b", ' ', title, flags=re.I)
    # No partir por una coma interna de una medida (1,050MB/s).
    title = re.split(r'\s*[|;–—]\s*|\s+-\s+|,(?!\d)', title)[0]
    return ' '.join(title.split()[:12])


def _product_title(title, *, product_title=''):
    """Excluir componentes salvo cuando el artículo sea la pieza misma."""
    tokens = set(words(product_title or title))
    if tokens & {'gpu', 'graphics', 'grafica', 'video', 'processor', 'procesador', 'cpu'} and not tokens & {
            'tablet', 'laptop', 'notebook', 'desktop', 'computer', 'pc'}:
        return title
    return COMPONENT.sub(' ', title)


def _query(text):
    seen, parts = set(), []
    for part in text.split():
        key = code(part)
        if key and key not in seen:
            seen.add(key)
            parts.append(part)
    return ' '.join(parts)


def amazon_identity(row, brand=''):
    title = row.get('title') or ''
    sources = list(_sources(row))
    brand = _brand(brand) or next((_brand(s.get('brand')) or _brand(s.get('brand_name'))
                                for s in sources if _brand(s.get('brand')) or _brand(s.get('brand_name'))), '')
    brand = brand or (title.split()[0] if title.split() else '')
    # Priorizar el número de pieza provisto, luego el modelo más específico del título.
    model_title = _product_title(title)
    explicit_value = next((s[key] for key in MODEL_KEYS for s in sources
                           if isinstance(s.get(key), str)
                           and field_model(_product_title(s[key], product_title=title))), '')
    explicit = field_model(_product_title(explicit_value, product_title=title))
    tokens = model_tokens(model_title)
    product_models = [t for t in tokens if code(t) != code(brand)]
    # NJ98 también puede ser la primera palabra; no perderlo si no hay otra pieza.
    model = explicit or max(product_models or tokens, key=len, default='')
    cleaned = _clean_title(model_title)
    line = []
    # 870 EVO es una línea; SATA y el formato físico no la definen.
    disk_line = re.search(r'\b(\d{3,4})\s+(EVO|PRO|QVO)\b', model_title, re.I)
    tablet_line = re.search(r'\b(Idea\s+Tab)\b', model_title, re.I)
    if disk_line and 'ssd' in words(title):
        model, line = explicit, disk_line.group().split()
    elif tablet_line:
        model, line = explicit, tablet_line.group().split()
    if model and len(code(model)) <= 3:
        parts = TOKEN.findall(MEASURE.sub(' ', cleaned))
        index = next((i for i, part in enumerate(parts) if code(part) == code(model)), None)
        if index is not None:
            # Naga V3 Pro, en lugar de V3. Las palabras previas conservan la línea.
            line = [p for p in parts[:index] if code(p) not in words(brand)
                    and p.lower() not in FILLER and p.lower() not in GENERIC_MODELS]
            line += [model]
            if index + 1 < len(parts) and parts[index + 1].lower() in QUALIFIERS:
                line.append(parts[index + 1])
        elif explicit_value:
            # Si el título es genérico, no perder Naga/Pro presentes en el campo model.
            line = [p for p in TOKEN.findall(MEASURE.sub(' ', explicit_value))
                    if p.lower() not in FILLER and code(p) not in words(brand)]
    if not model and not line:
        # También existen modelos sin dígitos, como Extreme Portable SSD.
        named = next((s[key] for key in MODEL_KEYS for s in sources
                      if isinstance(s.get(key), str) and 0 < len(s[key].split()) <= 6
                      and not re.search(r'\d', s[key]) and not MEASURE.search(s[key])
                      and not COMPONENT.search(s[key])
                      and set(words(s[key])) - FILLER - set(words(brand)) - GENERIC_MODELS), '')
        line = TOKEN.findall(named)
    # Sufijos de la pieza: Evolve2 65, G502 X, X2 Superstrike. No perderlos
    # aunque el código principal sea suficientemente largo por sí solo.
    suffix = []
    parts = TOKEN.findall(MEASURE.sub(' ', cleaned))
    index = next((i for i, part in enumerate(parts) if model and code(part) == code(model)), None)
    if index is not None:
        for part in parts[index + 1:]:
            if part.isdigit() or len(part) == 1 or part.lower() in QUALIFIERS | {'superstrike', 'hero'}:
                suffix.append(part)
            else:
                break
    return dict(title=title, brand=brand, models=[model] if model else [],
                line=line, suffix=suffix, cleaned=cleaned)


def build_queries(title, brand='', row=None):
    identity = amazon_identity({**(row or {}), 'title': title or ''}, brand)
    if not identity['title']:
        return []
    model = ' '.join(identity['line'] or identity['models'])
    if identity['models'] and not identity['line']:
        model = ' '.join([model, *(part for part in identity['suffix'] if part.lower() != 'hero')]).strip()
    specific = f"{identity['brand']} {model}".strip() if model else ''
    queries = {}
    for value in (specific, identity['cleaned']):
        query = _query(value)
        if query:
            queries.setdefault(code(query), query)
    return list(queries.values())[:2]


ML_IDENTITY_ATTRIBUTES = ('BRAND', 'LINE', 'MODEL', 'ALPHANUMERIC_MODEL', 'PART_NUMBER', 'MPN')


def capacities(text):
    # Misma escala decimal para poder cotejar 1TB con 1000GB, sin mezclar velocidades.
    values = set()
    for match in re.finditer(r'(?<!\w)(\d+(?:[.,]\d+)?)[\s-]*(TB|GB|MB)\b(?!\s*/\s*s)', text, re.I):
        value, unit = match.groups()
        values.add(float(value.replace(',', '.')) * {'TB': 1000, 'GB': 1, 'MB': .001}[unit.upper()])
    return values


def candidate_score(identity, product):
    """(puntaje, motivo); None prohíbe consultar /items de ese candidato."""
    # Nombre + atributos de identidad que /products/search ya trae (marca, línea, modelo, número de parte):
    # el nombre de ML a veces omite el modelo que sí figura en los atributos.
    extra = ' '.join(str(a.get('value_name') or '') for a in product.get('attributes') or []
                     if isinstance(a, dict) and a.get('id') in ML_IDENTITY_ATTRIBUTES)
    name = ' '.join(filter(None, [product.get('name') or '', extra]))
    target, source = set(words(name)), set(words(identity['title']))
    brand = set(words(identity['brand']))
    if bool(source & AFTERMARKET) != bool(target & AFTERMARKET):
        return None, 'originalidad_distinta'
    if bool(source & PACK) != bool(target & PACK):
        return None, 'presentacion_distinta'
    # Una marca de destino («para Brother») no es la marca del fabricante.
    brand_text = re.split(r'\b(?:para|for|compatible\s+con|compatible\s+with)\b',
                         ' '.join(words(product.get('name'))), maxsplit=1)[0]
    declared_brands = [set(words(a.get('value_name'))) for a in product.get('attributes') or []
                       if isinstance(a, dict) and a.get('id') == 'BRAND' and a.get('value_name')]
    # Marca declarada por ML compatible si una contiene a la otra: «Logitech G» vs «Logitech» (07/11 rechazaba
    # el Logitech G Pro X2 Superstrike correcto por exigir igualdad exacta).
    if (not brand or (declared_brands and not any(brand <= value or value <= brand for value in declared_brands))
            or not brand <= (set(words(brand_text)) | set().union(*declared_brands))):
        return None, 'marca_ausente_o_distinta'
    # Comparar códigos por tokens completos; V3 no coincide con V30.
    parts = words(name)
    candidate_codes = {''.join(parts[i:i + size]) for size in range(1, 5) for i in range(len(parts))}
    for model in identity['models']:
        if code(model) not in candidate_codes:
            return None, f'modelo_ausente_o_distinto:{model}'
    # Variante (Pro/Flex/Duo…) del título o del modelo estructurado (raw.model «Naga V3 Pro»).
    known = source | set(words(' '.join(identity['line'] + identity.get('suffix', []))))
    if (known & QUALIFIERS) != (target & QUALIFIERS):
        return None, 'variante_ausente_o_distinta'
    if not set(words(' '.join(identity.get('suffix', [])))) <= target:
        return None, 'submodelo_ausente_o_distinto'
    line_words = set(words(' '.join(identity['line']))) - set(words(' '.join(identity['models'])))
    if not line_words <= target:
        return None, 'linea_ausente_o_distinta'
    source_types = {kind for kind, aliases in TYPE_WORDS.items() if source & aliases}
    target_types = {kind for kind, aliases in TYPE_WORDS.items() if target & aliases}
    if {'disco', 'solido'} <= target:
        target_types.add('ssd')
    if {'camara', 'deportiva'} <= target:
        target_types.add('camara_deportiva')
    if target_types - source_types:
        return None, 'tipo_contradictorio:' + ','.join(sorted(target_types - source_types))
    if source_types and not source_types & target_types:
        return None, 'tipo_no_confirmado'
    expected, actual = capacities(identity['title']), capacities(name)
    if expected and expected != actual:
        return None, 'capacidad_ausente_o_distinta'
    shared = (source & target) - brand - FILLER
    if not identity['models'] and not identity['line']:
        # Sin pieza conocida, exigir las palabras de la línea además de la marca/tipo.
        distinctive = source - brand - FILLER - set().union(*TYPE_WORDS.values())
        distinctive = {w for w in distinctive if w.isalpha() and len(w) > 2}
        if not distinctive or not distinctive <= target:
            return None, 'linea_no_confirmada'
    return 100 * len(identity['models']) + 10 * len(identity['line']) + len(shared), 'identidad_confirmada'
