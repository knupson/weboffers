import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  artDate,
  deadlineAt,
  deployExtraWithRetry,
  deployOnce,
  deployWithRetry,
  hasBothTodayPrices,
  hasExtraSlotToday,
  nextRunAt,
  overlayCatalog,
  runStartupIfPending,
  RETRY_INTERVAL_MS,
} from './deploy.mjs';

describe('deployer', () => {
  let tmpDir: string;
  const prevToken = process.env.CLOUDFLARE_API_TOKEN;
  const prevAccount = process.env.CLOUDFLARE_ACCOUNT_ID;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'deploy-test-'));
    await fs.mkdir(path.join(tmpDir, 'work', 'dist'), { recursive: true });
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
  });

  it('tolera ausencia del overlay pero rechaza JSON inválido', async () => {
    await overlayCatalog(path.join(tmpDir, 'work'), tmpDir);
    await fs.writeFile(path.join(tmpDir, 'catalog-auto.json'), '{}');
    await expect(overlayCatalog(path.join(tmpDir, 'work'), tmpDir)).rejects.toThrow('lista de productos');
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
      runImpl: async (cmd: string) => { calls.push(cmd); return ''; },
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
        return '';
      },
    })).toBe('ok');
    expect(commands).toEqual(['git', 'npm', 'npm', 'npx']);
    expect(JSON.parse(await fs.readFile(path.join(tmpDir, 'last-result.json'), 'utf8')))
      .toMatchObject({ status: 'ok', at: '2026-11-03T10:00:00.000Z' });
  });

  it('calcula 07:00 ART como inicio, 11:00 ART como tope y 10 min de reintento', () => {
    const now = new Date('2026-10-30T10:00:00Z'); // 07:00 ART del 2026-10-30
    expect(artDate(now)).toBe('2026-10-30');
    expect(deadlineAt(now)).toBe(Date.parse('2026-10-30T14:00:00Z')); // 11:00 ART
    expect(nextRunAt(new Date('2026-10-30T09:30:00Z'))).toBe(Date.parse('2026-10-30T10:00:00Z'));
    expect(RETRY_INTERVAL_MS).toBe(10 * 60e3);
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
        return '';
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

    // Falta ml-prices.json -> skip
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('skip');

    // ml-prices.json de hoy, pero falta amazon-prices.json -> skip
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('skip');

    // amazon-prices.json de ayer -> skip
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-29', items: { a: { amount: 100 } } }));
    expect((await hasBothTodayPrices(now, { outputFile, amazonOutputFile })).ready).toBe(false);
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('skip');

    // Ambos de hoy -> despliega y guarda el hash en stateFile
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 100 } } }));
    expect((await hasBothTodayPrices(now, { outputFile, amazonOutputFile })).ready).toBe(true);
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('ok');

    // Segunda corrida con el mismo contenido -> skip por hash idéntico
    expect(await deployOnce(now, { outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '' })).toBe('skip');
  });

  it('deployWithRetry reintenta cada 10 minutos desde las 07:30 ART hasta que ambos archivos son de hoy', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-29', items: {} })); // viejo al principio

    let currentMs = Date.parse('2026-10-30T10:30:00Z'); // 07:30 ART
    const sleeps: number[] = [];
    const deployCalls: Array<{ iso: string; requireBothToday: boolean }> = [];

    const result = await deployWithRetry({
      outputFile,
      amazonOutputFile,
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => {
        sleeps.push(ms);
        currentMs += ms;
        if (sleeps.length === 2) {
          // A las 07:50 ART termina el scraper de Amazon y escribe date == hoy
          await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 99 } } }));
        }
      },
      deployFn: async (now: Date, opts: { requireBothToday: boolean }) => {
        deployCalls.push({ iso: now.toISOString(), requireBothToday: opts.requireBothToday });
        return 'ok';
      },
    });

    expect(result).toBe('ok');
    expect(sleeps).toEqual([10 * 60e3, 10 * 60e3]);
    expect(deployCalls).toEqual([{ iso: '2026-10-30T10:50:00.000Z', requireBothToday: true }]);
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
      runImpl: async (cmd: string) => { commands.push(cmd); return ''; },
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
        runImpl: async (cmd: string) => { commands.push(cmd); return ''; },
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
      runImpl: async () => { commands++; return ''; },
    })).toBe('fail');
    expect(commands).toBe(0);
  });

  it('al iniciar después de las 07:30 ART ejecuta la ventana pendiente del día si no hubo despliegue hoy', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });
    await fs.mkdir(path.dirname(stateFile), { recursive: true });

    // Antes de las 07:30 ART (06:30 ART = 09:30Z): todavía no empezó la ventana de hoy
    const beforeRes = await runStartupIfPending({
      stateFile,
      nowFn: () => new Date('2026-10-30T09:30:00Z'),
    });
    expect(beforeRes).toBe('before-window');

    // Estado previo: el último despliegue fue ayer (2026-10-29), y el contenedor arranca a las 08:30 ART (11:30Z)
    await fs.writeFile(stateFile, JSON.stringify({ hash: 'h-ayer', date: '2026-10-29', deployedAt: '2026-10-29T14:00:00Z' }));
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1500 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-29', items: {} })); // aún viejo a las 08:30 ART

    let currentMs = Date.parse('2026-10-30T11:30:00Z'); // 08:30 ART
    const sleeps: number[] = [];

    const pendingRes = await runStartupIfPending({
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => {
        sleeps.push(ms);
        currentMs += ms;
        // A las 08:40 ART llega el archivo de Amazon de hoy
        await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 120 } } }));
      },
    });

    expect(pendingRes).toBe('ok');
    expect(sleeps).toEqual([10 * 60e3]);
    const savedState = JSON.parse(await fs.readFile(stateFile, 'utf8'));
    expect(savedState.date).toBe('2026-10-30');

    // Si el contenedor se reinicia más tarde el mismo día (ej. 09:30 ART), detecta que hoy ya desplegó
    const alreadyRes = await runStartupIfPending({
      stateFile,
      nowFn: () => new Date('2026-10-30T12:30:00Z'),
    });
    expect(alreadyRes).toBe('already-deployed');
  });

  it('ante un fail transitorio reintenta cada 10 minutos hasta tener éxito, incluyendo el intento final de las 11:00 ART', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 100 } } }));

    // Arranca a las 10:40 ART (13:40Z); falla a las 10:40 y a las 10:50, y tiene éxito en el intento final de las 11:00 ART (14:00Z)
    let currentMs = Date.parse('2026-10-30T13:40:00Z');
    const sleeps: number[] = [];
    const attempts: string[] = [];

    const result = await deployWithRetry({
      outputFile,
      amazonOutputFile,
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => {
        sleeps.push(ms);
        currentMs += ms;
      },
      deployFn: async (now: Date) => {
        attempts.push(now.toISOString());
        return attempts.length < 3 ? 'fail' : 'ok';
      },
    });

    expect(result).toBe('ok');
    expect(sleeps).toEqual([10 * 60e3, 10 * 60e3]);
    expect(attempts).toEqual([
      '2026-10-30T13:40:00.000Z',
      '2026-10-30T13:50:00.000Z',
      '2026-10-30T14:00:00.000Z',
    ]);

    // Si el intento de las 11:00 ART también devuelve fail, termina y devuelve fail sin entrar en loop infinito
    let atDeadlineMs = Date.parse('2026-10-30T13:50:00Z');
    const finalSleeps: number[] = [];
    const finalResult = await deployWithRetry({
      outputFile,
      amazonOutputFile,
      nowFn: () => new Date(atDeadlineMs),
      sleepFn: async (ms: number) => {
        finalSleeps.push(ms);
        atDeadlineMs += ms;
      },
      deployFn: async () => 'fail',
    });
    expect(finalResult).toBe('fail');
    expect(finalSleeps).toEqual([10 * 60e3]);
  });

  it('en día extra (2026-11-02) hay segundo despliegue a las 13:00 ART una sola vez y nextRunAt apunta a las 16:00Z tras la mañana', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });

    // Despliegue de la mañana del día extra (07:30 ART)
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-02', slot: '2026-11-02T06', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-02', items: { a: { amount: 100 } } }));
    expect(await deployOnce(new Date('2026-11-02T10:30:00Z'), {
      outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '',
    })).toBe('ok');
    let state = JSON.parse(await fs.readFile(stateFile, 'utf8'));
    expect(state.date).toBe('2026-11-02');
    expect(state.slot).toBe('morning');

    // Tras el despliegue de la mañana, el próximo run es a las 16:00Z (13:00 ART) ese mismo día
    expect(nextRunAt(new Date('2026-11-02T12:00:00Z'), state)).toBe(Date.parse('2026-11-02T16:00:00Z'));

    // El worker termina el refresh extra y firma slot T13 con precios nuevos
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-02', slot: '2026-11-02T13', items: { a: { price: 900 } } }));
    expect((await hasExtraSlotToday(new Date('2026-11-02T16:00:00Z'), { outputFile })).ready).toBe(true);

    const commands: string[] = [];
    const extraRes = await deployExtraWithRetry({
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async (cmd: string) => { commands.push(cmd); return ''; },
      nowFn: () => new Date('2026-11-02T16:00:00Z'),
      sleepFn: async () => {},
    });
    expect(extraRes).toBe('ok');
    expect(commands.filter((c) => c === 'npx')).toHaveLength(1); // un solo wrangler deploy
    state = JSON.parse(await fs.readFile(stateFile, 'utf8'));
    expect(state.date).toBe('2026-11-02');
    expect(state.slot).toBe('extra');

    // Hecho el segundo despliegue, nextRunAt va al día siguiente a las 10:00Z
    expect(nextRunAt(new Date('2026-11-02T17:00:00Z'), state)).toBe(Date.parse('2026-11-03T10:00:00Z'));

    // Reintentar el segundo despliegue el mismo día no despliega de nuevo
    const again = await deployExtraWithRetry({
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async (cmd: string) => { commands.push(cmd); return ''; },
      nowFn: () => new Date('2026-11-02T16:30:00Z'),
      sleepFn: async () => {},
    });
    expect(again).toBe('skip');
    expect(commands.filter((c) => c === 'npx')).toHaveLength(1);
  });

  it('en día extra espera el slot T13 reintentando cada 10 min hasta las 15:00 ART', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-03', slot: '2026-11-03T06', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-03', items: { a: { amount: 100 } } }));

    let currentMs = Date.parse('2026-11-03T16:00:00Z'); // 13:00 ART
    const sleeps: number[] = [];
    const deployCalls: string[] = [];
    const result = await deployExtraWithRetry({
      outputFile,
      amazonOutputFile,
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => {
        sleeps.push(ms);
        currentMs += ms;
        if (sleeps.length === 1) {
          // A las 13:10 ART el worker firma el slot T13
          await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-03', slot: '2026-11-03T13', items: { a: { price: 950 } } }));
        }
      },
      deployFn: async (now: Date) => {
        deployCalls.push(now.toISOString());
        return 'ok';
      },
    });

    expect(result).toBe('ok');
    expect(sleeps).toEqual([10 * 60e3]);
    expect(deployCalls).toEqual(['2026-11-03T16:10:00.000Z']);
  });

  it('en día extra, si a las 15:00 ART no hay slot T13 no despliega la segunda vez', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-04', slot: '2026-11-04T06', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-04', items: {} }));

    let currentMs = Date.parse('2026-11-04T17:50:00Z'); // 14:50 ART
    const sleeps: number[] = [];
    let deploys = 0;
    const result = await deployExtraWithRetry({
      outputFile,
      amazonOutputFile,
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => {
        sleeps.push(ms);
        currentMs += ms;
      },
      deployFn: async () => { deploys += 1; return 'ok'; },
    });

    expect(result).toBe('skip');
    expect(sleeps).toEqual([10 * 60e3]); // 14:50 -> 15:00 ART (18:00Z)
    expect(deploys).toBe(0);
  });

  it('en día normal no hay segundo despliegue: nextRunAt va al otro día y deployExtraWithRetry no despliega', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });

    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', slot: '2026-10-30T06', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 100 } } }));
    expect(await deployOnce(new Date('2026-10-30T10:30:00Z'), {
      outputFile, amazonOutputFile, workDir, stateFile, runImpl: async () => '',
    })).toBe('ok');
    const state = JSON.parse(await fs.readFile(stateFile, 'utf8'));
    // Día normal: tras la mañana el próximo run es mañana a las 10:00Z
    expect(nextRunAt(new Date('2026-10-30T12:00:00Z'), state)).toBe(Date.parse('2026-10-31T10:00:00Z'));

    // Aunque ml-prices.json tuviera slot T13, en día normal no se despliega la segunda vez
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', slot: '2026-10-30T13', items: { a: { price: 900 } } }));
    let deploys = 0;
    const res = await deployExtraWithRetry({
      outputFile,
      amazonOutputFile,
      nowFn: () => new Date('2026-10-30T16:00:00Z'),
      sleepFn: async () => {},
      deployFn: async () => { deploys += 1; return 'ok'; },
    });
    expect(res).toBe('skip');
    expect(deploys).toBe(0);
  });
});
