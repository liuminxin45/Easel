"""Strict numeric/enum projection for the independent operator report."""
import html
import re

KINDS = ('attempt', 'view', 'exposure', 'activate', 'commit', 'dismiss', 'accepted', 'failed', 'uncertain', 'local_success')


def project(value):
    if not isinstance(value, dict) or value.get('status') != 'available':
        return {'status': 'unavailable'}
    def identifier(value):
        return isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', value) is not None
    def count(value):
        return type(value) is int and 0 <= value <= 2**53
    result = {'status': 'available', 'days': 7, 'enabled': value.get('enabled') is True}
    totals = value.get('totals', {})
    result['totals'] = {key: totals[key] for key in KINDS if isinstance(totals, dict) and count(totals.get(key))}
    for field, keys, numeric in (('actions', ('id',), KINDS), ('screens', ('id',), ('count',)), ('paths', ('from', 'to'), ('count',))):
        raw = value.get(field, [])
        rows = []
        for row in raw[:128] if isinstance(raw, list) else []:
            if not isinstance(row, dict) or not all(identifier(row.get(key)) for key in keys):
                continue
            rows.append({**{key: row[key] for key in keys}, 'retired': row.get('retired') is True,
                **{key: row[key] for key in numeric if count(row.get(key))}})
        result[field] = rows
    return result


def render(value):
    usage = project(value)
    body = '<section aria-label="使用与路径"><h2>使用与路径</h2>'
    if usage['status'] != 'available':
        return body+'<p>当前使用数据不可用；历史数据保留。此状态不触发应用重启。</p></section>'
    body += '<p>最近7天 · '+('记录中' if usage['enabled'] else '已暂停记录')+'。仅显示登记的标识与计数，不含正文、文件名或凭据。历史数据继续保留在应用原统计库，沿用原保留期限。</p>'
    for retired, title in ((False, '当前页面与操作'), (True, '已退役页面与操作的历史记录')):
        body += '<h3>'+title+'</h3>'
        for field, heading, columns in (
                ('screens', '页面访问', (('id', '页面'), ('count', '访问'))),
                ('actions', '操作', (('id', '操作标识'), ('activate', '激活'), ('accepted', '提交受理'), ('uncertain', '结果未知'))),
                ('paths', '常走路径', (('from', '来源'), ('to', '去向'), ('count', '次数')))):
            rows = [row for row in usage[field] if row['retired'] == retired]
            body += '<h4>'+heading+'</h4>'
            if not rows:
                body += '<p>本时间范围暂无记录。</p>'
                continue
            body += '<div class="usage-table"><table><thead><tr>'+''.join('<th scope="col">'+label+'</th>' for _, label in columns)+'</tr></thead><tbody>'
            for row in rows:
                body += '<tr>'+''.join('<td>'+html.escape(str(row.get(key, 0)))+'</td>' for key, _ in columns)+'</tr>'
            body += '</tbody></table></div>'
    return body+'</section>'
