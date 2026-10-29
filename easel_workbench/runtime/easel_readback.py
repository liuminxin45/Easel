"""Conservative translation of independently observed platform items."""
import datetime as dt
import re


def receipt(value, revision, platform):
    verdict=value.get('readback') or {}
    matched=verdict.get('matched') or {}
    result={'remote_state':'unknown','verified':False,'account':revision['account'],'revision_hash':revision['hash'],
            'remote_id':matched.get('platform_content_id'),'evidence':[{'kind':'platform_readback','outcome':verdict.get('outcome','not_obtained'),'remote_id':matched.get('platform_content_id')}],
            'error':'尚无完整平台证据；保留原发送记录，不重新发布'}
    remote=str(matched.get('platform_content_id') or '')
    if verdict.get('outcome')!='verified' or value.get('account')!=revision['account'] or matched.get('title')!=revision['title']:return result
    status=matched.get('status')
    if platform=='bilibili' and re.fullmatch(r'(?:BV[A-Za-z0-9]+|av[0-9]+)',remote):
        url='https://www.bilibili.com/video/'+remote
        state='published' if status=='已发布' else 'pending_review' if status in ('审核中','待审核','转码中') else None
    elif platform=='douyin' and re.fullmatch(r'[0-9]{5,40}',remote):
        url='https://www.douyin.com/video/'+remote
        state='published' if status=='published' else 'pending_review' if status=='reviewing' else None
    elif platform=='kuaishou' and re.fullmatch(r'[A-Za-z0-9_-]{5,100}',remote):
        url='https://www.kuaishou.com/short-video/'+remote
        state='published' if status=='published' else 'pending_review' if status=='reviewing' else None
    else:return result
    if not state:return result
    timestamp=matched.get('published_at_ms')
    if state=='published':
        if type(timestamp) not in (int,float) or timestamp<=0:return result
        try:published=dt.datetime.fromtimestamp(timestamp/1000,dt.timezone.utc).isoformat()
        except (ValueError,OSError,OverflowError):return result
        if timestamp>dt.datetime.now(dt.timezone.utc).timestamp()*1000+60000:return result
        result['published_at']=published
    result.update(remote_state=state,verified=True,safe_url=url,error=None)
    return result
