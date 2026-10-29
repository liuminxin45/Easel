"""One narrow handoff from the retained shell to the native account workspace."""
from __future__ import annotations
import urllib.parse
from fastapi.responses import Response

ACCOUNTS_PATH='/toolbox?section=distribution&pane=connections'
ACCOUNT_TOOL={'id':'platform_accounts','name':'账号连接','path':ACCOUNTS_PATH,
              'description':'连接和检查发布平台账号。','icon':'SettingsIcon','group':'insights'}

SCRIPT=r'''(()=>{
  'use strict';
  if(window.__distributionEntryBound)return;
  window.__distributionEntryBound=true;
  const target='/native/?'+new URLSearchParams({path:'/toolbox?section=distribution&pane=connections'});
  document.addEventListener('click',event=>{
    if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    const element=event.target instanceof Element?event.target.closest('[data-desktop-action="studio.nav.tool.platform_accounts"]'):null;
    if(!element||element.hasAttribute('disabled')||!element.closest('nav[aria-label="工作台导航"],nav[aria-label="桌面工作台导航"]'))return;
    event.preventDefault();event.stopImmediatePropagation();
    window.location.assign(target);
  },true);
})();'''

def inject(html):
    marker='<script defer src="/distribution-entry.js"></script>'
    if marker in html:return html
    if '</head>' not in html:raise ValueError('工作台页面缺少头部')
    return html.replace('</head>',marker+'</head>',1)

def script_response(method):
    # The shared server computes representation compression/length, then strips
    # the HEAD body; supplying the same bytes preserves GET/HEAD parity.
    return Response(SCRIPT,media_type='text/javascript',headers={
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Cross-Origin-Resource-Policy':'same-origin','Content-Length':str(len(SCRIPT.encode('utf-8')))})

def native_target(query):
    """Only the named workspace, not an arbitrary URL, may cross the shell."""
    if 'distribution' not in query.getlist('section'):return None
    allowed={'section','pane','work','version','item'}
    if any(key not in allowed for key in query) or any(len(query.getlist(key))!=1 for key in query):raise ValueError('分发入口参数无效')
    if query.get('pane','pending') not in ('pending','connections','history'):raise ValueError('分发页面无效')
    values={key:query[key] for key in query}
    from easel_workbench.runtime.toolbox_store import ident
    for key in ('work','version','item'):
        if key in values:ident(values[key])
    route='/toolbox?'+urllib.parse.urlencode(values)
    return '/native/?'+urllib.parse.urlencode({'path':route})
