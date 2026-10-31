import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { deployOnce } from './deploy.mjs';

describe('deployOnce', () => {
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

  it('elimina data/amazon-prices.json previo del workDir cuando falta o es inválido', async () => {
    const outputFile = path.join(tmpDir, 'ml-prices.json');
    const amazonOutputFile = path.join(tmpDir, 'amazon-prices.json');
    const workDir = path.join(tmpDir, 'work');
    const stateFile = path.join(tmpDir, 'state', 'last-deploy.json');

    await fs.mkdir(path.join(workDir, '.git'), { recursive: true });
    await fs.mkdir(path.join(workDir, 'data'), { recursive: true });
    const staleAmazonInWork = path.join(workDir, 'data', 'amazon-prices.json');
    await fs.writeFile(staleAmazonInWork, JSON.stringify({ date: '2026-10-29', items: { viejo: { amount: 100 } } }));

    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 1000 } } }));
    // Caso 1: amazon-prices.json con JSON inválido
    await fs.writeFile(amazonOutputFile, '{json-roto');

    const now = new Date('2026-10-30T10:30:00Z');
    const result = await deployOnce(now, {
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
    });

    expect(result).toBe('ok');
    await expect(fs.access(staleAmazonInWork)).rejects.toThrow();

    // Caso 2: si en un despliegue previo quedó el archivo y ahora amazon-prices.json no existe, también lo borra
    await fs.writeFile(staleAmazonInWork, JSON.stringify({ date: '2026-10-30', items: {} }));
    await fs.rm(amazonOutputFile, { force: true });
    await fs.writeFile(outputFile, JSON.stringify({ date: '2026-10-30', items: { a: { price: 2000 } } }));

    const result2 = await deployOnce(now, {
      outputFile,
      amazonOutputFile,
      workDir,
      stateFile,
      runImpl: async () => '',
    });

    expect(result2).toBe('ok');
    await expect(fs.access(staleAmazonInWork)).rejects.toThrow();
  });
});
