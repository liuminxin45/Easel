// Uses only the documented CUA browser API. Never touches external browser profiles.
export async function closeProductionBrowser(cua, threadId, operationId) {
  if (typeof threadId!=='string'||!threadId||typeof operationId!=='string'||!operationId) throw new TypeError('Explicit thread and operation required');
  const report = {operation_id:operationId,thread_id:threadId,status:'unavailable',browser_count:0,closed_count:0,remaining_count:null,errors:[]};
  let browsers;
  try { browsers=await cua.listBrowsers({emit:false}); }
  catch { report.errors.push({phase:'inventory'}); return report; }
  const owned=browsers.filter(b=>b.type==='iab'&&b.metadata?.codexSessionId===threadId);
  if (!owned.length) return report;
  report.browser_count=owned.length;
  let remaining=0,verified=true;
  for (const info of owned) {
    let browser;
    try { browser=await cua.getBrowser({id:info.id}); }
    catch { report.errors.push({browser_id:info.id,phase:'bind'});verified=false;continue; }
    try {
      let tabs=await browser.tabs.list();
      // A page can close itself or create a popup while closing. Re-list each pass.
      for (let pass=0;pass<3&&tabs.length;pass++) {
        for (const item of tabs) {
          try { await (await browser.tabs.get(item.id)).close();report.closed_count++; }
          catch { report.errors.push({browser_id:info.id,tab_id:item.id,phase:'close'}); }
        }
        tabs=await browser.tabs.list();
      }
      remaining+=tabs.length;
    } catch { report.errors.push({browser_id:info.id,phase:'verify'});verified=false; }
  }
  if (verified) {
    report.remaining_count=remaining;
    report.status=remaining?'incomplete':report.closed_count?'closed':'already_empty';
  } else report.status='unconfirmed';
  return report;
}

export function cleanupReceipt(report) {
  return '<!-- TOOLBOX_BROWSER_CLEANUP '+JSON.stringify(report)+' -->';
}
