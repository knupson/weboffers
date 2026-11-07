// PreToolUse (Bash|PowerShell): toda consulta manual al scraper de Amazon pasa por tools/probar_scraper.py.
// Motivo (07/11/2026): consultas a mano sin imprimir el error, un ASIN inventado y una prueba con un producto
// fuera de USD 100-400. La herramienta hace esas tres cosas sola; este hook impide saltearla.
import fs from 'node:fs';

let input = {};
try { input = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); } catch { process.exit(0); }
const cmd = String(input.tool_input?.command || '');
const tocaScraper = /(weboffers-)?amazon-scraper:8000|amazon-scraper-1\b.*(curl|wget|requests)/i.test(cmd);
if (!tocaScraper || /probar_scraper\.py/.test(cmd)) process.exit(0);
process.stdout.write(JSON.stringify({
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    permissionDecision: 'deny',
    permissionDecisionReason: "Las consultas al scraper de Amazon van por tools/probar_scraper.py (imprime siempre el error, no acepta ASIN inventados y marca el rango USD 100-400). Uso: ssh docker 'docker exec -i -w /app franquicia400-weboffers-worker-1 python - <endpoint> clave=valor ...' < tools/probar_scraper.py",
  },
}));
