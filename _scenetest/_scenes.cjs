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
  const info = await p.evaluate(() => window.__S__.map(s => ({
    sid: s.sid, kind: s.kind,
    inFrom: +s.inFrom.toFixed(2), outTo: +s.outTo.toFixed(2),
    hit: s.update ? undefined : undefined
  })));
  console.log(JSON.stringify(info, null, 1));
  await b.close();
})();
