import { promises as fs } from 'node:fs';
import { createHash } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { deployOnce, nextRunAt } from './deploy.mjs';

let dir: string;
let opts: any;
let commands: string[];
const sha = 'b'.repeat(40);
const now = (hour: string) => new Date(`2026-11-05T${hour}:00Z`);
beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'segunda-'));
  const workDir = path.join(dir, 'work');
  await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
  await fs.mkdir(path.join(workDir, 'dist'));
  await fs.writeFile(path.join(workDir, 'data', 'catalog.json'), '[{"slug":"p"}]');
  await fs.writeFile(path.join(workDir, 'dist', 'estado.json'), '{"publicados":1}');
  vi.stubEnv('CLOUDFLARE_API_TOKEN', 'test');
  vi.stubEnv('CLOUDFLARE_ACCOUNT_ID', 'test');
  commands = [];
  opts = { workDir, stateFile: path.join(dir, 'state.json'), outputFile: path.join(dir, 'ml.json'),
    amazonOutputFile: path.join(dir, 'amazon.json'),
    runImpl: async (cmd: string, args: string[]) => { commands.push(`${cmd} ${args[0]}`); return sha; } };
  await prices('ml', 0);
  await prices('amazon', 0);
});
afterEach(async () => { vi.unstubAllEnvs(); vi.restoreAllMocks(); await fs.rm(dir, { recursive: true, force: true }); });
async function prices(source: string, attempt: number) {
  await fs.writeFile(source === 'ml' ? opts.outputFile : opts.amazonOutputFile,
    JSON.stringify({ date: '2026-11-05', slot: `2026-11-05T${attempt ? '13' : '06'}`, attempts: attempt,
      items: { p: { amount: 150 + attempt } } }));
}
async function state() { return JSON.parse(await fs.readFile(opts.stateFile, 'utf8')); }

it('publica SHA, hash del catálogo efectivo y slot antes de llamar a wrangler', async () => {
  const run = opts.runImpl;
  opts.runImpl = async (cmd: string, args: string[]) => {
    if (cmd === 'npx') {
      const published = JSON.parse(await fs.readFile(path.join(opts.workDir, 'dist/estado.json'), 'utf8'));
      expect(published.version).toEqual({ sha, catalogHash: createHash('sha256').update('[{"slug":"p"}]').digest('hex') });
      expect(published.slot).toBe('2026-11-05T06');
    }
    return run(cmd, args);
  };
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  expect((await state()).version.sha).toBe(sha);
  expect((await state()).priceSlot).toBe('2026-11-05T06');
});

it('detecta cambios de ML y Amazon, persiste dos recuperaciones y omite contenido idéntico', async () => {
  const log = vi.spyOn(process.stdout, 'write').mockReturnValue(true);
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  expect(await deployOnce(now('11:00'), opts)).toBe('skip');
  await prices('ml', 1);
  expect(await deployOnce(now('16:00'), opts)).toBe('ok');
  expect((await state()).redeploys).toBe(1);
  expect(await deployOnce(now('17:00'), opts)).toBe('skip');
  await prices('amazon', 2);
  expect(await deployOnce(now('22:59'), opts)).toBe('ok');
  expect((await state()).redeploys).toBe(2);
  await prices('ml', 3);
  expect(await deployOnce(now('22:59'), opts)).toBe('skip');
  expect(commands.filter(c => c.startsWith('npx'))).toHaveLength(3);
  expect(log.mock.calls.filter(([text]) => String(text).includes('DEPLOY_OK') && String(text).includes('(redespliegue por precios recuperados)'))).toHaveLength(2);
});

it('corta exactamente a las 20 ART y no consume cupo por fallas', async () => {
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  await prices('ml', 1);
  expect(await deployOnce(now('16:00'), { ...opts, runImpl: async () => { throw new Error('falló build'); } })).toBe('fail');
  expect((await state()).redeploys).toBe(0);
  expect(await deployOnce(now('23:00'), opts)).toBe('skip');
  expect(commands.filter(c => c.startsWith('npx'))).toHaveLength(1);
  expect(nextRunAt(now('22:59'), await state())).toBe(now('23:00').getTime());
  expect(nextRunAt(now('23:00'), await state())).toBe(Date.parse('2026-11-06T10:00:00Z'));
  // 05/11: sin tope diario de redespliegues; sólo 30 min de separación desde el último despliegue.
  expect(nextRunAt(now('16:00'), { date: '2026-11-05', redeploys: 2 })).toBe(now('16:10').getTime());
  expect(nextRunAt(now('16:00'), { date: '2026-11-05', redeploys: 5, deployedAt: now('15:50').toISOString() }))
    .toBe(now('16:20').getTime());
});

it('redespliega más de dos veces por día, con 30 min entre despliegues', async () => {
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  for (const [i, hora] of [[1, '11:00'], [2, '12:00'], [3, '13:00']] as const) {
    await prices('ml', i);
    expect(await deployOnce(now(hora), opts)).toBe('ok');
  }
  await prices('ml', 4);
  expect(await deployOnce(now('13:10'), opts)).toBe('skip');   // menos de 30 min desde el último
  expect((await state()).redeploys).toBe(3);
});

it('no redespliega si alguno de los archivos dejó de ser de hoy', async () => {
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  await fs.writeFile(opts.amazonOutputFile, '{"date":"2026-11-04","items":{"p":{}}}');
  expect(await deployOnce(now('16:00'), opts)).toBe('fail');
  expect(commands.filter(c => c.startsWith('npx'))).toHaveLength(1);
});

it.each(['slot', 'attempts', 'items'])('detecta cambios aislados en %s', async field => {
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  const data = JSON.parse(await fs.readFile(opts.outputFile, 'utf8'));
  data[field] = field === 'slot' ? '2026-11-05T13' : field === 'attempts' ? 1 : { p: { amount: 180 } };
  await fs.writeFile(opts.outputFile, JSON.stringify(data));
  expect(await deployOnce(now('16:00'), opts)).toBe('ok');
  expect((await state()).redeploys).toBe(1);
});

it('el hash corresponde al catálogo luego del overlay y el contador se reinicia al cambiar el día', async () => {
  await fs.writeFile(opts.stateFile, JSON.stringify({ date: '2026-11-04', redeploys: 2 }));
  await fs.writeFile(path.join(dir, 'catalog-auto.json'), '[{"slug":"nuevo","asin":"A"}]');
  expect(await deployOnce(now('10:00'), opts)).toBe('ok');
  const catalog = await fs.readFile(path.join(opts.workDir, 'data/catalog.json'));
  const saved = await state();
  expect(saved.version.catalogHash).toBe(createHash('sha256').update(catalog).digest('hex'));
  expect(JSON.parse(catalog.toString())).toHaveLength(2);
  expect(saved.redeploys).toBe(0);
});

it('no publica metadatos con un SHA inválido', async () => {
  expect(await deployOnce(now('10:00'), { ...opts, runImpl: async () => '' })).toBe('fail');
  expect(commands).toEqual([]);
  await expect(fs.access(opts.stateFile)).rejects.toThrow();
});
