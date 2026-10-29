"""Read article and test evidence only from this version's captured products."""
import json
import pathlib
import urllib.parse


def from_artifacts(rows, root, mode='auto'):
    root = pathlib.Path(root).resolve()
    issues = []
    def file(name, limit=2_000_000):
        matches = [row for row in rows if row['name'] == name]
        if len(matches) != 1:
            raise ValueError('未收到唯一的交付文件：' + str(name))
        row = matches[0]
        path = pathlib.Path(row['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError('交付文件不可用：' + str(name))
        return row, path
    result = {'title':'', 'body':'', 'ready':False, 'type':'product' if mode=='product' else 'unclassified', 'issues':issues, 'evidence':[], 'sources':[], 'test':None}
    try:
        _, path = file('文章交付.json', 128_000)
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if manifest.get('schema_version') != 1 or manifest.get('article_type') not in ('general','product'):
            raise ValueError('文章交付清单缺少有效的文章类型')
        result['type'] = 'product' if mode=='product' else manifest['article_type']
        _, path = file(manifest.get('body_file'))
        if path.suffix.lower() not in ('.md','.txt'):
            raise ValueError('文章正文需要 Markdown 或纯文本文件')
        result['body'] = path.read_text(encoding='utf-8-sig').strip()
        title=manifest.get('title','')
        if not isinstance(title,str) or not title.strip() or len(title)>500:
            raise ValueError('文章交付清单缺少标题')
        result['title']=title
        if not result['body']:raise ValueError('文章正文为空')
        sources = manifest.get('sources')
        if not isinstance(sources,list) or len(sources)>100:
            raise ValueError('文章交付清单缺少来源列表')
        for source in sources:
            url = urllib.parse.urlsplit(source['url'])
            if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or not all(isinstance(source.get(key),str) and source[key].strip() for key in ('title','checked_at')):
                raise ValueError('来源需要直接链接、标题和核对时间')
        result['sources'] = sources
        if result['type']=='product':
            test = manifest.get('test',{})
            result['test'] = {key:test.get(key) if isinstance(test.get(key),str) else '' for key in ('status','environment','recording_reason','limitations')}
            if test.get('status')!='completed' or not isinstance(test.get('environment'),str) or not test['environment'].strip():
                raise ValueError('产品文章尚未完成真实实测，请保留实际阻碍并补齐证据')
            _, record = file(test.get('record_file'))
            if record.suffix.lower() not in ('.md','.txt') or not record.read_text(encoding='utf-8-sig').strip():
                raise ValueError('缺少可阅读的实测记录')
            steps = test.get('steps')
            if not isinstance(steps,list) or not steps or any(not isinstance(step,dict) or not all(isinstance(step.get(key),str) and step[key].strip() for key in ('action','expected','actual')) for step in steps):
                raise ValueError('实测记录需要操作步骤、预期和真实结果')
            screenshots = test.get('screenshots')
            recordings = test.get('recordings',[])
            if not isinstance(screenshots,list) or not screenshots or not isinstance(recordings,list) or type(test.get('recording_required')) is not bool or not isinstance(test.get('recording_reason'),str) or not test['recording_reason'].strip():
                raise ValueError('实测需要截图及录屏需求说明')
            if test['recording_required'] and not recordings:
                raise ValueError('动态过程需要录屏，尚未收到录屏文件')
            evidence = []
            for name in [*screenshots,*recordings]:
                row, path = file(name, 300_000_000)
                with path.open('rb') as stream:header=stream.read(32)
                if name in screenshots:
                    valid = path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif') and (header.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff',b'GIF87a',b'GIF89a')) or header.startswith(b'RIFF') and header[8:12]==b'WEBP')
                else:
                    valid = path.suffix.lower() in ('.mp4','.webm') and (header[4:8]==b'ftyp' or header.startswith(b'\x1aE\xdf\xa3'))
                if not valid:raise ValueError('实测媒体格式无效：'+str(name))
                evidence.append({'id':row['id'],'name':row['name'],'mime':row['mime']})
            names=set(screenshots+recordings)
            if any(not isinstance(step.get('evidence'),list) or not step['evidence'] or any(name not in names for name in step['evidence']) for step in steps):
                raise ValueError('每个实测步骤需要关联已交付的截图或录屏')
            result['evidence'] = evidence
            result['test']['steps'] = steps
        result['ready'] = True
    except (OSError,ValueError,TypeError,KeyError,AttributeError,UnicodeError) as exc:
        issues.append(str(exc) if isinstance(exc,ValueError) and not isinstance(exc,json.JSONDecodeError) else '文章交付清单或文件不完整，请补齐正文与实测材料')
    return result
