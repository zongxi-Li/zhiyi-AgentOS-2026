/* Render actual draw.io models using the official draw.io viewer engine. */
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const MODULES = process.env.KINLIN_NODE_MODULES;
if (!MODULES) throw Error('Set KINLIN_NODE_MODULES to the bundled runtime node_modules');
const { chromium } = require(path.join(MODULES,'playwright'));
const BASE=path.resolve(__dirname,'..');
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json','.svg':'image/svg+xml','.drawio':'application/xml'};
async function main(){
 const figures=JSON.parse(await fs.readFile(path.join(BASE,'.build/figures.json'),'utf8'));
 const wanted=process.argv.slice(2);
 const selected=wanted.length?figures.filter(f=>wanted.includes(f.key+'_'+f.lang)):figures;
 const server=http.createServer(async(req,res)=>{
  try{
   const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
   const target=path.resolve(BASE,'.'+pathname);
   if(!target.startsWith(BASE+path.sep))throw Error('outside figure workspace');
   res.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');
   res.end(await fs.readFile(target));
  }catch(e){res.statusCode=404;res.end('not found');}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin=`http://127.0.0.1:${server.address().port}`;
 let browser;
 try{
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1500,height:1200},deviceScaleFactor:2});
  await context.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.abort());
  const page=await context.newPage();
  page.on('pageerror',err=>console.error('PAGE:',err.message));
  await page.goto(origin+'/tools/renderer.html',{waitUntil:'load'});
  await page.waitForFunction(()=>typeof window.loadFigure==='function');
  const reports=[];
  for(const f of selected){
   const xml=await fs.readFile(path.join(BASE,f.path),'utf8');
   const result=await page.evaluate(xml=>window.loadFigure(xml),xml);
   const stem=f.key+'_'+f.lang;
   const file=path.join(BASE,'svg',stem+'.svg');
   await fs.writeFile(file,result.svg);
   reports.push({figure:stem,width:f.width,height:f.height,modelCells:result.modelCells,labels:result.labels,edges:result.edges});
   await page.goto(origin+'/svg/'+stem+'.svg',{waitUntil:'load'});
   await page.evaluate(async()=>{await document.fonts.ready;document.documentElement.style.background='#fff';document.body&&(document.body.style.margin='0');});
   await page.setViewportSize({width:f.width,height:f.height});
   await page.screenshot({path:path.join(BASE,'png',stem+'.png'),clip:{x:0,y:0,width:f.width,height:f.height},scale:'device'});
   // Every PDF has the same 180 mm width; no rasterization is used.
   await page.evaluate(({width,height})=>{const s=document.createElementNS('http://www.w3.org/2000/svg','style');s.textContent=`@page{size:180mm ${180*height/width}mm;margin:0} svg{width:180mm!important;height:${180*height/width}mm!important;display:block}`;document.documentElement.appendChild(s);},{width:f.width,height:f.height});
   await page.pdf({path:path.join(BASE,'pdf',stem+'.pdf'),width:'180mm',height:`${180*f.height/f.width}mm`,margin:{top:0,bottom:0,left:0,right:0},printBackground:true,preferCSSPageSize:true});
   console.log('rendered',stem,result.modelCells);
   await page.goto(origin+'/tools/renderer.html',{waitUntil:'load'});
  }
  const rp=path.join(BASE,'.build/render-validation.json');
  let prior=[];try{prior=JSON.parse(await fs.readFile(rp,'utf8'));}catch{}
  const keys=new Set(reports.map(r=>r.figure));
  await fs.writeFile(rp,JSON.stringify([...prior.filter(r=>!keys.has(r.figure)),...reports],null,2));
 } finally {if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(e=>{console.error(e);process.exitCode=1});
