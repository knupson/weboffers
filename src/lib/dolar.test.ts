import { describe, expect, it, vi } from 'vitest';
import { fetchRates } from './dolar';

const payload = [
  { casa: 'oficial', nombre: 'Oficial', compra: 900, venta: 1000, fechaActualizacion: '2026-10-29' },
  { casa: 'tarjeta', nombre: 'Tarjeta', compra: 1400, venta: 1500, fechaActualizacion: '2026-10-29' },
  { casa: 'bolsa', nombre: 'Bolsa', compra: 1100, venta: 1200, fechaActualizacion: '2026-10-29' },
];

const mockFetch = (body: unknown, status = 200) =>
  vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe('fetchRates', () => {
  it('maps venta by casa and includes fetch metadata', async () => {
    const fetchImpl = mockFetch(payload);
    const before = Date.now();
    const result = await fetchRates(fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith('https://dolarapi.com/v1/dolares');
    expect(result).toEqual({
      mep: 1200, tarjeta: 1500, oficial: 1000,
      fetchedAt: expect.any(String), source: 'dolarapi.com',
    });
    const timestamp = Date.parse(result!.fetchedAt);
    expect(timestamp).toBeGreaterThanOrEqual(before);
    expect(timestamp).toBeLessThanOrEqual(Date.now());
    expect(new Date(timestamp).toISOString()).toBe(result!.fetchedAt);
  });

  it('returns null for network failures', async () => {
    expect(await fetchRates(vi.fn<typeof fetch>().mockRejectedValue(new Error('offline')))).toBeNull();
  });

  it('returns null for non-ok responses', async () => {
    expect(await fetchRates(mockFetch(payload, 503))).toBeNull();
  });

  it('returns null for invalid JSON', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('{'));
    expect(await fetchRates(fetchImpl)).toBeNull();
  });

  it.each(['bolsa', 'tarjeta', 'oficial'])('requires casa %s', async (casa) => {
    expect(await fetchRates(mockFetch(payload.filter((entry) => entry.casa !== casa)))).toBeNull();
  });

  it.each([null, {}, 'invalid', [null]])('rejects malformed payload %j', async (body) => {
    expect(await fetchRates(mockFetch(body))).toBeNull();
  });

  it.each(['bolsa', 'tarjeta', 'oficial'])('validates venta for %s', async (casa) => {
    for (const venta of [0, -1, NaN, Infinity, -Infinity, '1200', null, undefined]) {
      const data = payload.map((entry) => entry.casa === casa ? { ...entry, venta } : entry);
      const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue({
        ok: true, json: async () => data,
      } as Response);
      expect(await fetchRates(fetchImpl)).toBeNull();
    }
  });
});
