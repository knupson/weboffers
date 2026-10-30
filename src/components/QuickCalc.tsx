import { useEffect, useState } from "preact/hooks";
import { calculate } from "../lib/calc";
import { fetchRates } from "../lib/dolar";
import { formatArs, formatUsd } from "../lib/format";
import { AMAZON_EXTRA } from "../lib/estimate";

interface Props {
  mep: number | null;
}

const MAX = 600;
// Medido el 30/10/2026: desde USD 100 Amazon envía gratis a Argentina los productos
// elegibles; debajo, el envío ronda USD 40 a 50.
const shippingFor = (fob: number) => (fob >= 100 ? 0 : 45);
const START = 279;

const usd0 = (n: number) => formatUsd(n).replace(",00", "");

// La cinta de la franquicia: arrastrás el precio y ves cuánto te sale puesto en tu casa.
export default function QuickCalc({ mep: buildMep }: Props) {
  const [fob, setFob] = useState(START);
  const [mep, setMep] = useState<number | null>(buildMep);

  useEffect(() => {
    fetchRates().then((r) => r && setMep(r.mep));
  }, []);

  const shipping = shippingFor(fob);
  const r = calculate({ fobUsd: fob, shippingUsd: shipping }, mep ? { mep, tarjeta: mep } : null);
  const totalUsd = r.totalUsd + fob * AMAZON_EXTRA;
  const over = r.excessUsd > 0;

  return (
    <div class={over ? "quick over" : "quick"} aria-live="polite">
      <p class="k">Si en Amazon sale</p>
      <p class="usd num">{usd0(fob)}</p>
      <div class="cinta" style={{ "--edge": `${(400 / MAX) * 100}%` }}>
        <span class="edge" aria-hidden="true">USD 400</span>
        <input
          type="range"
          min={0}
          max={MAX}
          step={5}
          value={fob}
          aria-label="Precio del producto en Amazon, en dólares"
          aria-valuetext={formatUsd(fob)}
          onInput={(e) => setFob(Number(e.currentTarget.value))}
        />
      </div>
      <p class="k">te sale puesto en tu casa</p>
      <p class="ars num">{mep ? formatArs(totalUsd * mep) : usd0(totalUsd)}</p>
      <p class="state">{shipping ? `Envío ≈ ${usd0(shipping)}: debajo de USD 100 no es gratis` : over ? `Envío gratis. Pagás derechos sobre ${usd0(r.excessUsd)}` : "Envío gratis y sin derechos de importación"}</p>
    </div>
  );
}
