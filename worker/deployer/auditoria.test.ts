import { promises as fs } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { commandTimeout, deployOnce as actualDeployOnce, nextRunAt, purgeLogs, run } from './deploy.mjs';

async function deployOnce(now: Date, opts: any) {
  const runImpl = opts.runImpl;
  return actualDeployOnce(now, { ...opts, logDir: path.join(path.dirname(opts.stateFile), 'logs'),
    runImpl: async (cmd: string, args: string[], cwd: string, _exec: unknown, env: any) => {
      if (cmd === 'git' && args[0] === 'rev-parse') return 'a'.repeat(40);
      const result = await runImpl(cmd, args, cwd);
      if (cmd === 'npm' && args[0] === 'run') {
        const state = JSON.parse(await fs.readFile(path.join(cwd, 'dist', 'estado.json'), 'utf8'));
        await fs.writeFile(env.CADENA_DESGLOSE_PATH, JSON.stringify({ publicados: state.publicados, content: '2026-11-06 04:00:00 TOTALES simulados\n' }));
      }
      return result;
    } });
}
import { validatePriceFiles } from '../../tools/validate-price-files.mjs';

let dir: string;
beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'audit-'));
  vi.stubEnv('CLOUDFLARE_API_TOKEN', 'test');
  vi.stubEnv('CLOUDFLARE_ACCOUNT_ID', 'test');
});
afterEach(async () => { vi.unstubAllEnvs(); await fs.rm(dir, { recursive: true, force: true }); });

it('programa la siguiente ventana despues del vencimiento', () => {
  expect(nextRunAt(new Date('2026-11-05T14:00:00Z'), null)).toBe(Date.parse('2026-11-06T10:00:00Z'));
  expect(nextRunAt(new Date('2026-11-04T23:00:00Z'), { date: '2026-11-04' })).toBe(Date.parse('2026-11-05T10:00:00Z'));
});

it('aplica timeout por comando e identifica el comando colgado', async () => {
  expect(commandTimeout('git')).toBe(120000);
  expect(commandTimeout('npm')).toBe(600000);
  expect(commandTimeout('npx')).toBe(300000);
  await expect(run('npm', ['run', 'build'], dir, (_cmd, _args, options, callback) => {
    expect(options.timeout).toBe(600000);
    callback({ killed: true }, '', '');
  })).rejects.toThrow('npm run build falló (timeout)');
});

it.each([0, 49, 50, 75])('bloquea solo el catalogo vacio; con menos productos publica igual (regla del user): %s', async publicados => {
  await fs.mkdir(path.join(dir, 'work', 'dist'), { recursive: true });
  await fs.mkdir(path.join(dir, 'work', 'data'), { recursive: true });
  await fs.writeFile(path.join(dir, 'work', 'data', 'catalog.json'), '[]');
  await fs.writeFile(path.join(dir, 'work', 'dist', 'estado.json'), JSON.stringify({ publicados }));
  const stateFile = path.join(dir, 'last-deploy.json');
  const original = { date: '2026-11-04', publicados: 100 };
  await fs.writeFile(stateFile, JSON.stringify(original));
  const outputFile = path.join(dir, 'ml-prices.json');
  const amazonOutputFile = path.join(dir, 'amazon-prices.json');
  for (const file of [outputFile, amazonOutputFile]) await fs.writeFile(file, JSON.stringify({ date: '2026-11-05', items: { p: { amount: 150 } } }));
  const calls: string[] = [];
  const result = await deployOnce(new Date('2026-11-05T10:00:00Z'), {
    stateFile, outputFile, amazonOutputFile, workDir: path.join(dir, 'work'),
    runImpl: async (cmd: string) => { calls.push(cmd); },
  });
  expect(result).toBe(publicados === 0 ? 'fail' : 'ok');
  expect(calls.includes('npx')).toBe(publicados > 0);
  const saved = JSON.parse(await fs.readFile(stateFile, 'utf8'));
  if (publicados === 0) expect(saved).toEqual(original);
  else expect(saved.publicados).toBe(publicados);
});

it('purga logs de mas de treinta dias sin tocar otros archivos', async () => {
  for (const name of ['deployer-2026-10-06.log', 'deployer-2026-10-07.log', 'otro.log']) await fs.writeFile(path.join(dir, name), '');
  purgeLogs(dir, new Date('2026-11-05T12:00:00Z'));
  expect((await fs.readdir(dir)).sort()).toEqual(['deployer-2026-10-07.log', 'otro.log']);
});

it('valida ambos archivos con fecha ART antes del build manual', async () => {
  const files = [path.join(dir, 'ml'), path.join(dir, 'amazon')];
  for (const file of files) await fs.writeFile(file, '{"date":"2026-11-04"}');
  const now = new Date('2026-11-05T02:00:00Z');
  expect(() => validatePriceFiles(files, now)).not.toThrow();
  await fs.writeFile(files[1], '{"date":"2026-11-03"}');
  expect(() => validatePriceFiles(files, now)).toThrow('amazon');
});
