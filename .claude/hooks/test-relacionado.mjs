// PostToolUse (Edit/Write/MultiEdit): corre sólo el test del archivo tocado.
//  - .ts/.tsx/.mjs bajo src/ o worker/deployer/ → `npx vitest related <archivo> --run`
//  - .py → el propio test_*.py, o worker/test_<nombre>.py si existe (los de tools/ viven ahí)
// Sin test relacionado no hace nada. Si falla, exit 2: Claude ve el error y lo corrige.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

let raw = '';
for await (const chunk of process.stdin) raw += chunk;
let input;
try { input = JSON.parse(raw); } catch { process.exit(0); }

const file = input?.tool_input?.file_path;
if (!file) process.exit(0);
const root = process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd();
const rel = path.relative(root, path.resolve(file)).split(path.sep).join('/');
if (rel.startsWith('..') || rel.startsWith('node_modules/')) process.exit(0);
// En Windows spawnSync va con shell: sólo rutas con caracteres seguros (evita inyección por nombre de archivo).
if (!/^[\w\/.-]+$/.test(rel)) process.exit(0);

const ext = path.extname(rel);
let run = null;

if (['.ts', '.tsx', '.mjs'].includes(ext) && /^(src|worker\/deployer)\//.test(rel)) {
  run = ['npx', ['vitest', 'related', rel, '--run', '--silent', '--passWithNoTests']];
} else if (ext === '.py') {
  const base = path.basename(rel, '.py');
  const test = base.startsWith('test_') ? rel : `worker/test_${base}.py`;
  if (existsSync(path.join(root, test))) run = ['python', ['-m', 'pytest', test, '-q', '-x', '-p', 'no:cacheprovider']];
}
if (!run) process.exit(0);

const r = spawnSync(run[0], run[1], { cwd: root, encoding: 'utf8', shell: process.platform === 'win32', timeout: 90_000 });
if (r.status !== 0) {
  const out = `${r.stdout ?? ''}\n${r.stderr ?? ''}`.trim().split('\n').slice(-30).join('\n');
  process.stderr.write(`[test-relacionado] ${run[0]} ${run[1].join(' ')} falló tras editar ${rel}:\n${out}\n`);
  process.exit(2);
}
process.exit(0);
