import { expect, it, vi } from 'vitest';
import { GET } from '../pages/estado.json';
import { loadMlPrices } from './data';
vi.mock('./data', () => ({
  loadProducts: vi.fn(async () => ({ products: [] })),
  isComparable: vi.fn(() => false),
  loadAmazonPrices: vi.fn(() => null),
  loadMlPrices: vi.fn(() => ({ slot: '2026-11-05T13' })),
}));
it('expone el slot de ML publicado y tolera archivos anteriores sin slot', async () => {
  expect((await (await GET()).json()).slot).toBe('2026-11-05T13');
  vi.mocked(loadMlPrices).mockReturnValue(null);
  expect((await (await GET()).json()).slot).toBeNull();
});
