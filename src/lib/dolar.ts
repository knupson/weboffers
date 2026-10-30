type FetchedRates = {
  mep: number;
  tarjeta: number;
  oficial: number;
  fetchedAt: string;
  source: 'dolarapi.com';
};

export async function fetchRates(fetchImpl: typeof fetch = fetch): Promise<FetchedRates | null> {
  try {
    const response = await fetchImpl('https://dolarapi.com/v1/dolares');
    if (!response.ok) return null;
    const data: unknown = await response.json();
    if (!Array.isArray(data)) return null;

    const venta = (casa: string): number | null => {
      const value: unknown = data.find((entry) => entry?.casa === casa)?.venta;
      return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
    };
    const mep = venta('bolsa');
    const tarjeta = venta('tarjeta');
    const oficial = venta('oficial');
    if (mep === null || tarjeta === null || oficial === null) return null;

    return { mep, tarjeta, oficial, fetchedAt: new Date().toISOString(), source: 'dolarapi.com' };
  } catch {
    return null;
  }
}

/** Cuántos dólares vale un euro, cruzando el euro oficial con el dólar oficial de dolarapi. */
export async function fetchEurUsd(fetchImpl: typeof fetch = fetch): Promise<number | null> {
  try {
    const [eur, usd] = await Promise.all([
      fetchImpl('https://dolarapi.com/v1/cotizaciones/eur').then((r) => (r.ok ? r.json() : null)),
      fetchImpl('https://dolarapi.com/v1/dolares/oficial').then((r) => (r.ok ? r.json() : null)),
    ]);
    const e = eur?.venta;
    const u = usd?.venta;
    if (typeof e !== 'number' || typeof u !== 'number' || !(e > 0) || !(u > 0)) return null;
    return e / u;
  } catch {
    return null;
  }
}
