// 13/11: IndexNow tras cada deploy OK, sin poder romperlo nunca.
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { avisarIndexNow, deployOnce } from './deploy.mjs';

let dir: string;
const sitemap = (urls: string[]) =>
  `<?xml version="1.0"?><urlset>${urls.map((u) => `<url><loc>${u}</loc></url>`).join('')}</urlset>`;

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'indexnow-test-'));
});
afterEach(async () => {
  await fs.rm(dir, { recursive: true, force: true });
});

it('manda las URLs de los sitemap-N.xml del build (no las del índice) y acepta 202', async () => {
  await fs.writeFile(path.join(dir, 'sitemap-index.xml'), sitemap(['https://ofertas.knunet.com/sitemap-0.xml']));
  await fs.writeFile(path.join(dir, 'sitemap-0.xml'), sitemap(['https://ofertas.knunet.com/', 'https://ofertas.knunet.com/productos/a/']));
  const calls: any[] = [];
  const fetchImpl = async (url: string, init: any) => { calls.push([url, JSON.parse(init.body)]); return { status: 202 }; };
  expect(await avisarIndexNow(dir, { fetchImpl })).toBe('ok');
  expect(calls).toHaveLength(1);
  expect(calls[0][0]).toBe('https://api.indexnow.org/indexnow');
  expect(calls[0][1].urlList).toEqual(['https://ofertas.knunet.com/', 'https://ofertas.knunet.com/productos/a/']);
  expect(calls[0][1].host).toBe('ofertas.knunet.com');
});

it('una caída de la red o un código distinto de 200/202 es sólo un aviso', async () => {
  await fs.writeFile(path.join(dir, 'sitemap-0.xml'), sitemap(['https://ofertas.knunet.com/']));
  expect(await avisarIndexNow(dir, { fetchImpl: async () => { throw new Error('fetch failed'); } })).toBe('aviso');
  expect(await avisarIndexNow(dir, { fetchImpl: async () => ({ status: 429 }) })).toBe('aviso');
});

it('sin sitemap en el build no llama a la red', async () => {
  let llamadas = 0;
  expect(await avisarIndexNow(dir, { fetchImpl: async () => { llamadas += 1; return { status: 200 }; } })).toBe('aviso');
  expect(llamadas).toBe(0);
});

it('el deploy queda OK aunque IndexNow falle', async () => {
  const workDir = path.join(dir, 'work');
  await fs.mkdir(path.join(workDir, '.git'), { recursive: true });
  await fs.mkdir(path.join(workDir, 'dist'), { recursive: true });
  await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
  await fs.writeFile(path.join(workDir, 'data', 'catalog.json'), '[]');
  await fs.writeFile(path.join(workDir, 'dist', 'estado.json'), JSON.stringify({ publicados: 100 }));
  await fs.writeFile(path.join(workDir, 'dist', 'sitemap-0.xml'), sitemap(['https://ofertas.knunet.com/']));
  const outputFile = path.join(dir, 'ml-prices.json');
  const amazonOutputFile = path.join(dir, 'amazon-prices.json');
  await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
  await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 100 } } }));
  process.env.CLOUDFLARE_API_TOKEN = 'test-token';
  process.env.CLOUDFLARE_ACCOUNT_ID = 'test-account';
  let llamadas = 0;
  // LOG_DIR se lee al importar deploy.mjs: el aviso se comprueba en la salida estándar.
  const salida: string[] = [];
  const espia = vi.spyOn(process.stdout, 'write').mockImplementation((texto: any) => { salida.push(String(texto)); return true; });
  const result = await deployOnce(new Date('2026-10-30T10:00:00Z'), {
    // logDir propio, como los otros tests del deployer: sin él el desglose va a /state/logs (sin permiso fuera de root).
    outputFile, amazonOutputFile, workDir, stateFile: path.join(dir, 'state', 'last-deploy.json'), logDir: path.join(dir, 'logs'),
    fetchImpl: async () => { llamadas += 1; throw new Error('indexnow caído'); },
    runImpl: async (cmd: string, args: string[], _cwd: string, _exec: unknown, env: any) => {
      if (cmd === 'git' && args[0] === 'rev-parse') return 'a'.repeat(40);
      if (cmd === 'npm' && args[0] === 'run') {
        await fs.writeFile(env.CADENA_DESGLOSE_PATH, JSON.stringify({ publicados: 100, content: 'TOTALES simulados\n' }));
      }
      return '';
    },
  });
  espia.mockRestore();
  expect(result).toBe('ok');
  expect(llamadas).toBe(1);
  expect(salida.join('')).toContain('INDEXNOW_AVISO indexnow caído');
});
