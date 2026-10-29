"""Daily AI-bot HTML collector. No dependencies, no page archives."""
import datetime as dt
import html
import re
import time
import urllib.request

URL = 'https://ai-bot.cn/daily-ai-news/'
CST = dt.timezone(dt.timedelta(hours=8))

def text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', value))).strip()

def collect(page, day):
    # The site's news-list divs are nested/unclosed: split on date markers,
    # not on enclosing div boundaries, to avoid yesterday leaking into today.
    markers = list(re.finditer(r'<div\b[^>]*class=[\"\"][^\"\"]*\bnews-date\b[^\"\"]*[\"\"][^>]*>(.*?)</div>', page, re.S))
    if not markers:
        raise ValueError('news-date markers missing; HTML structure changed')
    result = []
    found = False
    for index, marker in enumerate(markers):
        label = text(marker.group(1))
        match = re.search(r'(\d{1,2})月(\d{1,2})', label)
        if not match:
            raise ValueError('unrecognized date marker')
        if (int(match[1]), int(match[2])) != (day.month, day.day):
            continue
        found = True
        section = page[marker.end():markers[index+1].start() if index+1 < len(markers) else len(page)]
        for item in re.split(r'<div\b[^>]*class=[\"\"][^\"\"]*\bnews-item\b[^\"\"]*[\"\"][^>]*>', section)[1:]:
            heading = re.search(r'<h2\b[^>]*>\s*<a\b[^>]*href=[\"\"]([^\"\"]+)[\"\"][^>]*>(.*?)</a>\s*</h2>', item, re.S)
            paragraph = re.search(r'<p\b[^>]*>(.*?)</p>', item, re.S)
            if not heading or not paragraph:
                raise ValueError('incomplete news item; HTML structure changed')
            link = html.unescape(heading[1])
            if not link.startswith(('https://', 'http://')):
                raise ValueError('invalid article URL')
            entry = (text(heading[2]), text(paragraph[1]), link)
            if entry not in result:
                result.append(entry)
    if found and not result:
        raise ValueError('today section exists but contains no readable articles')
    return result

def fetch():
    from easel_workbench.collectors import enabled, acquire
    if enabled():
        return acquire('aibot',{})
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (DailyNewsReader)', 'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 200:
                    raise ValueError('HTTP ' + str(response.status))
                return response.read(5_000_001).decode('utf-8')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)

