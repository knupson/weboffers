const ars = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  maximumFractionDigits: 0,
});

const usd = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "USD",
  currencyDisplay: "code",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const formatArs = (n: number) => ars.format(n);
export const formatUsd = (n: number) => usd.format(n).replace(/ /g, " ");

export function formatStamp(iso: string): string {
  return new Date(iso).toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Argentina/Buenos_Aires",
  });
}

/** "USD 399" o "EUR 189,99": sin decimales cuando el precio es redondo. */
export function formatPrice(n: number, currency: "USD" | "EUR"): string {
  const digits = Number.isInteger(n) ? 0 : 2;
  return `${currency} ${n.toLocaleString("es-AR", { minimumFractionDigits: digits, maximumFractionDigits: 2 })}`;
}
