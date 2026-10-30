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

const ars0 = (n: number) => Math.round(n).toLocaleString("es-AR");

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
      if (r) {
        setRates({ ...r, live: true });
        document.querySelectorAll<HTMLElement>("[data-rate]").forEach((el) => {
          const key = el.dataset.rate as "mep" | "tarjeta";
          el.textContent = `$${ars0(r[key])}`;
        });
      } else setRatesFailed(true);
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
    <div class="calc-grid">
      <div class="table">
        <div class="t">Datos de la compra</div>
        <form class="body" onSubmit={(e) => e.preventDefault()}>
          <label class="field">
            <span class="k">Precio del producto (USD)</span>
            <input class="in" inputMode="decimal" value={fob} onInput={(e) => setFob(e.currentTarget.value)} />
            <small>Sin envío ni impuestos. La franquicia cubre hasta USD 400.</small>
          </label>
          <label class="field">
            <span class="k">Envío a Argentina (USD)</span>
            <input class="in" inputMode="decimal" value={ship} onInput={(e) => setShip(e.currentTarget.value)} />
            <small>Lo ves en Amazon antes de pagar.</small>
          </label>
          <label class="field">
            <span class="k">IVA</span>
            <select class="in" value={iva} onChange={(e) => setIva(e.currentTarget.value)}>
              <option value="21">21% (por defecto)</option>
              <option value="10.5">10,5% (sin verificar)</option>
            </select>
            <small>Depende de la posición arancelaria del producto.</small>
          </label>
          {hasExcess && (
            <label class="field">
              <span class="k">Derechos sobre el excedente (%)</span>
              <input class="in" inputMode="decimal" value={duty} onInput={(e) => setDuty(e.currentTarget.value)} />
              <small>Estimación. Varía por producto.</small>
            </label>
          )}
          <label class="field">
            <span class="k">Precio en tienda argentina (ARS, opcional)</span>
            <input class="in" inputMode="numeric" value={local} placeholder="890000" onInput={(e) => setLocal(e.currentTarget.value)} />
            <small>Lo cargás vos, para comparar.</small>
          </label>
        </form>
      </div>

      <div class="table" aria-live="polite">
        <div class="t">Liquidación estimada</div>
        <div class="row"><span class="lab">Producto</span><span class="v">{formatUsd(result.fobUsd)}</span></div>
        <div class="row"><span class="lab">Envío</span><span class="v">{formatUsd(result.shippingUsd)}</span></div>
        <div class="row">
          <span class="lab">Derechos de importación</span>
          <span class="v">{hasExcess ? formatUsd(result.dutyUsd) : "USD 0,00"}</span>
        </div>
        <div class="row">
          <span class="lab">Tasa de estadística</span>
          <span class="v">{hasExcess ? formatUsd(result.statFeeUsd) : "USD 0,00"}</span>
        </div>
        <div class="row">
          <span class="lab">IVA ({iva.replace(".", ",")}%)</span>
          <span class="v">{formatUsd(result.ivaUsd)}</span>
        </div>
        <div class="row total"><span class="lab">Total</span><span class="v">{formatUsd(result.totalUsd)}</span></div>

        {rates ? (
          <div class="pesos">
            <div class="row">
              <span class="lab">En pesos al MEP (${ars0(rates.mep)})</span>
              <span class="v big">{result.totalArsMep != null ? formatArs(result.totalArsMep) : "-"}</span>
            </div>
            <div class="row">
              <span class="lab">En pesos al dólar tarjeta (${ars0(rates.tarjeta)})</span>
              <span class="v">{result.totalArsTarjeta != null ? formatArs(result.totalArsTarjeta) : "-"}</span>
            </div>
          </div>
        ) : (
          <p class="state">
            {ratesFailed
              ? "No pude traer la cotización del dólar. El total en dólares está bien, el pasaje a pesos no está disponible ahora."
              : "Trayendo la cotización del dólar..."}
          </p>
        )}

        <div style="padding: 0 var(--s2) var(--s2)">
          <p class={hasExcess ? "state" : "state ok"}>
            {hasExcess
              ? `Pasás la franquicia por ${formatUsd(result.excessUsd)}. Ese excedente paga derechos.`
              : "Dentro de la franquicia: sin derechos de importación ni tasa de estadística."}
          </p>
          {saving != null && (
            <p class={saving > 0 ? "state ok" : "state"}>
              {saving > 0
                ? `Contra el precio local que cargaste, la diferencia a favor es de ${formatArs(saving)}.`
                : "El precio local que cargaste es igual o menor que el total puesto en tu casa."}
            </p>
          )}
          {extraWarnings.map((w) => (
            <p class="state" key={w}>{w}</p>
          ))}
          {rates && (
            <p class="stamp">
              {rates.live
                ? `Cotización de dolarapi.com del ${formatStamp(rates.fetchedAt)}`
                : `No pude actualizar la cotización. Uso la última guardada, del ${formatStamp(rates.fetchedAt)}`}
            </p>
          )}
          <p class="stamp">Estimación orientativa. Cupo: 5 envíos por año y por persona.</p>
        </div>
      </div>
    </div>
  );
}
