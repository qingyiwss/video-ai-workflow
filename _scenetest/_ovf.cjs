const puppeteer = require(process.env.KAZI_PUPPETEER);
const fs = require('fs'); const path = require('path');
const RATIOS = {'9:16':{w:1080,h:1920},'16:9':{w:1920,h:1080},'4:3':{w:1440,h:1080},'1:1':{w:1080,h:1080}};
const TIMES = [3.70,17.66,31.88,44.52,56.76,68.20,81.30,93.44,104.44,116.16];
(async () => {
  const base = path.resolve(process.argv[2]);
  const tl = JSON.parse(fs.readFileSync(path.join(base,'timeline.json'),'utf8'));
  const def = JSON.parse(fs.readFileSync(path.join(base,'scene-def.json'),'utf8'));
  const b = await puppeteer.launch({executablePath: process.env.KAZI_CHROME,
    headless:'new', args:['--no-sandbox','--allow-file-access-from-files']});
  let totalBad = 0;
  for (const ratio of Object.keys(RATIOS)) {
    const R = RATIOS[ratio];
    const p = await b.newPage();
    await p.setViewport({width:R.w, height:R.h, deviceScaleFactor:1});
    await p.evaluateOnNewDocument((k,d)=>{window.__KIT__=k;window.__DEF__=d;}, tl, def);
    await p.goto('file:///'+path.join(base,'canvas.html').replace(/\\/g,'/')+'?ratio='+ratio,
                 {waitUntil:'networkidle0'});
    await new Promise(r=>setTimeout(r,900));
    await p.evaluate(()=>window.initScene());
    let bad = [];
    for (const t of TIMES) {
      await p.evaluate((tt)=>window.renderFrame(tt), t);
      await new Promise(r=>setTimeout(r,60));
      const found = await p.evaluate(() => {
        const stage = document.getElementById('stage');
        const sr = stage.getBoundingClientRect();
        const out = [];
        stage.querySelectorAll('*').forEach(el => {
          const cs = getComputedStyle(el);
          if (cs.display==='none'||cs.visibility==='hidden'||parseFloat(cs.opacity)<0.01) return;
          const r = el.getBoundingClientRect();
          if (r.width<2||r.height<2) return;
          if (sr.left-1<=r.left && r.right<=sr.right+1 && sr.top-1<=r.top && r.bottom<=sr.bottom+1) return;
          out.push(el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+' "'+(el.textContent||'').trim().slice(0,10)+'"');
        });
        return [...new Set(out)];
      });
      if (found.length) bad.push(`t=${t}: ${found.slice(0,3).join(' | ')}`);
    }
    if (bad.length === 0) console.log(`  ${ratio.padEnd(5)} ${TIMES.length} 个时刻  无溢出 OK`);
    else { totalBad += bad.length; console.log(`  ${ratio.padEnd(5)} ${bad.length} 处溢出`);
           bad.slice(0,4).forEach(x=>console.log(`        ${x}`)); }
    await p.close();
  }
  console.log(`\n  合计溢出时刻: ${totalBad}`);
  await b.close();
})();
