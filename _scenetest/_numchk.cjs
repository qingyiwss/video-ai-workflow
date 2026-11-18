const puppeteer = require(process.env.KAZI_PUPPETEER);
const fs = require('fs'); const path = require('path');
(async () => {
  const base = process.argv[2];
  const tl = JSON.parse(fs.readFileSync(path.join(base,'timeline.json'),'utf8'));
  const def = JSON.parse(fs.readFileSync(path.join(base,'scene-def.json'),'utf8'));
  const b = await puppeteer.launch({executablePath: process.env.KAZI_CHROME,
    headless:'new', args:['--no-sandbox','--allow-file-access-from-files']});
  const p = await b.newPage();
  await p.setViewport({width:1080,height:1920});
  await p.evaluateOnNewDocument((k,d)=>{window.__KIT__=k;window.__DEF__=d;}, tl, def);
  await p.goto('file:///'+path.join(base,'canvas.html').replace(/\\/g,'/')+'?ratio=9:16',
               {waitUntil:'networkidle0'});
  await new Promise(r=>setTimeout(r,1000));
  await p.evaluate(()=>window.initScene());
  await p.evaluate((t)=>window.renderFrame(t), 56.76);
  await new Promise(r=>setTimeout(r,200));
  const info = await p.evaluate(() => {
    const out = {};
    for (const id of ['nb','nl','ns','nline']) {
      const el = document.getElementById(id);
      if (!el) { out[id] = null; continue; }
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      out[id] = {top: Math.round(r.top), bottom: Math.round(r.bottom),
                 h: Math.round(r.height), font: cs.fontSize, lh: cs.lineHeight,
                 text: el.textContent.trim().slice(0,10)};
    }
    return out;
  });
  console.log(JSON.stringify(info, null, 1));
  await b.close();
})();
