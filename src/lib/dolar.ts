type FetchedRates = {
  mep: number;
  tarjeta: number;
  oficial: number;
  fetchedAt: string;
  source: 'dolarapi.com';
};

/** Dos intentos por fuente; el plazo incluye la lectura del cuerpo. */
export async function fetchJsonWithRetry(url: string, fetchImpl: typeof fetch = fetch): Promise<any> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetchImpl(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      if (attempt === 1) throw new Error(`Falló la fuente ${url}: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      clearTimeout(timer);
    }
  }
}

export async function fetchRates(fetchImpl: typeof fetch = fetch): Promise<FetchedRates | null> {
  try {
    const data: unknown = await fetchJsonWithRetry('https://dolarapi.com/v1/dolares', fetchImpl);
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
  } catch (error) {
    console.warn(String(error));
    return null;
  }
}

/** Cuántos dólares vale un euro, cruzando el euro oficial con el dólar oficial de dolarapi. */
export async function fetchEurUsd(fetchImpl: typeof fetch = fetch): Promise<number | null> {
  try {
    const [eur, usd] = await Promise.all([
      fetchJsonWithRetry('https://dolarapi.com/v1/cotizaciones/eur', fetchImpl),
      fetchJsonWithRetry('https://dolarapi.com/v1/dolares/oficial', fetchImpl),
    ]);
    const e = eur?.venta;
    const u = usd?.venta;
    if (typeof e !== 'number' || typeof u !== 'number' || !(e > 0) || !(u > 0)) return null;
    return e / u;
  } catch (error) {
    console.warn(String(error));
    return null;
  }
}
