import { useEffect, useMemo, useState } from "preact/hooks";
import { calculate } from "../lib/calc";
import { fetchEurUsd, fetchRates } from "../lib/dolar";
import { formatArs, formatUsd, formatStamp } from "../lib/format";

interface BuildRates {
  mep: number;
  tarjeta: number;
  oficial: number;
  fetchedAt: string;
}

interface Props {
  buildRates: BuildRates | null;
  initialFob?: number | null;
  title?: string;
  /** Moneda en la que cobra la tienda. Amazon.es cobra en euros. */
  currency?: "USD" | "EUR";
  /** Muestra el selector Amazon.com / Amazon.es. */
  switchable?: boolean;
}

type LiveRates = BuildRates & { live: boolean };

const num = (v: string) => {
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? n : 0;
};

const ars0 = (n: number) => Math.round(n).toLocaleString("es-AR");

export default function Calculator({ buildRates, initialFob = null, title = "Calculá el costo final", currency: initialCurrency = "USD", switchable = false }: Props) {
  const [currency, setCurrency] = useState(initialCurrency);
  const [eurUsd, setEurUsd] = useState<number | null>(null);
  const [fob, setFob] = useState(initialFob ? String(initialFob) : "");
  const [ship, setShip] = useState("");
  const [iva, setIva] = useState("21");
  const [duty, setDuty] = useState("35");
  const [local, setLocal] = useState("");
  const [rates, setRates] = useState<LiveRates | null>(buildRates ? { ...buildRates, live: false } : null);
  const [ratesFailed, setRatesFailed] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("fob");
    if (q && num(q) > 0) setFob(String(num(q)));
    fetchRates().then((r) => (r ? setRates({ ...r, live: true }) : setRatesFailed(true)));
  }, []);

  useEffect(() => {
    if (currency === "EUR" && eurUsd == null) fetchEurUsd().then(setEurUsd);
  }, [currency]);

  const toUsd = currency === "EUR" ? eurUsd ?? 0 : 1;

  const result = useMemo(
    () =>
      calculate(
        { fobUsd: num(fob) * toUsd, shippingUsd: num(ship) * toUsd, ivaRate: num(iva) / 100, dutyRate: num(duty) / 100 },
        rates
      ),
    [fob, ship, iva, duty, rates, toUsd]
  );

  const empty = num(fob) === 0 || toUsd === 0;
  const hasExcess = result.excessUsd > 0;
  const used = Math.min(1, result.fobUsd / 400);
  const localArs = num(local);
  const saving = result.totalArsMep != null && localArs > 0 ? localArs - result.totalArsMep : null;
  const extraWarnings = result.warnings.filter((w) => !w.startsWith("El régimen permite hasta 5"));

  return (
    <div class="calc">
      <div class="calc-inner">
        <form class="calc-in" onSubmit={(e) => e.preventDefault()}>
          <p class="title">{title}</p>
          {switchable && (
            <div class="field">
              <span class="lab" id="c-tienda">Tienda</span>
              <div class="seg" role="radiogroup" aria-labelledby="c-tienda">
                {[
                  ["USD", "Amazon.com (USD)"],
                  ["EUR", "Amazon.es (EUR)"],
                ].map(([v, label]) => (
                  <label key={v}>
                    <input type="radio" name="tienda" value={v} checked={currency === v} onChange={() => setCurrency(v as "USD" | "EUR")} />
                    {label}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div class="field">
            <label for="c-fob">Precio del producto</label>
            <div class="money">
              <span>{currency}</span>
              <input id="c-fob" class="in" inputMode="decimal" value={fob} onInput={(e) => setFob(e.currentTarget.value)} />
            </div>
            <small>
              {currency === "EUR"
                ? eurUsd
                  ? `El precio en euros de Amazon.es. Lo pasamos a dólares a 1 EUR = USD ${eurUsd.toFixed(3).replace(".", ",")} (oficial).`
                  : "El precio en euros de Amazon.es. Trayendo la cotización del euro..."
                : "El precio que ves en Amazon, sin envío ni impuestos."}
            </small>
          </div>
          <div class="field">
            <label for="c-ship">Envío a Argentina</label>
            <div class="money">
              <span>{currency}</span>
              <input id="c-ship" class="in" inputMode="decimal" value={ship} onInput={(e) => setShip(e.currentTarget.value)} />
            </div>
            <small>Amazon lo muestra en la ficha como "Shipping &amp; Import Charges". Desde USD 100, los productos elegibles tienen envío gratis: poné 0.</small>
          </div>
          <div class="field">
            <span class="lab" id="c-iva">IVA</span>
            <div class="seg" role="radiogroup" aria-labelledby="c-iva">
              {[
                ["21", "21%"],
                ["10.5", "10,5%"],
              ].map(([v, label]) => (
                <label key={v}>
                  <input type="radio" name="iva" value={v} checked={iva === v} onChange={() => setIva(v)} />
                  {label}
                </label>
              ))}
            </div>
            <small>Usamos 21%. El 10,5% depende del producto y no está confirmado.</small>
          </div>
          {hasExcess && (
            <div class="field">
              <label for="c-duty">Derechos sobre el excedente (%)</label>
              <input id="c-duty" class="in" inputMode="decimal" value={duty} onInput={(e) => setDuty(e.currentTarget.value)} />
              <small>Estimación. Varía según el producto.</small>
            </div>
          )}
          <div class="field">
            <label for="c-local">Precio en Argentina (opcional)</label>
            <div class="money">
              <span>ARS</span>
              <input id="c-local" class="in" inputMode="numeric" value={local} onInput={(e) => setLocal(e.currentTarget.value)} />
            </div>
            <small>Cargalo para ver cuánto ahorrás.</small>
          </div>
        </form>

        <div class="calc-out" aria-live="polite">
          <div>
            <p class="total-k">Te sale puesto en tu casa</p>
            <p class="total-v num">
              {empty ? "Cargá el precio" : result.totalArsMep != null ? formatArs(result.totalArsMep) : formatUsd(result.totalUsd)}
            </p>
            <div class="alt-v">
              {rates ? (
                <>
                  <span>al MEP <span class="num">${ars0(rates.mep)}</span></span>
                  {!empty && result.totalArsTarjeta != null && (
                    <span>Con tarjeta: <span class="num">{formatArs(result.totalArsTarjeta)}</span></span>
                  )}
                  {!empty && <span>En dólares: <span class="num">{formatUsd(result.totalUsd)}</span></span>}
                </>
              ) : (
                <span>{ratesFailed ? "No pude traer el dólar del día. Te muestro el total en dólares." : "Trayendo el dólar del día..."}</span>
              )}
            </div>
          </div>

          {empty ? (
            <p class="fine">Poné arriba el precio que ves en Amazon y acá aparece el total en pesos.</p>
          ) : (
            <>
              <div class={hasExcess ? "meter over" : "meter"}>
                <div class="meter-bar"><i style={{ transform: `scaleX(${used})` }} /></div>
                <p>
                  {hasExcess
                    ? `Te pasás de la franquicia por ${formatUsd(result.excessUsd)}. Ese excedente paga derechos.`
                    : `Usás ${formatUsd(result.fobUsd)} de los USD 400 de franquicia.`}
                </p>
              </div>

              {saving != null && (
                <p class={saving > 0 ? "note ok" : "note"}>
                  {saving > 0
                    ? `Ahorrás ${formatArs(saving)} contra el precio en Argentina.`
                    : "En Argentina te sale igual o menos. No conviene traerlo."}
                </p>
              )}
              {extraWarnings.map((w) => (
                <p class="note" key={w}>{w}</p>
              ))}

              <details class="break">
                <summary>Ver el desglose</summary>
                <div class="rows">
                  <div><span>Producto</span><span class="num">{formatUsd(result.fobUsd)}</span></div>
                  <div><span>Envío</span><span class="num">{formatUsd(result.shippingUsd)}</span></div>
                  <div><span>Derechos de importación</span><span class="num">{formatUsd(result.dutyUsd)}</span></div>
                  <div><span>Tasa de estadística</span><span class="num">{formatUsd(result.statFeeUsd)}</span></div>
                  <div><span>IVA {iva.replace(".", ",")}%</span><span class="num">{formatUsd(result.ivaUsd)}</span></div>
                  <div class="sum"><span>Total</span><span class="num">{formatUsd(result.totalUsd)}</span></div>
                </div>
              </details>
            </>
          )}

          <p class="fine">
            {rates
              ? rates.live
                ? `Dólar de dolarapi.com, ${formatStamp(rates.fetchedAt).replace(/\.$/, "")}. `
                : `Dólar guardado del ${formatStamp(rates.fetchedAt).replace(/\.$/, "")}. `
              : ""}
            Estimación orientativa. Cupo: 5 envíos por año y por persona.
          </p>
        </div>
      </div>
    </div>
  );
}
