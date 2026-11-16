"""Arma brand/carrusel/out/datos.json con los precios de hoy (data/*.json frescos de la Pi4).
Uso: python brand/carrusel/datos.py slug1 slug2=Nombre corto ...  (en el orden del carrusel; «=Nombre» opcional)"""
import sys, json, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reel'))
import hacer_reel as h

hoy = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).date().isoformat()
ml, az, cat = h.datos_hoy(hoy)
mep, eur = h.cotizaciones(True)
ps = {p['slug']: p for p in h.comparables(ml, az, cat, hoy, mep, eur)}
pedidos = [a.split('=', 1) + [None] if '=' not in a else a.split('=', 1) for a in sys.argv[1:]]
pedidos = [(x[0], x[1]) for x in pedidos]
faltan = [s for s, _ in pedidos if s not in ps]
if faltan:
    sys.exit(f'No comparables hoy: {faltan}')
out = []
for s, corto in pedidos:
    p = ps[s]
    # 16/11: ahorro con el mismo redondeo que la ficha (roundArs10k sobre la diferencia, 0 si es menor a $5.000).
    dif = abs(p['ml'] - p['az'])
    out.append(dict(slug=s, name=corto or p['name'], brand=p.get('brand', ''), category=p.get('category', ''),
                    ml=p['ml'], az=p['az'], gana=p['gana'] or ('ml' if p['ml'] <= p['az'] else 'amazon'),
                    ahorro=(h.redondear(dif / 10000) * 10000) if dif >= 5000 else 0))
d = Path(__file__).parent / 'out'
d.mkdir(exist_ok=True)
fecha = datetime.date.fromisoformat(hoy).strftime('%d/%m')
(d / 'datos.json').write_text(json.dumps(dict(fecha=fecha, total=len(ps), link='ofertas.knunet.com', productos=out),
                                         ensure_ascii=False, indent=2), encoding='utf-8')
for p in out:
    print(f"{p['slug']:32} ML {p['ml']:>9} AZ ~{p['az']:>9} gana {p['gana']:6} ahorro {p['ahorro']}")
print('total comparables', len(ps))
