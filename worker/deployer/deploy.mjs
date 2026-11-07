// Despliegue diario de Franquicia 400 a Cloudflare con los precios de Mercado Libre y Amazon.
// Espera precios del día de 07:00 a 11:00 ART; luego chequea recuperaciones cada 10 min hasta las 20:00 ART.
// Logs sin secretos: DEPLOY_OK / DEPLOY_SKIP / DEPLOY_WAIT / DEPLOY_FAIL / DEPLOY_OFF.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, mkdirSync, readdirSync, unlinkSync, promises as fs } from 'node:fs';
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
// Redespliegue por precios recuperados: sin tope diario (05/11, el tope de 2 dejó correcciones sin publicar),
// pero con al menos 30 min entre despliegues y sólo si cambiaron los precios.
const MIN_REDEPLOY_GAP_MS = 30 * 60e3;
const ONE_DAY_MS = 86400e3;
const MAX_SLEEP_MS = 60e3;

let stopRequested = false;

// `docker logs` se pierde al recrear el contenedor; /state es un volumen con nombre y sobrevive (05/11).
const LOG_DIR = process.env.DEPLOYER_LOG_DIR ?? '/state/logs';

function log(line) {
  const now = new Date();
  const text = String(line).split(/\r?\n/).map((part) => `${now.toISOString()} ${part}\n`).join('');
  process.stdout.write(text);
  try {
    mkdirSync(LOG_DIR, { recursive: true });
    purgeLogs(LOG_DIR, now);
    appendFileSync(path.join(LOG_DIR, `deployer-${artDate(now)}.log`), text);
  } catch {
    // El log en disco nunca frena un despliegue.
  }
}

function purgeLogs(dir, now = new Date()) {
  const cutoff = artDate(new Date(now.getTime() - 30 * ONE_DAY_MS));
  for (const file of readdirSync(dir)) {
    const match = /^deployer-(\d{4}-\d{2}-\d{2})\.log$/.exec(file);
    if (match && match[1] <= cutoff) unlinkSync(path.join(dir, file));
  }
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

function redeployCount(state) {
  // Compatibilidad con despliegues previos al contador persistido.
  return state?.redeploys ?? (state?.slot === 'extra' ? 1 : 0);
}

function nextRunAt(now, lastState) {
  const today = artDate(now);
  if (lastState?.date === today && now.getTime() < recoveryDeadlineAt(now)) {
    const gapEnd = Date.parse(lastState.deployedAt ?? '') + MIN_REDEPLOY_GAP_MS;
    const next = Math.max(now.getTime() + RETRY_INTERVAL_MS, Number.isFinite(gapEnd) ? gapEnd : 0);
    return Math.min(next, recoveryDeadlineAt(now));
  }
  let target = startAt(now);
  if (target <= now.getTime()) {
    if (lastState !== undefined && lastState?.date !== today && now.getTime() < deadlineAt(now)) {
      return now.getTime();
    }
    target += ONE_DAY_MS;
  }
  return target;
}

function recoveryDeadlineAt(now) {
  return Date.parse(`${artDate(now)}T23:00:00Z`); // 20:00 ART
}

function deadlineAt(now) {
  return Date.parse(`${artDate(now)}T${DEADLINE_UTC}`);
}

function redact(text) {
  const token = process.env.CLOUDFLARE_API_TOKEN?.trim();
  return token ? text.split(token).join('***') : text;
}

function commandTimeout(command) {
  return command === 'git' ? 120e3 : command === 'npm' ? 600e3 : 300e3;
}

function run(command, args, cwd, execImpl = execFile, extraEnv = {}) {
  const childEnv = { ...process.env, ...extraEnv, CI: '1', WRANGLER_SEND_METRICS: 'false' };
  return new Promise((resolve, reject) => {
    execImpl(command, args, {
      timeout: commandTimeout(command),
      killSignal: 'SIGKILL',
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
        reject(new Error(`${command} ${args.join(' ')} falló (${error.killed ? 'timeout' : `código ${error.code ?? '?'}`}): ${tail}`));
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
  const sheetDest = path.join(workDir, 'data', 'ml-fichas.json');
  await fs.copyFile(path.join(outputDir, 'ml-fichas.json'), sheetDest).catch(async (error) => {
    if (error.code !== 'ENOENT') throw error;
    await fs.rm(sheetDest, { force: true });
  });
  const catalogPath = path.join(workDir, 'data', 'catalog.json');
  const repo = JSON.parse(await fs.readFile(catalogPath, 'utf8'));
  const origins = Object.fromEntries(repo.map((p) => [p.slug, 'repo']));
  const saveOrigins = () => fs.writeFile(path.join(workDir, 'data', 'catalog-origins.json'), JSON.stringify(origins));
  await saveOrigins();
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
  const asins = new Set(repo.map((p) => p.asin).filter(Boolean));
  const slugs = new Set(repo.map((p) => p.slug).filter(Boolean));
  for (const entry of automatic) {
    if (asins.has(entry.asin) || slugs.has(entry.slug)) continue;
    repo.push(entry);
    origins[entry.slug] = 'auto';
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
  await saveOrigins();
}

/** Conserva el informe privado generado por el mismo endpoint que cuenta publicados. */
async function saveBreakdown(workDir, target, publicados, logger = log) {
  const report = JSON.parse(await fs.readFile(path.join(workDir, '.desglose-build.json'), 'utf8'));
  await fs.writeFile(target, report.content);
  if (report.publicados !== publicados) {
    const alert = `DEPLOY_ALERT desglose=${report.publicados} estado.json=${publicados}`;
    logger(alert);
    const stamp = new Date(Date.now() + ART_OFFSET_MS).toISOString().slice(0, 19).replace('T', ' ');
    await fs.appendFile(target, `${stamp} ${alert}\n`);
  }
  return report;
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
  const clock = opts.clockFn ?? (() => performance.now());
  const started = clock();
  const elapsed = () => ((clock() - started) / 1000).toFixed(1);
  const reportPath = path.join(workDir, '.desglose-build.json');
  const logDir = opts.logDir ?? LOG_DIR;
  const stamp = new Date(now.getTime() + ART_OFFSET_MS).toISOString();
  const breakdownPath = path.join(logDir, `desglose-${stamp.slice(0, 10)}-${stamp.slice(11, 16).replace(':', '')}.log`);
  let breakdownReady = false;
  let phase = null;
  let phaseStarted = started;
  const endPhase = () => {
    if (phase) log(`DEPLOY_FASE ${phase} ok ${((clock() - phaseStarted) / 1000).toFixed(1)}s`);
    phase = null;
  };
  const beginPhase = (name) => {
    endPhase();
    phase = name;
    phaseStarted = clock();
    log(`DEPLOY_FASE ${phase} inicio`);
  };

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
    log(`${expired ? 'DEPLOY_FAIL' : 'DEPLOY_SKIP'} ${check.reason}; no se despliega. ${elapsed()}s`);
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
  const recovery = last?.date === today;
  const gapEnd = Date.parse(last?.deployedAt ?? '') + MIN_REDEPLOY_GAP_MS;
  const skipReason = recovery && (last.hash === hash ? 'los precios no cambiaron desde el último despliegue'
    : Number.isFinite(gapEnd) && now.getTime() < gapEnd ? 'pasaron menos de 30 min desde el último despliegue'
    : now.getTime() >= recoveryDeadlineAt(now) ? 'cerró la ventana de recuperaciones de las 20:00 ART' : null);
  if (skipReason && !opts.manual) {
    log(`DEPLOY_SKIP ${skipReason}.`);
    return 'skip';
  }
  try {
    await fs.mkdir(logDir, { recursive: true });
    await fs.rm(reportPath, { force: true });
    await fs.writeFile(breakdownPath, `${stamp.slice(0, 19).replace('T', ' ')} DESGLOSE_PENDIENTE build todavía sin terminar\n`);
    beginPhase('repo_sync');
    await syncRepo(workDir, runImpl);
    beginPhase('overlay');
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
    const sha = (await runImpl('git', ['rev-parse', 'HEAD'], workDir)).trim();
    if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error('SHA de main inválido');
    const catalogHash = createHash('sha256').update(await fs.readFile(path.join(workDir, 'data', 'catalog.json'))).digest('hex');
    const version = { sha, catalogHash };
    beginPhase('dependencias');
    await runImpl('npm', ['ci'], workDir);
    beginPhase('build');
    await fs.rm(reportPath, { force: true });
    // La variable llega solamente al build; no contamina otros despliegues ni procesos.
    if (opts.runImpl) await runImpl('npm', ['run', 'build'], workDir, undefined, { CADENA_DESGLOSE_PATH: reportPath });
    else await run('npm', ['run', 'build'], workDir, execFile, { CADENA_DESGLOSE_PATH: reportPath });
    beginPhase('verificacion');
    const buildState = JSON.parse(await fs.readFile(path.join(workDir, 'dist', 'estado.json'), 'utf8'));
    const publicados = buildState.publicados;
    await saveBreakdown(workDir, breakdownPath, publicados);
    breakdownReady = true;
    if (!Number.isInteger(publicados) || publicados <= 0) throw new Error('Catálogo vacío o cantidad de comparables inválida');
    // Con menos productos se publican igual los frescos (regla del user: nunca dejar precios viejos); sólo se avisa.
    if (typeof last?.publicados === 'number' && publicados < last.publicados * 0.5) {
      log(`DEPLOY_ALERT caída brusca: ${publicados} comparables contra ${last.publicados} del último despliegue (se publica igual).`);
    }
    buildState.version = version;
    buildState.slot = JSON.parse(raw).slot ?? null;
    await fs.writeFile(path.join(workDir, 'dist', 'estado.json'), JSON.stringify(buildState, null, 1) + '\n');
    beginPhase('publicacion');
    await runImpl('npx', ['--yes', 'wrangler', 'deploy'], workDir);
    beginPhase('estado');
    await fs.mkdir(path.dirname(stateFile), { recursive: true });
    await fs.writeFile(stateFile, JSON.stringify({ hash, date: today, slot, priceSlot: buildState.slot, version, redeploys: recovery ? redeployCount(last) + 1 : 0, publicados, deployedAt: now.toISOString() }));
    await saveResult('ok', `Publicado con precios del ${today}`, now, opts);
    endPhase();
    log(`DEPLOY_OK publicado con precios del ${today}${recovery ? ' (redespliegue por precios recuperados)' : ''}. ${elapsed()}s desglose=${breakdownPath}`);
    return 'ok';
  } catch (error) {
    if (!breakdownReady) {
      // Un build fallido puede haber alcanzado a generar estado.json y su desglose.
      try {
        const state = JSON.parse(await fs.readFile(path.join(workDir, 'dist', 'estado.json'), 'utf8'));
        await saveBreakdown(workDir, breakdownPath, state.publicados);
      } catch {
        await fs.appendFile(breakdownPath, `${stamp.slice(0, 19).replace('T', ' ')} DESGLOSE_NO_DISPONIBLE build sin informe completo\n`).catch(() => {});
      }
    }
    if (phase) log(`DEPLOY_FASE ${phase} fail ${((clock() - phaseStarted) / 1000).toFixed(1)}s ${redact(error.message).replace(/[\r\n]+/g, ' | ')}`);
    log(`DEPLOY_FAIL ${redact(error.message).replace(/[\r\n]+/g, ' | ')} ${elapsed()}s desglose=${breakdownPath}`);
    await saveResult('fail', error.message, now, opts);
    return 'fail';
  }
}

async function deployWithRetry(opts = {}) {
  const nowFn = opts.nowFn ?? (() => new Date());
  const sleepFn = opts.sleepFn ?? sleepMs;
  const deployFn = opts.deployFn ?? deployOnce;
  const retryIntervalMs = opts.retryIntervalMs ?? RETRY_INTERVAL_MS;
  const startedAt = nowFn().getTime();

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
      log(`DEPLOY_FAIL son las 11:00 ART o más: ${check.reason}; no se despliega. ${((now.getTime() - startedAt) / 1000).toFixed(1)}s`);
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

async function runChainIfReady(now = new Date(), opts = {}) {
  const today = artDate(now);
  const markerFile = path.join(opts.outputDir ?? path.dirname(opts.outputFile ?? OUTPUT_FILE), `cadena-${today}.json`);
  const marker = await readJsonWithDate(markerFile);
  if (!marker.ok || marker.data?.fecha !== today) return 'no-marker';
  const state = await readState(opts.stateFile ?? STATE_FILE);
  if (state?.date === today) return 'already-deployed';
  const check = await hasBothTodayPrices(now, opts);
  if (!check.ready) return 'waiting-prices';
  log(`DEPLOY_INFO cadena del ${today} terminada; desplegando ahora.`);
  return await (opts.deployFn ?? deployOnce)(now, opts);
}

async function main() {
  const stop = () => { stopRequested = true; };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  log('Deployer iniciado.');
  const startupStarted = performance.now();
  try {
    await runStartupIfPending();
  } catch (error) {
    log(`DEPLOY_FAIL ${redact(String(error.message))} ${((performance.now() - startupStarted) / 1000).toFixed(1)}s`);
  }
  let chainAttempted = null;
  let announcedNext = null;
  let scheduleState = null;
  while (!stopRequested) {
    const wake = new Date();
    const today = artDate(wake);
    const attemptStarted = performance.now();
    try {
      if (chainAttempted !== today) {
        const result = await runChainIfReady(wake);
        if (!['no-marker', 'waiting-prices'].includes(result)) chainAttempted = today;
      }
      const state = await readState();
      const stateKey = JSON.stringify(state);
      if (announcedNext === null || scheduleState !== stateKey) {
        announcedNext = nextRunAt(wake, state);
        scheduleState = stateKey;
        log(`Próximo despliegue previsto: ${new Date(announcedNext).toISOString()}.`);
      }
      const next = announcedNext;
      if (next > wake.getTime()) {
        // Revisa el marcador aunque el próximo horario fijo esté a varias horas.
        await sleepMs(Math.min(MAX_SLEEP_MS, next - wake.getTime()));
        continue;
      }
      announcedNext = null;
      if (state?.date === today) {
        await deployOnce(wake, { slot: state.slot ?? 'morning' });
      } else {
        await deployWithRetry();
      }
    } catch (error) {
      log(`DEPLOY_FAIL ${redact(String(error.message)).replace(/[\r\n]+/g, ' | ')} ${((performance.now() - attemptStarted) / 1000).toFixed(1)}s`);
      await sleepMs(MAX_SLEEP_MS);
    }
  }
  log('Deployer detenido.');
}

if (process.argv[1] && process.argv[1].endsWith('deploy.mjs')) {
  if (process.argv.includes('--ahora')) {
    const manualStarted = performance.now();
    // 05/11: despliegue manual por el MISMO camino que el automático (altas de catalog-auto, fotos y validaciones).
    // tools/deploy.sh compilaba en la PC sin las altas automáticas y publicaba un catálogo incompleto.
    deployOnce(new Date(), { slot: 'manual', manual: true })
      .then((r) => { log(`DEPLOY_MANUAL ${r}`); process.exit(r === 'ok' ? 0 : 1); })
      .catch((e) => { log(`DEPLOY_FAIL manual: ${redact(String(e.message))} ${((performance.now() - manualStarted) / 1000).toFixed(1)}s`); process.exit(1); });
  } else {
    main();
  }
}

export {
  saveBreakdown,
  run,
  commandTimeout,
  purgeLogs,
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
  runChainIfReady,
  RETRY_INTERVAL_MS,
  DEADLINE_UTC,
  EXTRA_DEPLOY_AT_UTC,
  EXTRA_DEADLINE_UTC,
};
