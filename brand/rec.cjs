const { chromium } = require("C:/Users/KnuPwns/AppData/Local/npm-cache/_npx/13ab0715f9f30c2e/node_modules/playwright");
const fs = require("fs");
const out = "C:/Users/KnuPwns/AppData/Local/Temp/claude/E--Repositorios-Personal-weboffers/09a5136b-88b8-4117-9bfd-c55984dd71ba/scratchpad/redes/videos";
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  for (const v of ["1", "2", "3"]) {
    const ctx = await b.newContext({ viewport: { width: 1080, height: 1920 }, recordVideo: { dir: out, size: { width: 1080, height: 1920 } } });
    const p = await ctx.newPage();
    const d = JSON.parse(fs.readFileSync(out + "/../voz/duraciones.json", "utf8"))[v];
    await p.goto("file:///E:/Repositorios/Personal/weboffers/brand/video.html?v=" + v + "&d=" + encodeURIComponent(JSON.stringify(d)));
    await p.waitForFunction(() => window.DONE === true, null, { timeout: 120000, polling: 200 });
    const path = await p.video().path();
    await ctx.close();
    fs.renameSync(path, out + "/raw-" + v + ".webm");
    console.log("ok", v);
  }
  await b.close();
})();
