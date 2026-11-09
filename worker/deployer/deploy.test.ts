import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  deployOnce as actualDeployOnce,
  deployWithRetry,
  hasBothTodayPrices,
  overlayCatalog,
  main,
  saveBreakdown,
} from './deploy.mjs';

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

describe('deployer', () => {
  let tmpDir: string;
  const prevToken = process.env.CLOUDFLARE_API_TOKEN;
  const prevAccount = process.env.CLOUDFLARE_ACCOUNT_ID;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'deploy-test-'));
    await fs.mkdir(path.join(tmpDir, 'work', 'dist'), { recursive: true });
    await fs.mkdir(path.join(tmpDir, 'work', 'data'), { recursive: true });
    await fs.writeFile(path.join(tmpDir, 'work', 'data', 'catalog.json'), '[]');
    await fs.writeFile(path.join(tmpDir, 'work', 'dist', 'estado.json'), JSON.stringify({ publicados: 100 }));
    process.env.CLOUDFLARE_API_TOKEN = 'test-token';
    process.env.CLOUDFLARE_ACCOUNT_ID = 'test-account';
  });

  afterEach(async () => {
    if (prevToken === undefined) delete process.env.CLOUDFLARE_API_TOKEN;
    else process.env.CLOUDFLARE_API_TOKEN = prevToken;
    if (prevAccount === undefined) delete process.env.CLOUDFLARE_ACCOUNT_ID;
    else process.env.CLOUDFLARE_ACCOUNT_ID = prevAccount;
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  it('superpone catálogo y fotos antes del build con prioridad del repo', async () => {
    const workDir = path.join(tmpDir, 'work');
    const outputDir = path.join(tmpDir, 'output');
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    await fs.mkdir(path.join(workDir, 'public', 'products'), { recursive: true });
    await fs.mkdir(path.join(outputDir, 'products'), { recursive: true });
    const original = { asin: 'A', slug: 'a', summary: 'del repo' };
    await fs.writeFile(path.join(workDir, 'data', 'catalog.json'), JSON.stringify([original]));
    await fs.writeFile(path.join(outputDir, 'catalog-auto.json'), JSON.stringify([
      { ...original, summary: 'automático' }, { asin: 'A', slug: 'otro' },
      { asin: 'B', slug: 'a' }, { asin: 'C', slug: 'c' }, { asin: 'C', slug: 'c' },
    ]));
    await fs.writeFile(path.join(workDir, 'public', 'products', 'a.webp'), 'original');
    await fs.writeFile(path.join(outputDir, 'products', 'a.webp'), 'automática');
    await fs.writeFile(path.join(outputDir, 'products', 'c.webp'), 'nueva');
    await fs.writeFile(path.join(outputDir, 'products', 'c.jpg'), 'telegram');
    await overlayCatalog(workDir, outputDir);
    expect(JSON.parse(await fs.readFile(path.join(workDir, 'data', 'catalog.json'), 'utf8')))
      .toEqual([original, { asin: 'C', slug: 'c' }]);
    expect(await fs.readFile(path.join(workDir, 'public', 'products', 'a.webp'), 'utf8')).toBe('original');
    expect(await fs.readFile(path.join(workDir, 'public', 'products', 'c.webp'), 'utf8')).toBe('nueva');
    expect(await fs.readFile(path.join(workDir, 'public', 'products', 'c.jpg'), 'utf8')).toBe('telegram');
    expect(JSON.parse(await fs.readFile(path.join(workDir, 'data', 'catalog-origins.json'), 'utf8'))).toEqual({ a: 'repo', c: 'auto' });
  });

  it('tolera ausencia del overlay pero rechaza JSON inválido', async () => {
    await overlayCatalog(path.join(tmpDir, 'work'), tmpDir);
    await fs.writeFile(path.join(tmpDir, 'catalog-auto.json'), '{}');
    await expect(overlayCatalog(path.join(tmpDir, 'work'), tmpDir)).rejects.toThrow('lista de productos');
  });

  it('copia fichas opcionales y elimina una copia anterior si falta el archivo', async () => {
    const work = path.join(tmpDir, 'work');
    const dest = path.join(work, 'data', 'ml-fichas.json');
    const source = path.join(tmpDir, 'ml-fichas.json');
    const sheet = JSON.stringify({ generatedAt: '2026-11-07', items: {} });
    await fs.writeFile(source, sheet);
    await overlayCatalog(work, tmpDir);
    expect(await fs.readFile(dest, 'utf8')).toBe(sheet);
    await fs.rm(source);
    await overlayCatalog(work, tmpDir);
    await expect(fs.stat(dest)).rejects.toMatchObject({ code: 'ENOENT' });
  });

  it('un overlay fallido mantiene DEPLOY_FAIL y no ejecuta el build', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-03', items: {} }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-03', items: { a: { amount: 150 } } }));
    await fs.writeFile(path.join(tmpDir, 'catalog-auto.json'), '{inválido');
    const calls: string[] = [];
    expect(await deployOnce(new Date('2026-11-03T10:00:00Z'), {
      outputFile, amazonOutputFile, workDir: path.join(tmpDir, 'work'), stateFile: path.join(tmpDir, 'state.json'),
      runImpl: async (cmd: string) => { calls.push(cmd); return 'a'.repeat(40); },
    })).toBe('fail');
    expect(calls).toEqual(['git']);
    expect(JSON.parse(await fs.readFile(path.join(tmpDir, 'last-result.json'), 'utf8')))
      .toMatchObject({ status: 'fail', at: '2026-11-03T10:00:00.000Z' });
  });

  it('el build recibe las altas y sus fotos', async () => {
    const workDir = path.join(tmpDir, 'work');
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    await fs.mkdir(path.join(tmpDir, 'products'));
    await fs.writeFile(path.join(workDir, 'data', 'catalog.json'), '[]');
    await fs.writeFile(path.join(tmpDir, 'catalog-auto.json'), '[{"asin":"A","slug":"a"}]');
    await fs.writeFile(path.join(tmpDir, 'products', 'a.webp'), 'foto');
    await fs.writeFile(path.join(tmpDir, 'products', 'a.jpg'), 'telegram');
    await fs.writeFile(path.join(tmpDir, 'offers.json'), JSON.stringify({ rates: { mep: 1234 }, items: [] }));
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-03', items: {} }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-03', items: { a: { amount: 150 } } }));
    const commands: string[] = [];
    expect(await deployOnce(new Date('2026-11-03T10:00:00Z'), {
      outputFile, amazonOutputFile, workDir, stateFile: path.join(tmpDir, 'state.json'),
      runImpl: async (command: string) => {
        commands.push(command);
        if (command === 'npm') {
          expect(JSON.parse(await fs.readFile(path.join(workDir, 'data', 'catalog.json'), 'utf8'))).toEqual([{ asin: 'A', slug: 'a' }]);
          expect(await fs.readFile(path.join(workDir, 'public', 'products', 'a.webp'), 'utf8')).toBe('foto');
          expect(await fs.readFile(path.join(workDir, 'public', 'products', 'a.jpg'), 'utf8')).toBe('telegram');
          expect(JSON.parse(await fs.readFile(path.join(workDir, 'data', 'offers.json'), 'utf8')).rates.mep).toBe(1234);
        }
        return 'a'.repeat(40);
      },
    })).toBe('ok');
    expect(commands).toEqual(['git', 'npm', 'npm', 'npx']);
    expect(JSON.parse(await fs.readFile(path.join(tmpDir, 'last-result.json'), 'utf8')))
      .toMatchObject({ status: 'ok', at: '2026-11-03T10:00:00.000Z' });
  });

  it('persiste el error del build y evita publicar cuando falta MEP', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    await fs.writeFile(path.join(workDir, 'data', 'offers.json'), '{"rates":{"mep":999}}');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-03', items: {} }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-03', items: { a: { amount: 150 } } }));
    const commands: string[] = [];
    const result = await deployOnce(new Date('2026-11-03T10:00:00Z'), {
      outputFile, amazonOutputFile, workDir, stateFile: path.join(tmpDir, 'last-deploy.json'),
      runImpl: async (cmd: string, args: string[]) => {
        commands.push(`${cmd} ${args[0]}`);
        if (cmd === 'npm' && args[0] === 'run') {
          await expect(fs.access(path.join(workDir, 'data', 'offers.json'))).rejects.toThrow();
          throw new Error('Sin cotización MEP válida');
        }
        return 'a'.repeat(40);
      },
    });
    expect(result).toBe('fail');
    expect(commands.some((command) => command.startsWith('npx'))).toBe(false);
    await expect(fs.access(path.join(tmpDir, 'last-deploy.json'))).rejects.toThrow();
    expect(JSON.parse(await fs.readFile(path.join(tmpDir, 'last-result.json'), 'utf8')))
      .toEqual({ status: 'fail', reason: 'Sin cotización MEP válida', at: '2026-11-03T10:00:00.000Z' });
  });

  it('antes de las 11:00 ART exige que ml-prices.json y amazon-prices.json tengan date == hoy', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });

    const now = new Date('2026-10-30T10:00:00Z'); // 07:00 ART

    // Sin precios del día, falla inmediatamente
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('fail');

    // ML vigente con Amazon ausente: falla
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('fail');

    // Amazon de ayer: falla
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-29', items: { a: { amount: 100 } } }));
    expect((await hasBothTodayPrices(now, { outputFile, amazonOutputFile })).ready).toBe(false);
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('fail');

    // Ambos de hoy -> despliega y guarda el hash en stateFile
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 100 } } }));
    expect((await hasBothTodayPrices(now, { outputFile, amazonOutputFile })).ready).toBe(true);
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('ok');

    // Segunda corrida con el mismo contenido -> skip por hash idéntico
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('skip');
  });

  it('a las 11:00 ART falla sin precios del día y conserva el sitio previo', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    const previous = path.join(workDir, 'data', 'amazon-prices.json');
    await fs.writeFile(previous, 'sitio anterior');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    let currentMs = Date.parse('2026-10-30T13:50:00Z');
    const commands: string[] = [];
    const result = await deployWithRetry({
      outputFile, amazonOutputFile, workDir, stateFile,
      runImpl: async (cmd: string) => { commands.push(cmd); return 'a'.repeat(40); },
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => { currentMs += ms; },
    });
    expect(result).toBe('fail');
    expect(commands).toEqual([]);
    expect(await fs.readFile(previous, 'utf8')).toBe('sitio anterior');
    for (const raw of ['{json-roto', JSON.stringify({ date: '2026-10-29', items: { a: { amount: 100 } } })]) {
      await fs.writeFile(amazonOutputFile, raw);
      expect(await deployOnce(new Date('2026-10-30T14:00:00Z'), {
        outputFile, amazonOutputFile, workDir, stateFile,
        runImpl: async (cmd: string) => { commands.push(cmd); return 'a'.repeat(40); },
      })).toBe('fail');
    }
    expect(commands).toEqual([]);
  });

  it('rechaza Amazon de hoy con items vacío incluso con requireBothToday desactivado', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: {} }));
    const now = new Date('2026-10-30T14:00:00Z');
    expect((await hasBothTodayPrices(now, { outputFile, amazonOutputFile })).ready).toBe(false);
    let commands = 0;
    expect(await deployOnce(now, { outputFile, amazonOutputFile, requireBothToday: false,
      stateFile: path.join(tmpDir, 'state.json'),
      runImpl: async () => { commands++; return 'a'.repeat(40); },
    })).toBe('fail');
    expect(commands).toBe(0);
  });

  it('conserva el informe del build y alerta si difiere de estado.json', async () => {
    const workDir = path.join(tmpDir, 'work');
    const target = path.join(tmpDir, 'desglose.log');
    const content = '2026-11-06 12:00:00 PRODUCTO kindle asin=B0CFPJYX7P origen=repo PUBLICADO\n2026-11-06 12:00:00 TOTALES total=1 publicados=1 filtrados=0\n';
    await fs.writeFile(path.join(workDir, '.desglose-build.json'), JSON.stringify({ publicados: 1, content }));
    const alerts: string[] = [];
    await saveBreakdown(workDir, target, 1, (line: string) => alerts.push(line));
    expect(await fs.readFile(target, 'utf8')).toBe(content);
    expect(alerts).toEqual([]);
    await saveBreakdown(workDir, target, 2, (line: string) => alerts.push(line));
    expect(alerts).toEqual(['DEPLOY_ALERT desglose=1 estado.json=2']);
    expect(await fs.readFile(target, 'utf8')).toContain('DEPLOY_ALERT desglose=1 estado.json=2');
  });

  it('ejecuta una sola vez por invocación, incluso si falla y sin ventana horaria', async () => {
    for (const manual of [false, true]) {
      const calls: boolean[] = [];
      const result = await main({ manual, nowFn: () => new Date('2026-11-09T06:30:00Z'),
        deployFn: async (now: Date, opts: any) => {
          expect(now.toISOString()).toBe('2026-11-09T06:30:00.000Z');
          calls.push(opts.manual);
          return 'fail';
        }});
      expect(result).toBe('fail');
      expect(calls).toEqual([manual]);
    }
  });
});