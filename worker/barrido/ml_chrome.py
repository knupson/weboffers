"""Plan diario API → Chrome con perfil → selección, sin exponer CDP a otra red."""
import json
import os
from pathlib import Path

from .amazon_source import SourceError
from .events import emit_event, now_art
from .ml_lookup import MLClient, MLBudget


class ChromeLookup(MLClient):
    def __init__(self, config, output, *, prepare=False, max_catalogs=None, **kwargs):
        super().__init__(config, **kwargs)
        self.prepare = prepare
        self.output = Path(output)
        self.date = now_art().date().isoformat()
        self.path = self.output / f'ml-chrome-plan-{self.date}.json'
        self.plan = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'date': self.date, 'queries': {}, 'catalogos': []}
        if self.plan.get('date') != self.date:
            raise SourceError('El plan ML no es del día')
        self.max_catalogs = max_catalogs if max_catalogs is not None else int(os.environ.get('BARRIDO_ML_CATALOGOS', '400'))
        self.deadline = self.clock() + float(os.environ.get('BARRIDO_ML_SEGUNDOS', '600' if prepare else '120'))
        original_sleep = self.sleep
        def bounded_sleep(seconds):
            self.check_budget(seconds)
            original_sleep(seconds)
        self.sleep = bounded_sleep
        self.items = None
        if prepare:
            data = self.ml.load_json(self.ml.ruta_chrome(self.output.parent, self.date), {}) or {}
            self.read_today = {cid for cid, item in (data.get('items') or {}).items()
                               if isinstance(item, dict) and isinstance(item.get('results'), list)
                               and str(item.get('leido', '')).startswith(self.date)} if data.get('date') == self.date else set()
            self._save()  # incluso sin candidatos, la siguiente pasada recibe un plan del día

    def check_budget(self, seconds=0):
        if now_art().date().isoformat() != self.date:
            raise SourceError('Cambió el día ART durante el plan ML')
        if self.clock() + seconds >= self.deadline:
            raise MLBudget('tiempo_ml_agotado')

    def _save(self):
        self.output.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.plan, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.path)

    def _retry(self, perform, path):
        def bounded():
            self.check_budget(30)  # deja terminar el timeout HTTP y persistir el plan
            return perform()
        return super()._retry(bounded, path)

    def search(self, query):
        self.check_budget()
        if query not in self.plan['queries']:
            if not self.prepare:
                raise MLBudget('consulta_fuera_del_plan_chrome')
            self.plan['queries'][query] = super().search(query)
            self._save()
        return self.plan['queries'][query]

    def cheapest(self, identity):
        self.check_budget()
        if self.prepare:
            if identity not in self.plan['catalogos']:
                if identity not in self.read_today and len(set(self.plan['catalogos']) - self.read_today) >= self.max_catalogs:
                    raise MLBudget('tope_catalogos_chrome')
                self.plan['catalogos'].append(identity)
                self._save()
            return None  # sólo el plan; esta pasada nunca escribe ml-candidatos
        if self.items is None:
            path = self.ml.ruta_chrome(self.output.parent, self.date)
            data = self.ml.load_json(path, {}) or {}
            self.items = data.get('items', {}) if data.get('date') == self.date else {}
        item = self.items.get(identity) or {}
        results, reason = item.get('results'), item.get('motivo', 'sin_lectura')
        if not str(item.get('leido') or '').startswith(self.date):
            results, reason = None, 'lectura_fuera_del_dia'
        if identity not in self.items:
            # Chrome llegó al tope: no gastar el checkpoint confirmando errores en lo que quedó pendiente.
            emit_event('BARRIDO_ML_CHROME_CATALOGO', catalogo=identity, ofertas=None, motivo='pendiente_por_presupuesto')
            raise MLBudget('catalogo_pendiente_chrome')
        emit_event('BARRIDO_ML_CHROME_CATALOGO', catalogo=identity,
                   ofertas=len(results) if isinstance(results, list) else None, motivo=reason)
        if not isinstance(results, list) and (reason == 'sin_items' or reason.startswith('pagina_de_otro_catalogo')):
            # 27/11: el 1.er candidato sin ofertas cortaba el producto entero y no se probaba el 2.º
            # (Vornado AVH10: MLA25262595 vacío, MLA61407692 con oferta). En el alta, saltear un catálogo
            # no publica nada; es lo mismo que el 404 de la API («catalogo_sin_ofertas_404»).
            emit_event('BARRIDO_DESCARTE', motivo='catalogo_sin_ofertas_chrome', valor=identity, detalle=reason)
            return None
        if not isinstance(results, list):
            raise SourceError(f'Chrome ML {identity}: {reason}')
        return self.select_offers(identity, results)
