"""Arma brand/carrusel/out/datos.json con los precios de hoy (data/*.json frescos de la Pi4).
Uso: python brand/carrusel/datos.py slug1 slug2 ...  (en el orden del carrusel)"""
import sys, json, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reel'))
import hacer_reel as h

hoy = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).date().isoformat()
ml, az, cat = h.datos_hoy(hoy)
mep, eur = h.cotizaciones(True)
ps = {p['slug']: p for p in h.comparables(ml, az, cat, hoy, mep, eur)}
faltan = [s for s in sys.argv[1:] if s not in ps]
if faltan:
    sys.exit(f'No comparables hoy: {faltan}')
out = []
for s in sys.argv[1:]:
    p = ps[s]
    out.append(dict(slug=s, name=p['name'], brand=p.get('brand', ''), category=p.get('category', ''),
                    ml=p['ml'], az=p['az'], gana=p['gana'] or ('ml' if p['ml'] <= p['az'] else 'amazon'),
                    ahorro=abs(p['ml'] - p['az'])))
d = Path(__file__).parent / 'out'
d.mkdir(exist_ok=True)
fecha = datetime.date.fromisoformat(hoy).strftime('%d/%m')
(d / 'datos.json').write_text(json.dumps(dict(fecha=fecha, total=len(ps), link='ofertas.knunet.com', productos=out),
                                         ensure_ascii=False, indent=2), encoding='utf-8')
for p in out:
    print(f"{p['slug']:32} ML {p['ml']:>9} AZ ~{p['az']:>9} gana {p['gana']:6} ahorro {p['ahorro']}")
print('total comparables', len(ps))
