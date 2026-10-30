import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {build} from 'vite';
import react from '@vitejs/plugin-react';

const frontend=path.resolve(import.meta.dirname,'..'),root=path.resolve(frontend,'../..');
if(process.version!=='v24.19.0')throw Error('Node 24.19.0 required');
execFileSync(process.execPath,['node_modules/typescript/bin/tsc','-p','tsconfig.workbench.json'],{cwd:frontend,stdio:'inherit'});
execFileSync(process.execPath,[path.join(root,'scripts/audit_workbench_interactions.mjs')],{cwd:root,stdio:'inherit'});
execFileSync(process.execPath,[path.join(root,'scripts/audit_easel_base.mjs')],{cwd:root,stdio:'inherit'});
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const release=process.env.NATIVE_RELEASE_ID||'native-easel-workbench-'+new Date().toISOString().replace(/\D/g,'').slice(0,14);
if(!/^native-[\w-]{1,80}$/.test(release))throw Error('Invalid release');
const out=path.join(root,'native-releases',release);
if(fs.existsSync(out))throw Error('Immutable release exists');
const aliases={'@workbench/core':'core/index.ts','@workbench/platform':'platform/index.ts','@workbench/ui-easel':'ui/index.tsx'};
const sources=()=>{
  const files=fs.readdirSync(path.join(frontend,'src'),{recursive:true})
    .filter(n=>fs.statSync(path.join(frontend,'src',n)).isFile())
    .map(n=>'web/frontend/src/'+n.replaceAll('\\','/'));
  files.push(...['package.json','package-lock.json','tsconfig.workbench.json','workbench.html','auth.html','scripts/build-workbench.mjs'].map(n=>'web/frontend/'+n),
    'web/static/easel-icon-transparent.png','scripts/audit_workbench_interactions.mjs','easel_workbench/assets/native-reconnect.js','easel_workbench/assets/native-sw-template.js','docs/workbench/import-baseline.json','docs/workbench/upstream-base.json','scripts/audit_easel_base.mjs','LICENSE');
  return Object.fromEntries(files.sort().map(n=>[n,sha(fs.readFileSync(path.join(root,n)))]));
};
const inputs=sources();
await build({configFile:false,root:frontend,plugins:[react()],resolve:{alias:Object.fromEntries(Object.entries(aliases).map(([k,v])=>[k,path.join(frontend,'src/workbench',v)]))},base:'/native-assets/'+release+'/',build:{outDir:out,emptyOutDir:false,manifest:true,target:'es2022',rollupOptions:{input:{index:path.join(frontend,'workbench.html'),auth:path.join(frontend,'auth.html')}}},logLevel:'warn'});
fs.mkdirSync(path.join(out,'static'));fs.copyFileSync(path.join(root,'web/static/easel-icon-transparent.png'),path.join(out,'static/easel-icon-transparent.png'));
fs.renameSync(path.join(out,'workbench.html'),path.join(out,'index.html'));
for(const file of ['index.html','auth.html']){const p=path.join(out,file);fs.writeFileSync(p,fs.readFileSync(p,'utf8').replaceAll('__NATIVE_RELEASE__',release));}
fs.mkdirSync(path.join(out,'licenses'));fs.copyFileSync(path.join(root,'LICENSE'),path.join(out,'licenses/Easel-LICENSE.txt'));
fs.copyFileSync(path.join(root,'docs/workbench/import-baseline.json'),path.join(out,'licenses/Workbench-SOURCE.json'));
fs.writeFileSync(path.join(out,'licenses/Easel-NOTICE.txt'),'Easel, Apache-2.0. Source: https://github.com/ZJU-REAL/Easel\nLocal fork base: 514caf8089f89b4793063aeae867690cc69bf8b8\nPrivate workflow adaptation: easel_workbench and web/frontend/src/workbench.\n');
fs.copyFileSync(path.join(root,'easel_workbench/assets/native-reconnect.js'),path.join(out,'reconnect.js'));
const assets=fs.readdirSync(out,{recursive:true}).filter(n=>fs.statSync(path.join(out,n)).isFile()&&/\.(js|css|woff2?|svg|png|webp)$/.test(n)).map(n=>'/native-assets/'+release+'/'+n.replaceAll('\\','/'));
fs.writeFileSync(path.join(out,'sw.js'),`const VERSION=${JSON.stringify(release)},CACHE='native-static-'+VERSION,SHELL='native-shell-'+VERSION,ASSETS=${JSON.stringify(assets)};\n`+fs.readFileSync(path.join(root,'easel_workbench/assets/native-sw-template.js'),'utf8'));
fs.writeFileSync(path.join(out,'manifest.webmanifest'),JSON.stringify({id:'/native/',name:'创作工作台',short_name:'工作台',start_url:'/native/',scope:'/native/',display:'standalone'}));
fs.writeFileSync(path.join(out,'build-inputs.json'),JSON.stringify({node:process.version,inputs},null,2));
if(JSON.stringify(inputs)!==JSON.stringify(sources()))throw Error('Source changed during build');
const files=Object.fromEntries(fs.readdirSync(out,{recursive:true}).filter(n=>fs.statSync(path.join(out,n)).isFile()).map(n=>[n.replaceAll('\\','/'),sha(fs.readFileSync(path.join(out,n)))]));
const manifest={schema:1,release,architecture:'easel-workbench-extension',entry:'index.html',auth:'auth.html',files,preview_only:true};fs.writeFileSync(path.join(out,'native-manifest.json'),JSON.stringify(manifest,null,2));
console.log(JSON.stringify({release,manifest_sha256:sha(fs.readFileSync(path.join(out,'native-manifest.json'))),output:out}));
