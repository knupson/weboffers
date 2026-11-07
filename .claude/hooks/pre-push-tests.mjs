// PreToolUse (Bash/PowerShell): antes de cualquier `git push` corre vitest y pytest.
// El deployer de la VM clona main: un push con tests rotos termina en ofertas.knunet.com.
// Si algo falla, bloquea el push (exit 2) y le devuelve a Claude el error literal.
import { spawnSync } from 'node:child_process';

let raw = '';
for await (const chunk of process.stdin) raw += chunk;
let input;
try { input = JSON.parse(raw); } catch { process.exit(0); }

const command = input?.tool_input?.command ?? '';
if (!/\bgit\s+(?:-[^\s]+\s+)*push\b/.test(command)) process.exit(0);

// El hook corre ANTES del comando entero: si el mismo comando cambia el árbol antes del push
// (merge, pull…), los tests verían el árbol viejo. 07/11: `git merge … && git push` subió un test roto.
const pushAt = command.search(/\bgit\s+(?:-[^\s]+\s+)*push\b/);
if (/\bgit\s+(?:-[^\s]+\s+)*(merge|pull|rebase|cherry-pick|checkout|switch|reset|am|stash)\b/.test(command.slice(0, pushAt))) {
  process.stderr.write('[pre-push] El comando cambia el árbol antes del push: los tests correrían sobre el árbol viejo. Hacé el merge/pull primero y el `git push` en un comando aparte.\n');
  process.exit(2);
}

const cwd = process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd();
const suites = [
  ['vitest', 'npm', ['test', '--silent']],
  ['pytest', 'python', ['-m', 'pytest', 'worker', '-q', '-x', '-p', 'no:cacheprovider']],
];

for (const [name, cmd, args] of suites) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8', shell: process.platform === 'win32', timeout: 240_000 });
  if (r.status !== 0) {
    const out = `${r.stdout ?? ''}\n${r.stderr ?? ''}`.trim().split('\n').slice(-40).join('\n');
    process.stderr.write(`[pre-push] ${name} falló (status ${r.status}); push bloqueado. Arreglar y volver a pushear.\n${out}\n`);
    process.exit(2);
  }
}
process.exit(0);
