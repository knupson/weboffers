import { readFileSync } from 'node:fs';

export function validatePriceFiles(files, now = new Date()) {
  const today = new Date(now.getTime() - 3 * 3600e3).toISOString().slice(0, 10);
  for (const file of files) {
    const data = JSON.parse(readFileSync(file, 'utf8'));
    if (data.date !== today) throw new Error(`${file}: fecha ${data.date}; se requieren precios del ${today} ART`);
  }
}

if (process.argv[1]?.endsWith('validate-price-files.mjs')) validatePriceFiles(process.argv.slice(2));
