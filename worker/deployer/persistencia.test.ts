// Auditoría 09/11 (F-15, F-18, F-28): archivos de precios parciales, un solo despliegue a la vez y alarma en last-result.json.
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { acquireLock, deployOnce, hasBothTodayPrices } from './deploy.mjs';

describe('persistencia del deploy', () => {
  let tmpDir: string;
  const now = new Date('2026-11-03T10:00:00Z');
  const prevToken = process.env.CLOUDFLARE_API_TOKEN;
  const prevAccount = process.env.CLOUDFLARE_ACCOUNT_ID;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'deploy-persist-'));
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

  async function prices(mlExtra: object = {}, amazonExtra: object = {}) {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-11-03', items: { a: { price: 1 } }, ...mlExtra }));
    await fs.writeFile(amazonOutputFile, JSON.stringify({ date: '2026-11-03', items: { a: { amount: 150 } }, ...amazonExtra }));
    return { outputFile, amazonOutputFile };
  }

  it('F-15: un archivo de hoy marcado completo:false (alta sin verificación) no cuenta como corrida entera', async () => {
    expect((await hasBothTodayPrices(now, await prices())).ready).toBe(true);
    const ml = await hasBothTodayPrices(now, await prices({ completo: false }));
    expect(ml.ready).toBe(false);
    expect(ml.reason).toContain('ml-prices.json es parcial');
    const amazon = await hasBothTodayPrices(now, await prices({}, { completo: false }));
    expect(amazon.ready).toBe(false);
    expect(amazon.reason).toContain('amazon-prices.json es parcial');
    // completo:true o ausente es una corrida normal.
    expect((await hasBothTodayPrices(now, await prices({ completo: true }, { completo: true }))).ready).toBe(true);
  });

  it('F-15: el deploy se niega a publicar con precios parciales, sin tocar el repo ni el build', async () => {
    const opts: any = await prices({}, { completo: false });
    const commands: string[] = [];
    const result = await deployOnce(now, {
      ...opts, workDir: path.join(tmpDir, 'work'), stateFile: path.join(tmpDir, 'state.json'),
      logDir: path.join(tmpDir, 'logs'), runImpl: async (cmd: string) => { commands.push(cmd); return 'a'.repeat(40); },
    });
    expect(result).toBe('fail');
    expect(commands).toEqual([]);
    expect(JSON.parse(await fs.readFile(path.join(tmpDir, 'last-result.json'), 'utf8')).reason).toContain('parcial');
  });

  it('F-18: el segundo despliegue espera al primero (candado) y no corre dos builds sobre el mismo /work', async () => {
    const opts: any = await prices();
    const workDir = path.join(tmpDir, 'work');
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    await fs.mkdir(path.join(workDir, 'dist'), { recursive: true });
    await fs.writeFile(path.join(workDir, 'data', 'catalog.json'), '[]');
    await fs.writeFile(path.join(workDir, 'dist', 'estado.json'), JSON.stringify({ publicados: 100 }));
    let activos = 0;
    let maximo = 0;
    const runImpl = async (cmd: string, args: string[], cwd: string, _exec: unknown, env: any) => {
      if (cmd === 'git' && args[0] === 'rev-parse') return 'a'.repeat(40);
      if (cmd === 'npx') {
        activos += 1;
        maximo = Math.max(maximo, activos);
        await new Promise((resolve) => setTimeout(resolve, 150));
        activos -= 1;
      }
      if (cmd === 'npm' && args[0] === 'run') {
        await fs.writeFile(env.CADENA_DESGLOSE_PATH, JSON.stringify({ publicados: 100, content: '2026-11-03 04:00:00 TOTALES\n' }));
      }
      return 'a'.repeat(40);
    };
    const common = { ...opts, workDir, logDir: path.join(tmpDir, 'logs'), runImpl, lockPollMs: 20, manual: true };
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    const [a, b] = await Promise.all([
      deployOnce(now, { ...common, stateFile }),
      deployOnce(now, { ...common, stateFile }),
    ]);
    expect([a, b]).toEqual(['ok', 'ok']);
    expect(maximo).toBe(1);
    await expect(fs.access(path.join(tmpDir, 'state', 'deploy.lock'))).rejects.toThrow(); // se libera al terminar
  });

  async function crearCandado(dir: string, owner: object | null, edadMs = 0) {
    await fs.mkdir(dir);
    if (owner) await fs.writeFile(path.join(dir, 'owner.json'), JSON.stringify(owner));
    if (edadMs) {
      const antes = new Date(Date.now() - edadMs);
      await fs.utimes(dir, antes, antes);
    }
  }

  it('F-18: candado de un pid muerto se toma; de uno vivo se espera y, si no termina, el despliegue falla', async () => {
    const lock = path.join(tmpDir, 'deploy.lock');
    await crearCandado(lock, { pid: 999999, at: new Date().toISOString() });
    const robado = await acquireLock(lock, { pidAlive: () => false, lockPollMs: 10 });
    expect(robado.ok).toBe(true);
    await robado.release();
    await expect(fs.access(lock)).rejects.toThrow();

    await crearCandado(lock, { pid: process.pid, at: new Date().toISOString() });
    const ocupado = await acquireLock(lock, { pidAlive: () => true, lockWaitMs: 100, lockPollMs: 10 });
    expect(ocupado.ok).toBe(false);
    expect(ocupado.reason).toContain('otro despliegue en curso');

    setTimeout(() => { fs.rm(lock, { recursive: true, force: true }); }, 60);
    const espera = await acquireLock(lock, { pidAlive: () => true, lockWaitMs: 2000, lockPollMs: 10 });
    expect(espera.ok).toBe(true);
    await espera.release();
  });

  it('revisión 2: un dueño vivo nunca se desaloja por antigüedad', async () => {
    const lock = path.join(tmpDir, 'deploy.lock');
    await crearCandado(lock, { pid: process.pid, at: new Date(Date.now() - 5 * 3600e3).toISOString() }, 5 * 3600e3);
    const r = await acquireLock(lock, { pidAlive: () => true, lockWaitMs: 150, lockPollMs: 10 });
    expect(r.ok).toBe(false);
    expect(JSON.parse(await fs.readFile(path.join(lock, 'owner.json'), 'utf8')).pid).toBe(process.pid); // sigue siendo suyo
  });

  it('revisión 2: dos tomadores de un candado abandonado no ganan los dos', async () => {
    const lock = path.join(tmpDir, 'deploy.lock');
    await crearCandado(lock, { pid: 999999, at: new Date().toISOString() });
    // Ambos ven al dueño muerto; el que gana mantiene el candado (no lo libera) y el otro tiene que esperar.
    const resultados = await Promise.all([
      acquireLock(lock, { pidAlive: (pid: number) => pid === process.pid, lockWaitMs: 400, lockPollMs: 10 }),
      acquireLock(lock, { pidAlive: (pid: number) => pid === process.pid, lockWaitMs: 400, lockPollMs: 10 }),
    ]);
    expect(resultados.filter((r) => r.ok)).toHaveLength(1);
    expect(resultados.filter((r) => !r.ok)).toHaveLength(1);
    const huerfanos = (await fs.readdir(tmpDir)).filter((n) => n.includes('.takeover') || n.includes('.stale-'));
    expect(huerfanos).toEqual([]);
  });

  it('revisión 3: un KILL entre mkdir y escribir el pid no bloquea para siempre', async () => {
    const lock = path.join(tmpDir, 'deploy.lock');
    await crearCandado(lock, null); // carpeta sin owner.json, recién creada: puede estar escribiéndose, se espera
    const reciente = await acquireLock(lock, { pidAlive: () => true, lockWaitMs: 100, lockPollMs: 10 });
    expect(reciente.ok).toBe(false);
    await fs.rm(lock, { recursive: true, force: true });
    await crearCandado(lock, null, 3 * 60e3); // sin pid y de más de 2 minutos: murió en el medio
    const robado = await acquireLock(lock, { pidAlive: () => true, lockWaitMs: 100, lockPollMs: 10 });
    expect(robado.ok).toBe(true);
    await robado.release();
    await fs.mkdir(lock);
    await fs.writeFile(path.join(lock, 'owner.json'), '{"pid"'); // pid truncado
    const antes = new Date(Date.now() - 3 * 60e3);
    await fs.utimes(lock, antes, antes);
    expect((await acquireLock(lock, { pidAlive: () => true, lockWaitMs: 100, lockPollMs: 10 })).ok).toBe(true);
  });

  it('revisión 2: un mutex de toma huérfano no traba el candado', async () => {
    const lock = path.join(tmpDir, 'deploy.lock');
    await crearCandado(lock, { pid: 999999, at: new Date().toISOString() });
    await crearCandado(`${lock}.takeover`, null, 3 * 60e3); // un tomador murió dentro de su sección crítica
    const r = await acquireLock(lock, { pidAlive: () => false, lockWaitMs: 2000, lockPollMs: 10 });
    expect(r.ok).toBe(true);
  });

  it('F-28: la caída brusca de publicados queda en last-result.json además del log', async () => {
    const opts: any = await prices();
    const workDir = path.join(tmpDir, 'work');
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    await fs.mkdir(path.join(workDir, 'dist'), { recursive: true });
    await fs.writeFile(path.join(workDir, 'data', 'catalog.json'), '[]');
    await fs.writeFile(path.join(workDir, 'dist', 'estado.json'), JSON.stringify({ publicados: 10 }));
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');
    await fs.mkdir(path.dirname(stateFile), { recursive: true });
    await fs.writeFile(stateFile, JSON.stringify({ hash: 'otro', date: '2026-11-02', publicados: 100, deployedAt: '2026-11-02T10:00:00Z' }));
    const result = await deployOnce(now, {
      ...opts, workDir, stateFile, logDir: path.join(tmpDir, 'logs'), manual: true,
      runImpl: async (cmd: string, args: string[], _cwd: string, _exec: unknown, env: any) => {
        if (cmd === 'npm' && args[0] === 'run') {
          await fs.writeFile(env.CADENA_DESGLOSE_PATH, JSON.stringify({ publicados: 10, content: 'x\n' }));
        }
        return 'a'.repeat(40);
      },
    });
    expect(result).toBe('ok');
    const saved = JSON.parse(await fs.readFile(path.join(path.dirname(stateFile), 'last-result.json'), 'utf8'));
    expect(saved.status).toBe('ok');
    expect(saved.alerta).toContain('caída brusca: 10 comparables contra 100');
  });
});
