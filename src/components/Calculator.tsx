import { useEffect, useMemo, useState } from "preact/hooks";
import { calculate } from "../lib/calc";
import { fetchRates } from "../lib/dolar";
import { formatArs, formatUsd, formatStamp } from "../lib/format";

interface BuildRates {
  mep: number;
  tarjeta: number;
  oficial: number;
  fetchedAt: string;
}

interface Props {
  buildRates: BuildRates | null;
}

type LiveRates = BuildRates & { live: boolean };

const num = (v: string) => {
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? n : 0;
};

export default function Calculator({ buildRates }: Props) {
  const [fob, setFob] = useState("279");
  const [ship, setShip] = useState("54");
  const [iva, setIva] = useState("21");
  const [duty, setDuty] = useState("35");
  const [local, setLocal] = useState("");
  const [rates, setRates] = useState<LiveRates | null>(
    buildRates ? { ...buildRates, live: false } : null
  );
  const [ratesFailed, setRatesFailed] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("fob");
    if (q && num(q) > 0) setFob(String(num(q)));
    fetchRates().then((r) => {
      if (r) setRates({ ...r, live: true });
      else setRatesFailed(true);
    });
  }, []);

  const result = useMemo(
    () =>
      calculate(
        { fobUsd: num(fob), shippingUsd: num(ship), ivaRate: num(iva) / 100, dutyRate: num(duty) / 100 },
        rates
      ),
    [fob, ship, iva, duty, rates]
  );

  const hasExcess = result.excessUsd > 0;
  const localArs = num(local);
  const saving = result.totalArsMep != null && localArs > 0 ? localArs - result.totalArsMep : null;
  const extraWarnings = result.warnings.filter((w) => !w.startsWith("El régimen permite hasta 5"));

  return (
    <div class="calc">
      <form class="inputs" onSubmit={(e) => e.preventDefault()}>
        <label>
          <span>Precio del producto (USD)</span>
          <input class="input" inputMode="decimal" value={fob} onInput={(e) => setFob(e.currentTarget.value)} />
          <small>Sin envío ni impuestos. La franquicia cubre hasta USD 400.</small>
        </label>
        <label>
          <span>Envío a Argentina (USD)</span>
          <input class="input" inputMode="decimal" value={ship} onInput={(e) => setShip(e.currentTarget.value)} />
          <small>Lo ves en Amazon antes de pagar.</small>
        </label>
        <label>
          <span>IVA</span>
          <select class="input" value={iva} onChange={(e) => setIva(e.currentTarget.value)}>
            <option value="21">21% (valor por defecto)</option>
            <option value="10.5">10,5% (sin verificar)</option>
          </select>
          <small>Depende de la posición arancelaria del producto.</small>
        </label>
        {hasExcess && (
          <label>
            <span>Derechos de importación sobre el excedente (%)</span>
            <input class="input" inputMode="decimal" value={duty} onInput={(e) => setDuty(e.currentTarget.value)} />
            <small>Estimación. Varía por producto.</small>
          </label>
        )}
        <label>
          <span>Precio en una tienda argentina (ARS, opcional)</span>
          <input class="input" inputMode="numeric" value={local} placeholder="Ej. 890000" onInput={(e) => setLocal(e.currentTarget.value)} />
          <small>Lo cargás vos, para comparar.</small>
        </label>
      </form>

      <div class="card ledger" aria-live="polite">
        <dl>
          <div><dt>Producto</dt><dd class="mono">{formatUsd(result.fobUsd)}</dd></div>
          <div><dt>Envío</dt><dd class="mono">{formatUsd(result.shippingUsd)}</dd></div>
          <div>
            <dt>Derechos de importación</dt>
            <dd class="mono">{hasExcess ? formatUsd(result.dutyUsd) : "USD 0,00"}</dd>
          </div>
          <div>
            <dt>Tasa de estadística</dt>
            <dd class="mono">{hasExcess ? formatUsd(result.statFeeUsd) : "USD 0,00"}</dd>
          </div>
          <div><dt>IVA ({iva.replace(".", ",")}%)</dt><dd class="mono">{formatUsd(result.ivaUsd)}</dd></div>
          <div class="total"><dt>Total</dt><dd class="mono">{formatUsd(result.totalUsd)}</dd></div>
        </dl>

        <p class={hasExcess ? "state over" : "state in"}>
          {hasExcess
            ? `Pasás la franquicia por ${formatUsd(result.excessUsd)}. Ese excedente paga derechos.`
            : "Dentro de la franquicia: sin derechos de importación ni tasa de estadística."}
        </p>

        {rates ? (
          <div class="pesos">
            <div>
              <span class="lab">En pesos al MEP (${Math.round(rates.mep).toLocaleString("es-AR")})</span>
              <strong class="mono big">{result.totalArsMep != null ? formatArs(result.totalArsMep) : "-"}</strong>
            </div>
            <div>
              <span class="lab">En pesos al dólar tarjeta (${Math.round(rates.tarjeta).toLocaleString("es-AR")})</span>
              <strong class="mono">{result.totalArsTarjeta != null ? formatArs(result.totalArsTarjeta) : "-"}</strong>
            </div>
            <p class="stamp">
              {rates.live
                ? `Cotización de dolarapi.com del ${formatStamp(rates.fetchedAt)}`
                : `No pude actualizar la cotización. Uso la última guardada, del ${formatStamp(rates.fetchedAt)}`}
            </p>
          </div>
        ) : (
          <p class="state warn">
            {ratesFailed
              ? "No pude traer la cotización del dólar. El total en dólares está bien; el pasaje a pesos no está disponible ahora."
              : "Trayendo la cotización del dólar..."}
          </p>
        )}

        {saving != null && (
          <p class={saving > 0 ? "state in" : "state warn"}>
            {saving > 0
              ? `Contra el precio local que cargaste, la diferencia a favor es de ${formatArs(saving)}.`
              : "El precio local que cargaste es igual o menor que el total puesto en tu casa."}
          </p>
        )}

        {extraWarnings.map((w) => (
          <p class="state warn" key={w}>{w}</p>
        ))}
        <p class="stamp">Estimación orientativa. Tené en cuenta el cupo de 5 envíos por año y por persona.</p>
      </div>

      <style>{`
        .calc { display: grid; gap: 24px; grid-template-columns: 1fr; align-items: start; }
        @media (min-width: 900px) { .calc { grid-template-columns: 0.9fr 1.1fr; gap: 40px; } }
        .inputs { display: grid; gap: 20px; }
        .inputs label { display: grid; gap: 6px; }
        .inputs label > span { font-weight: 500; font-size: 0.9375rem; }
        .inputs small { color: var(--muted); font-size: 0.8125rem; }
        .ledger { padding: 28px; display: grid; gap: 20px; }
        dl { margin: 0; display: grid; }
        dl > div { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-top: 1px solid var(--line); }
        dl > div:first-child { border-top: 0; }
        dt { color: var(--muted); }
        dd { margin: 0; }
        .total { font-weight: 600; border-top: 1px solid var(--ink) !important; }
        .total dt { color: var(--ink); }
        .state { font-size: 0.9375rem; padding: 12px 14px; border-radius: var(--radius); margin: 0; }
        .state.in { background: var(--green-bg); color: var(--green-ink); }
        .state.over { background: var(--yellow-bg); color: var(--yellow-ink); }
        .state.warn { background: var(--yellow-bg); color: var(--yellow-ink); }
        .pesos { display: grid; gap: 14px; }
        .pesos > div { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
        .lab { color: var(--muted); font-size: 0.9375rem; }
        .big { font-size: 1.6rem; font-weight: 500; }
        .stamp { color: var(--muted); font-size: 0.8125rem; margin: 0; }
      `}</style>
    </div>
  );
}
