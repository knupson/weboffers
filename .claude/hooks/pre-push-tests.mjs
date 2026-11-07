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
