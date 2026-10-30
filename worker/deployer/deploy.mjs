// Despliegue diario de Franquicia 400 a Cloudflare con los precios de Mercado Libre.
// Corre a las 07:30 ART. Logs sin secretos: DEPLOY_OK / DEPLOY_SKIP / DEPLOY_FAIL / DEPLOY_OFF.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';

const REPO_URL = 'https://github.com/knupson/weboffers.git';
const OUTPUT_FILE = '/app/output/ml-prices.json';
const WORK_DIR = '/work';
const STATE_FILE = '/state/last-deploy.json';
const ART_OFFSET_MS = -3 * 3600e3;   // Argentina no tiene horario de verano
const DEPLOY_AT_UTC = '10:30:00Z';    // 07:30 ART
const ONE_DAY_MS = 86400e3;
const MAX_SLEEP_MS = 60e3;

let stopRequested = false;

function log(line) {
  process.stdout.write(`${new Date().toISOString()} ${line}\n`);
}

function artDate(date) {
  return new Date(date.getTime() + ART_OFFSET_MS).toISOString().slice(0, 10);
}

function nextRunAt(now) {
  let target = Date.parse(`${artDate(now)}T${DEPLOY_AT_UTC}`);
  if (target <= now.getTime()) target += ONE_DAY_MS;
  return target;
}

function redact(text) {
  const token = process.env.CLOUDFLARE_API_TOKEN?.trim();
  return token ? text.split(token).join('***') : text;
}

function run(command, args, cwd) {
  return new Promise((resolve, reject) => {
    execFile(command, args, {
      cwd,
      maxBuffer: 20 * 1024 * 1024,
      env: { ...process.env, CI: '1', WRANGLER_SEND_METRICS: 'false' },
    }, (error, stdout, stderr) => {
      if (error) {
        const tail = redact(`${stderr}`.trim().split('\n').slice(-3).join(' | '));
        reject(new Error(`${command} ${args.join(' ')} falló (código ${error.code ?? '?'}): ${tail}`));
      } else {
        resolve(stdout);
      }
    });
  });
}

async function readState() {
  try {
    return JSON.parse(await fs.readFile(STATE_FILE, 'utf8'));
  } catch {
    return null;
  }
}

async function syncRepo() {
  const hasRepo = await fs.access(path.join(WORK_DIR, '.git')).then(() => true, () => false);
  if (hasRepo) {
    await run('git', ['-C', WORK_DIR, 'fetch', '--depth', '1', 'origin', 'main'], WORK_DIR);
    await run('git', ['-C', WORK_DIR, 'reset', '--hard', 'FETCH_HEAD'], WORK_DIR);
  } else {
    await run('git', ['clone', '--depth', '1', '--branch', 'main', REPO_URL, WORK_DIR], '/');
  }
}

async function deployOnce(now = new Date()) {
  const token = process.env.CLOUDFLARE_API_TOKEN?.trim();
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID?.trim();
  if (!token || !accountId) {
    log('DEPLOY_OFF faltan CLOUDFLARE_API_TOKEN o CLOUDFLARE_ACCOUNT_ID; no se despliega.');
    return 'off';
  }
  let raw;
  try {
    raw = await fs.readFile(OUTPUT_FILE, 'utf8');
  } catch {
    log('DEPLOY_SKIP no existe ml-prices.json todavía.');
    return 'skip';
  }
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    log('DEPLOY_SKIP ml-prices.json no es JSON válido.');
    return 'skip';
  }
  const today = artDate(now);
  if (data.date !== today) {
    log(`DEPLOY_SKIP ml-prices.json es de ${data.date}, hoy es ${today}.`);
    return 'skip';
  }
  const hash = createHash('sha256').update(raw).digest('hex');
  const last = await readState();
  if (last?.hash === hash) {
    log('DEPLOY_SKIP ml-prices.json no cambió desde el último despliegue.');
    return 'skip';
  }
  try {
    await syncRepo();
    await fs.mkdir(path.join(WORK_DIR, 'data'), { recursive: true });
    await fs.writeFile(path.join(WORK_DIR, 'data', 'ml-prices.json'), raw);
    await run('npm', ['ci'], WORK_DIR);
    await run('npm', ['run', 'build'], WORK_DIR);
    await run('npx', ['--yes', 'wrangler', 'deploy'], WORK_DIR);
    await fs.mkdir(path.dirname(STATE_FILE), { recursive: true });
    await fs.writeFile(STATE_FILE, JSON.stringify({ hash, date: today, deployedAt: now.toISOString() }));
    log(`DEPLOY_OK publicado con precios del ${today}.`);
    return 'ok';
  } catch (error) {
    log(`DEPLOY_FAIL ${redact(error.message)}`);
    return 'fail';
  }
}

async function sleepUntil(timestamp) {
  while (!stopRequested && Date.now() < timestamp) {
    await new Promise((resolve) => setTimeout(resolve, Math.min(MAX_SLEEP_MS, Math.max(0, timestamp - Date.now()))));
  }
}

async function main() {
  const stop = () => { stopRequested = true; };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  log('Deployer iniciado.');
  while (!stopRequested) {
    const next = nextRunAt(new Date());
    log(`Próximo despliegue previsto: ${new Date(next).toISOString()}.`);
    await sleepUntil(next);
    if (stopRequested) break;
    try {
      await deployOnce(new Date());
    } catch (error) {
      log(`DEPLOY_FAIL ${redact(String(error.message))}`);
    }
  }
  log('Deployer detenido.');
}

if (process.argv[1] && process.argv[1].endsWith('deploy.mjs')) {
  main();
}

export { artDate, nextRunAt, deployOnce };
