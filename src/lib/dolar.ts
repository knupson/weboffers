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
