import { artDate, comparableChecks, type CatalogEntry } from './data';

/** El endpoint de estado usa sus mismos productos y su mismo instante para contar y explicar. */
export function publicationBreakdown(products: CatalogEntry[], origins: Record<string, string> = {}, now = Date.now()) {
  const stamp = new Date(now - 3 * 3600e3).toISOString().slice(0, 19).replace('T', ' ');
  const failures: Record<string, number> = {};
  let publicados = 0;
  const clean = (text: string) => text.replace(/[\r\n]+/g, ' ');
  const lines = products.map((product) => {
    const checks = comparableChecks(product, null, now);
    const ok = checks.every((check) => check.ok);
    if (ok) publicados++;
    for (const check of checks) {
      failures[check.filtro] ??= 0;
      if (!check.ok) failures[check.filtro]++;
    }
    return `${stamp} PRODUCTO ${clean(product.slug)} asin=${clean(product.asin || 'ausente')} origen=${origins[product.slug] === 'auto' ? 'auto' : 'repo'} ${ok ? 'PUBLICADO' : 'FILTRADO'} ` +
      checks.map((check) => `${check.filtro}=${check.ok ? 'ok' : 'FALLA'}(${clean(check.valor)})`).join(' ');
  });
  const totals = { total: products.length, publicados, filtrados: products.length - publicados, fallas: failures };
  lines.push(`${stamp} TOTALES total=${totals.total} publicados=${publicados} filtrados=${totals.filtrados}`);
  for (const [filter, count] of Object.entries(failures)) lines.push(`${stamp} FILTRO ${filter} fallas=${count}`);
  return { fecha: artDate(now), ...totals, content: lines.join('\n') + '\n' };
}
