import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  artDate,
  deadlineAt,
  deployOnce,
  deployWithRetry,
  hasBothTodayPrices,
  nextRunAt,
  runStartupIfPending,
  RETRY_INTERVAL_MS,
} from './deploy.mjs';

describe('deployer', () => {
  let tmpDir: string;
  const prevToken = process.env.CLOUDFLARE_API_TOKEN;
  const prevAccount = process.env.CLOUDFLARE_ACCOUNT_ID;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'deploy-test-'));
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

  it('calcula 07:30 ART como inicio, 11:00 ART como tope y 10 min de reintento', () => {
    const now = new Date('2026-10-30T10:30:00Z'); // 07:30 ART del 2026-10-30
    expect(artDate(now)).toBe('2026-10-30');
    expect(deadlineAt(now)).toBe(Date.parse('2026-10-30T14:00:00Z')); // 11:00 ART
    expect(nextRunAt(new Date('2026-10-30T10:00:00Z'))).toBe(Date.parse('2026-10-30T10:30:00Z'));
    expect(RETRY_INTERVAL_MS).toBe(10 * 60e3);
  });

  it('antes de las 11:00 ART exige que ml-prices.json y amazon-prices.json tengan date == hoy', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });

    const now = new Date('2026-10-30T10:30:00Z'); // 07:30 ART

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

  it('a las 11:00 ART despliega igual aunque falten precios de hoy y limpia archivos inválidos del workDir', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');

    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    const staleAmazonInWork = path.join(workDir, 'data', 'amazon-prices.json');
    await fs.writeFile(staleAmazonInWork, JSON.stringify({ date: '2026-10-29', items: { viejo: { amount: 100 } } }));

    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, '{json-roto');

    // Simula que son las 10:50 ART (falta 1 intervalo de 10m para las 11:00 ART = 14:00Z)
    let currentMs = Date.parse('2026-10-30T13:50:00Z');
    const sleeps: number[] = [];

    const result = await deployWithRetry({
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
      nowFn: () => new Date(currentMs),
      sleepFn: async (ms: number) => {
        sleeps.push(ms);
        currentMs += ms;
      },
    });

    expect(sleeps).toEqual([10 * 60e3]);
    expect(result).toBe('ok');
    await expect(fs.access(staleAmazonInWork)).rejects.toThrow();

    // Si luego amazon-prices.json no existe a las 11:00 ART y cambia ml-prices.json, también borra el previo
    await fs.writeFile(staleAmazonInWork, JSON.stringify({ date: '2026-10-30', items: {} }));
    await fs.rm(amazonOutputFile, { force: true });
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 2000 } } }));

    const result2 = await deployOnce(new Date('2026-10-30T14:00:00Z'), {
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
    });

    expect(result2).toBe('ok');
    await expect(fs.access(staleAmazonInWork)).rejects.toThrow();
  });

  it('a las 11:00 ART no hace skip si el hash coincide con ayer pero la fecha del último despliegue es anterior', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });

    // Día 1 (2026-10-30): ambos archivos del día se despliegan y guardan su hash con date=2026-10-30
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-10-30', items: { a: { amount: 100 } } }));
    const day1 = await deployOnce(new Date('2026-10-30T10:30:00Z'), {
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
    });
    expect(day1).toBe('ok');

    // Día 2 (2026-10-31 a las 11:00 ART): los archivos siguen idénticos a ayer (mismo hash, distinta fecha)
    const day2At11 = await deployWithRetry({
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
      nowFn: () => new Date('2026-10-31T14:00:00Z'),
      sleepFn: async () => {},
    });
    expect(day2At11).toBe('ok');
    const savedState = JSON.parse(await fs.readFile(stateFile, 'utf8'));
    expect(savedState.date).toBe('2026-10-31');

    // Mismo día 2 con el mismo hash y misma fecha -> ahora sí hace skip
    const day2Repeat = await deployOnce(new Date('2026-10-31T14:05:00Z'), {
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
    });
    expect(day2Repeat).toBe('skip');
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
});
