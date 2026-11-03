// Despliegue diario de Franquicia 400 a Cloudflare con los precios de Mercado Libre y Amazon.
// Corre desde las 07:00 ART esperando que ambos archivos de precios sean del día (reintenta cada 10 min hasta las 11:00 ART).
// Logs sin secretos: DEPLOY_OK / DEPLOY_SKIP / DEPLOY_WAIT / DEPLOY_FAIL / DEPLOY_OFF.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';

const REPO_URL = 'https://github.com/knupson/weboffers.git';
const OUTPUT_FILE = '/app/output/ml-prices.json';
const AMAZON_OUTPUT_FILE = '/app/output/amazon-prices.json';
const WORK_DIR = '/work';
const STATE_FILE = '/state/last-deploy.json';
const ART_OFFSET_MS = -3 * 3600e3;   // Argentina no tiene horario de verano
const DEPLOY_AT_UTC = '10:00:00Z';    // 07:00 ART
const DEADLINE_UTC = '14:00:00Z';     // 11:00 ART
// Días de oferta especial: segundo despliegue a las 13:00 ART (16:00Z) apenas ml-prices.json
// firma el slot "<fecha>T13" (reintenta hasta 15:00 ART = 18:00Z). Amazon no se relee.
const EXTRA_DEPLOY_DATES = new Set(['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-27', '2026-11-30']);
const EXTRA_DEPLOY_AT_UTC = '16:00:00Z';  // 13:00 ART
const EXTRA_DEADLINE_UTC = '18:00:00Z';   // 15:00 ART
const EXTRA_SLOT_HOUR = 13;               // slot "<fecha>T13" que escribe el worker
const RETRY_INTERVAL_MS = 10 * 60e3;  // 10 minutos
const ONE_DAY_MS = 86400e3;
const MAX_SLEEP_MS = 60e3;

let stopRequested = false;

function log(line) {
  process.stdout.write(`${new Date().toISOString()} ${line}\n`);
}

function artDate(date) {
  return new Date(date.getTime() + ART_OFFSET_MS).toISOString().slice(0, 10);
}

function startAt(now) {
  return Date.parse(`${artDate(now)}T${DEPLOY_AT_UTC}`);
}

function isExtraDate(dateStr) {
  return EXTRA_DEPLOY_DATES.has(dateStr);
}

function extraStartAt(now) {
  return Date.parse(`${artDate(now)}T${EXTRA_DEPLOY_AT_UTC}`);
}

function extraDeadlineAt(now) {
  return Date.parse(`${artDate(now)}T${EXTRA_DEADLINE_UTC}`);
}

function extraSlotId(dateStr) {
  return `${dateStr}T${String(EXTRA_SLOT_HOUR).padStart(2, '0')}`;
}

function nextRunAt(now, lastState) {
  const today = artDate(now);
  let target = startAt(now);
  if (target <= now.getTime()) {
    if (lastState !== undefined && lastState?.date !== today) {
      return now.getTime();
    }
    if (isExtraDate(today) && (lastState?.slot ?? 'morning') !== 'extra') {
      const extra = extraStartAt(now);
      return extra > now.getTime() ? extra : now.getTime();
    }
    target += ONE_DAY_MS;
  }
  return target;
}

function deadlineAt(now) {
  return Date.parse(`${artDate(now)}T${DEADLINE_UTC}`);
}

function redact(text) {
  const token = process.env.CLOUDFLARE_API_TOKEN?.trim();
  return token ? text.split(token).join('***') : text;
}

function run(command, args, cwd) {
  const childEnv = { ...process.env, CI: '1', WRANGLER_SEND_METRICS: 'false' };
  return new Promise((resolve, reject) => {
    execFile(command, args, {
      cwd,
      maxBuffer: 20 * 1024 * 1024,
      env: childEnv,
    }, (error, stdout, stderr) => {
      const combined = `${stdout ?? ''}\n${stderr ?? ''}`;
      for (const line of combined.split('\n')) {
        if (line.includes('MENOS_DE_100')) {
          log(`DEPLOY_ALERT ${line.trim()}`);
        }
      }
      if (error) {
        const lines = combined.trim().split('\n').map((l) => l.trim()).filter(Boolean);
        const tail = redact(lines.slice(-3).join(' | '));
        reject(new Error(`${command} ${args.join(' ')} falló (código ${error.code ?? '?'}): ${tail}`));
      } else {
        resolve(stdout);
      }
    });
  });
}

async function readState(stateFile = STATE_FILE) {
  try {
    return JSON.parse(await fs.readFile(stateFile, 'utf8'));
  } catch {
    return null;
  }
}

async function readJsonWithDate(filePath) {
  try {
    const raw = await fs.readFile(filePath, 'utf8');
    const data = JSON.parse(raw);
    return { ok: true, raw, data };
  } catch (err) {
    return { ok: false, missing: err?.code === 'ENOENT' };
  }
}

async function hasBothTodayPrices(now = new Date(), opts = {}) {
  const outputFile = opts.outputFile ?? OUTPUT_FILE;
  const amazonOutputFile = opts.amazonOutputFile ?? AMAZON_OUTPUT_FILE;
  const today = artDate(now);
  const ml = await readJsonWithDate(outputFile);
  if (!ml.ok || ml.data?.date !== today) {
    return {
      ready: false,
      reason: !ml.ok
        ? 'ml-prices.json ausente o inválido'
        : `ml-prices.json es de ${ml.data?.date} (hoy ${today})`,
    };
  }
  const amz = await readJsonWithDate(amazonOutputFile);
  if (!amz.ok || amz.data?.date !== today) {
    return {
      ready: false,
      reason: !amz.ok
        ? 'amazon-prices.json ausente o inválido'
        : `amazon-prices.json es de ${amz.data?.date} (hoy ${today})`,
    };
  }
  if (!amz.data.items || Array.isArray(amz.data.items) || typeof amz.data.items !== 'object' || Object.keys(amz.data.items).length === 0) {
    return { ready: false, reason: 'amazon-prices.json tiene items vacío o inválido' };
  }
  return { ready: true, mlRaw: ml.raw, amazonRaw: amz.raw };
}

async function hasExtraSlotToday(now = new Date(), opts = {}) {
  const outputFile = opts.outputFile ?? OUTPUT_FILE;
  const today = artDate(now);
  const slot = extraSlotId(today);
  const ml = await readJsonWithDate(outputFile);
  if (!ml.ok) {
    return { ready: false, reason: 'ml-prices.json ausente o inválido' };
  }
  if (ml.data?.date !== today) {
    return { ready: false, reason: `ml-prices.json es de ${ml.data?.date} (hoy ${today})` };
  }
  if (ml.data?.slot !== slot) {
    return { ready: false, reason: `ml-prices.json no tiene slot ${slot} todavía` };
  }
  return { ready: true, mlRaw: ml.raw };
}

async function syncRepo(workDir = WORK_DIR, runImpl = run) {
  const hasRepo = await fs.access(path.join(workDir, '.git')).then(() => true, () => false);
  if (hasRepo) {
    await runImpl('git', ['-C', workDir, 'fetch', '--depth', '1', 'origin', 'main'], workDir);
    await runImpl('git', ['-C', workDir, 'reset', '--hard', 'FETCH_HEAD'], workDir);
  } else {
    await runImpl('git', ['clone', '--depth', '1', '--branch', 'main', REPO_URL, workDir], '/');
  }
}

async function overlayCatalog(workDir, outputDir) {
  // Estado de la búsqueda semanal: lo publica /estado.json para el aviso de fallas de los lunes.
  await fs.copyFile(path.join(outputDir, 'catalog-auto-state.json'), path.join(workDir, 'data', 'catalog-auto-state.json')).catch((error) => {
    if (error.code !== 'ENOENT') throw error;
  });
  let automatic;
  try {
    automatic = JSON.parse(await fs.readFile(path.join(outputDir, 'catalog-auto.json'), 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return;
    throw error;
  }
  if (!Array.isArray(automatic) || automatic.some((p) => !p || typeof p !== 'object' || Array.isArray(p))) {
    throw new Error('catalog-auto.json debe ser una lista de productos');
  }
  const catalogPath = path.join(workDir, 'data', 'catalog.json');
  const repo = JSON.parse(await fs.readFile(catalogPath, 'utf8'));
  const asins = new Set(repo.map((p) => p.asin).filter(Boolean));
  const slugs = new Set(repo.map((p) => p.slug).filter(Boolean));
  for (const entry of automatic) {
    if (asins.has(entry.asin) || slugs.has(entry.slug)) continue;
    repo.push(entry);
    if (entry.asin) asins.add(entry.asin);
    if (entry.slug) slugs.add(entry.slug);
  }
  const products = path.join(outputDir, 'products');
  const dest = path.join(workDir, 'public', 'products');
  await fs.mkdir(dest, { recursive: true });
  const files = await fs.readdir(products).catch((error) => {
    if (error.code === 'ENOENT') return [];
    throw error;
  });
  for (const file of files.filter((name) => /\.(webp|jpg)$/.test(name))) {
    await fs.copyFile(path.join(products, file), path.join(dest, file), fs.constants.COPYFILE_EXCL).catch((error) => {
      if (error.code !== 'EEXIST') throw error;
    });
  }
  await fs.writeFile(catalogPath, JSON.stringify(repo, null, 2) + '\n');
}

async function saveResult(status, reason, now, opts = {}) {
  const resultFile = opts.resultFile ?? path.join(path.dirname(opts.stateFile ?? STATE_FILE), 'last-result.json');
  await fs.mkdir(path.dirname(resultFile), { recursive: true });
  await fs.writeFile(resultFile, JSON.stringify({ status, reason: redact(reason), at: now.toISOString() }) + '\n');
}

async function deployOnce(now = new Date(), opts = {}) {
  const outputFile = opts.outputFile ?? OUTPUT_FILE;
  const amazonOutputFile = opts.amazonOutputFile ?? AMAZON_OUTPUT_FILE;
  const workDir = opts.workDir ?? WORK_DIR;
  const stateFile = opts.stateFile ?? STATE_FILE;
  const runImpl = opts.runImpl ?? run;
  const slot = opts.slot ?? 'morning';

  const token = process.env.CLOUDFLARE_API_TOKEN?.trim();
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID?.trim();
  if (!token || !accountId) {
    log('DEPLOY_OFF faltan CLOUDFLARE_API_TOKEN o CLOUDFLARE_ACCOUNT_ID; no se despliega.');
    return 'off';
  }

  const today = artDate(now);
  let raw = null;
  let amazonRaw = null;

  const check = await hasBothTodayPrices(now, opts);
  if (!check.ready) {
    const expired = now.getTime() >= deadlineAt(now);
    log(`${expired ? 'DEPLOY_FAIL' : 'DEPLOY_SKIP'} ${check.reason}; no se despliega.`);
    if (expired) await saveResult('fail', check.reason, now, opts);
    return expired ? 'fail' : 'skip';
  }
  raw = check.mlRaw;
  amazonRaw = check.amazonRaw;
  if (opts.requireExtraSlot) {
    const extra = await hasExtraSlotToday(now, opts);
    if (!extra.ready) {
      log(`DEPLOY_SKIP ${extra.reason}; no se despliega.`);
      return 'skip';
    }
  }

  const hashInput = [raw ?? '', amazonRaw ?? ''].join('\n');
  const hash = createHash('sha256').update(hashInput).digest('hex');
  const last = await readState(stateFile);
  // Sólo omitir cuando coincidan el hash, la fecha ART y el slot del último despliegue.
  if (last?.hash === hash && last?.date === today && (last?.slot ?? 'morning') === slot) {
    log('DEPLOY_SKIP los precios y la fecha no cambiaron desde el último despliegue.');
    return 'skip';
  }
  try {
    await syncRepo(workDir, runImpl);
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    await overlayCatalog(workDir, opts.outputDir ?? path.dirname(outputFile));
    const offersDest = path.join(workDir, 'data', 'offers.json');
    await fs.copyFile(path.join(opts.outputDir ?? path.dirname(outputFile), 'offers.json'), offersDest).catch(async (error) => {
      if (error.code !== 'ENOENT') throw error;
      await fs.rm(offersDest, { force: true });
    });
    const mlDest = path.join(workDir, 'data', 'ml-prices.json');
    if (raw) {
      await fs.writeFile(mlDest, raw);
    } else {
      await fs.rm(mlDest, { force: true });
    }
    const amazonDest = path.join(workDir, 'data', 'amazon-prices.json');
    if (amazonRaw) {
      await fs.writeFile(amazonDest, amazonRaw);
    } else {
      await fs.rm(amazonDest, { force: true });
    }
    await runImpl('npm', ['ci'], workDir);
    await runImpl('npm', ['run', 'build'], workDir);
    await runImpl('npx', ['--yes', 'wrangler', 'deploy'], workDir);
    await fs.mkdir(path.dirname(stateFile), { recursive: true });
    await fs.writeFile(stateFile, JSON.stringify({ hash, date: today, slot, deployedAt: now.toISOString() }));
    await saveResult('ok', `Publicado con precios del ${today}`, now, opts);
    log(`DEPLOY_OK publicado con precios del ${today}${slot === 'extra' ? ' (segundo despliegue de las 13:00 ART)' : ''}.`);
    return 'ok';
  } catch (error) {
    log(`DEPLOY_FAIL ${redact(error.message)}`);
    await saveResult('fail', error.message, now, opts);
    return 'fail';
  }
}

async function deployWithRetry(opts = {}) {
  const nowFn = opts.nowFn ?? (() => new Date());
  const sleepFn = opts.sleepFn ?? sleepMs;
  const deployFn = opts.deployFn ?? deployOnce;
  const retryIntervalMs = opts.retryIntervalMs ?? RETRY_INTERVAL_MS;

  while (!stopRequested) {
    const now = nowFn();
    const deadline = deadlineAt(now);
    const check = await hasBothTodayPrices(now, opts);
    if (check.ready) {
      const res = await deployFn(now, { ...opts, requireBothToday: true });
      if (res !== 'fail' || now.getTime() >= deadline) {
        return res;
      }
      const waitMs = Math.min(retryIntervalMs, Math.max(0, deadline - now.getTime()));
      log(`DEPLOY_WAIT el despliegue devolvió fail; próximo reintento en ${Math.round(waitMs / 60e3)} min.`);
      await sleepFn(waitMs);
      continue;
    }
    if (now.getTime() >= deadline) {
      log(`DEPLOY_FAIL son las 11:00 ART o más: ${check.reason}; no se despliega.`);
      await saveResult('fail', check.reason, now, opts);
      return 'fail';
    }
    const waitMs = Math.min(retryIntervalMs, Math.max(0, deadline - now.getTime()));
    log(`DEPLOY_WAIT esperando precios del día (${check.reason}); próximo chequeo en ${Math.round(waitMs / 60e3)} min.`);
    await sleepFn(waitMs);
  }
  return 'stopped';
}

async function deployExtraWithRetry(opts = {}) {
  const nowFn = opts.nowFn ?? (() => new Date());
  const sleepFn = opts.sleepFn ?? sleepMs;
  const deployFn = opts.deployFn ?? deployOnce;
  const retryIntervalMs = opts.retryIntervalMs ?? RETRY_INTERVAL_MS;

  while (!stopRequested) {
    const now = nowFn();
    const today = artDate(now);
    if (!isExtraDate(today)) {
      log(`DEPLOY_INFO ${today} no es día de oferta especial; no hay segundo despliegue.`);
      return 'skip';
    }
    const deadline = extraDeadlineAt(now);
    const check = await hasExtraSlotToday(now, opts);
    if (check.ready) {
      const res = await deployFn(now, { ...opts, requireBothToday: false, requireExtraSlot: true, slot: 'extra' });
      if (res !== 'fail' || now.getTime() >= deadline) {
        return res;
      }
      const waitMs = Math.min(retryIntervalMs, Math.max(0, deadline - now.getTime()));
      log(`DEPLOY_WAIT el segundo despliegue devolvió fail; próximo reintento en ${Math.round(waitMs / 60e3)} min.`);
      await sleepFn(waitMs);
      continue;
    }
    if (now.getTime() >= deadline) {
      log(`DEPLOY_INFO son las 15:00 ART o más sin slot ${extraSlotId(today)} (${check.reason}); no se despliega la segunda vez.`);
      return 'skip';
    }
    const waitMs = Math.min(retryIntervalMs, Math.max(0, deadline - now.getTime()));
    log(`DEPLOY_WAIT esperando slot ${extraSlotId(today)} en ml-prices.json (${check.reason}); próximo chequeo en ${Math.round(waitMs / 60e3)} min.`);
    await sleepFn(waitMs);
  }
  return 'stopped';
}

async function sleepMs(ms) {
  const target = Date.now() + ms;
  await sleepUntil(target);
}

async function sleepUntil(timestamp) {
  while (!stopRequested && Date.now() < timestamp) {
    await new Promise((resolve) => setTimeout(resolve, Math.min(MAX_SLEEP_MS, Math.max(0, timestamp - Date.now()))));
  }
}

async function runStartupIfPending(opts = {}) {
  const nowFn = opts.nowFn ?? (() => new Date());
  const stateFile = opts.stateFile ?? STATE_FILE;
  const retryFn = opts.retryFn ?? deployWithRetry;
  const now = nowFn();
  if (now.getTime() < startAt(now)) {
    return 'before-window';
  }
  const last = await readState(stateFile);
  const today = artDate(now);
  if (last?.date === today) {
    log(`DEPLOY_SKIP ya existe despliegue del día (${today}) al iniciar.`);
    return 'already-deployed';
  }
  log(`DEPLOY_INFO ventana pendiente del ${today} al iniciar; ejecutando despliegue.`);
  return await retryFn(opts);
}

async function main() {
  const stop = () => { stopRequested = true; };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  log('Deployer iniciado.');
  try {
    await runStartupIfPending();
  } catch (error) {
    log(`DEPLOY_FAIL ${redact(String(error.message))}`);
  }
  while (!stopRequested) {
    const state = await readState();
    const next = nextRunAt(new Date(), state);
    log(`Próximo despliegue previsto: ${new Date(next).toISOString()}.`);
    await sleepUntil(next);
    if (stopRequested) break;
    const wake = new Date();
    const today = artDate(wake);
    const extraDue = isExtraDate(today)
      && wake.getTime() >= extraStartAt(wake)
      && state?.date === today
      && (state?.slot ?? 'morning') !== 'extra';
    try {
      if (extraDue) {
        await deployExtraWithRetry();
      } else {
        await deployWithRetry();
      }
    } catch (error) {
      log(`DEPLOY_FAIL ${redact(String(error.message))}`);
    }
  }
  log('Deployer detenido.');
}

if (process.argv[1] && process.argv[1].endsWith('deploy.mjs')) {
  main();
}

export {
  overlayCatalog,
  artDate,
  startAt,
  isExtraDate,
  extraStartAt,
  extraDeadlineAt,
  extraSlotId,
  nextRunAt,
  deadlineAt,
  hasBothTodayPrices,
  hasExtraSlotToday,
  deployOnce,
  deployWithRetry,
  deployExtraWithRetry,
  runStartupIfPending,
  RETRY_INTERVAL_MS,
  DEADLINE_UTC,
  EXTRA_DEPLOY_AT_UTC,
  EXTRA_DEADLINE_UTC,
};
