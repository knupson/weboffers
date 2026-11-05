import fs from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { fetchJsonWithRetry, fetchRates, fetchEurUsd } from './dolar';
import { loadOffers, loadProducts } from './data';
import * as estimate from './estimate';

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it('aborta cada intento a los 15 segundos e identifica la fuente', async () => {
  vi.useFakeTimers();
  const signals: AbortSignal[] = [];
  const fetcher = vi.fn<typeof fetch>((_url, options) => new Promise((_resolve, reject) => {
    const signal = options!.signal!;
    signals.push(signal);
    signal.addEventListener('abort', () => reject(new Error('timeout')));
  }));
  const promise = fetchJsonWithRetry('https://fuente/cotizacion', fetcher);
  const assertion = expect(promise).rejects.toThrow('https://fuente/cotizacion: timeout');
  await vi.advanceTimersByTimeAsync(14999);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(signals[0].aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(signals[0].aborted).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(signals[1]).not.toBe(signals[0]);
  await vi.advanceTimersByTimeAsync(15000);
  await assertion;
  expect(signals[1].aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it('reintenta HTTP o JSON fallido y libera temporizadores al recuperarse', async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response('', { status: 503 }))
    .mockResolvedValueOnce(new Response('{"venta":1234}'));
  expect(await fetchJsonWithRetry('https://fuente', fetcher)).toEqual({ venta: 1234 });
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
});

it('aplica el plazo también a un cuerpo que no termina de llegar', async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn<typeof fetch>((_url, options) => Promise.resolve({ ok: true,
    json: () => new Promise((_resolve, reject) => options!.signal!.addEventListener('abort', () => reject(new Error('cuerpo demorado'))))
  } as Response));
  const assertion = expect(fetchJsonWithRetry('https://fuente', fetcher)).rejects.toThrow('cuerpo demorado');
  await vi.advanceTimersByTimeAsync(30000);
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('las cotizaciones de dólar y euro recuperan una falla transitoria por fuente', async () => {
  const counts = new Map<string, number>();
  const fetcher = vi.fn<typeof fetch>(async url => {
    const source = String(url);
    const count = (counts.get(source) ?? 0) + 1;
    counts.set(source, count);
    if (count === 1) throw new Error('sin red');
    return new Response(JSON.stringify(source.endsWith('/dolares')
      ? ['bolsa', 'tarjeta', 'oficial'].map(casa => ({ casa, venta: 1000 }))
      : { venta: source.includes('/eur') ? 1100 : 1000 }));
  });
  expect((await fetchRates(fetcher))?.mep).toBe(1000);
  expect(await fetchEurUsd(fetcher)).toBeCloseTo(1.1);
  expect([...counts.values()]).toEqual([2, 2, 2]);
});

it('OFFERS_URL tiene dos intentos acotados y conserva el respaldo local', async () => {
  vi.useFakeTimers();
  vi.stubEnv('OFFERS_URL', 'https://ofertas/cotizaciones');
  const fetcher = vi.fn<typeof fetch>((_url, options) => new Promise((_resolve, reject) => {
    options!.signal!.addEventListener('abort', () => reject(new Error('timeout')));
  }));
  vi.stubGlobal('fetch', fetcher);
  vi.spyOn(fs, 'readFileSync').mockReturnValue('{"items":[],"rates":{"mep":1234}}');
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const promise = loadOffers();
  await vi.advanceTimersByTimeAsync(30000);
  expect((await promise).rates?.mep).toBe(1234);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(warn.mock.calls.flat().map(String).join(' ')).toContain('https://ofertas/cotizaciones');
});

it('expone el MEP efectivo del cálculo y la cabecera lo mantiene fijo', async () => {
  const layout = fs.readFileSync(new URL('../layouts/Base.astro', import.meta.url), 'utf8');
  expect(layout).toContain('Math.round(buildMep)');
  expect(layout).toContain('MEP usado en cálculos');
  expect(layout).not.toContain('fetchRates');
  expect(layout).not.toContain('[data-rate]');
  vi.stubEnv('OFFERS_URL', '');
  vi.spyOn(estimate, 'buildQuotes').mockResolvedValue({ mep: 1300, eurUsd: 1.1 });
  vi.spyOn(fs, 'readFileSync').mockImplementation(((file: string) =>
    String(file).endsWith('offers.json') ? '{"items":[],"rates":{"mep":1200}}' : '[]') as typeof fs.readFileSync);
  expect((await loadProducts()).buildMep).toBe(1300);
});
