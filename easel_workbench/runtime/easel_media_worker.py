"""One frozen media stage per isolated child process; stdin carries secrets.

The unmodified Easel scripts run only here. HTTP task receipts are journalled
before returning control to a script. A failed/unknown POST is never retried here.
"""
from __future__ import annotations

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))


import contextlib
import hashlib
import io
import json
import mimetypes
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
import base64

from easel_workbench.runtime.easel_connection_support import safe_env


class TaskPending(RuntimeError):
    pass


def read_only_reconcile(payload,receipt,output):
    """Resume only a previously observed GET status endpoint, never submission."""
    url=receipt.get('_poll_url');task=receipt.get('upstream_task_id')
    if not isinstance(url,str) or not task or task not in urllib.parse.unquote(url):raise TaskPending('未取得可只读核对的准确上游任务')
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in ('https','http') or parsed.username or parsed.password:raise TaskPending('轮询入口无效')
    allowed={urllib.parse.urlsplit(v).netloc for k,v in payload['env'].items() if ('BASE' in k or k.endswith('_URL')) and v.startswith(('https://','http://'))}
    allowed|={'dashscope.aliyuncs.com','ark.cn-beijing.volces.com','api.klingai.com','maas.devops.xiaohongshu.com','apihub.agnes-ai.com'}
    if parsed.netloc not in allowed:raise TaskPending('轮询入口不属于冻结提供方')
    import model_registry
    channel=payload['stage'];spec=model_registry.MODEL_GROUPS[channel]
    provider=next(p for p in spec['providers'] if p['id']==payload['config']['provider'])
    keys=[payload['env'].get(k['env']) for k in provider['keys'] if k.get('secret',True) and payload['env'].get(k['env'])]
    if not keys:raise TaskPending('冻结凭据不可用')
    token=keys[0]
    if provider['id']=='kling':
        import ai_video
        token=ai_video._kling_jwt(payload['env']['KLING_ACCESS_KEY'],payload['env']['KLING_SECRET_KEY'])
    header=payload['env'].get('IMG_API_KEY_HEADER') if channel=='image' else 'api-key' if provider['id']=='xhs-maas' else None
    headers={header:token} if header else {'Authorization':'Bearer '+token}
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers,method='GET'),timeout=60) as response:
        value=json.loads(response.read(20*1024*1024))
    statuses=[];urls=[];encoded=[]
    def walk(value,key=''):
        if isinstance(value,dict):
            for name,item in value.items():walk(item,name)
        elif isinstance(value,list):
            for item in value:walk(item,key)
        elif isinstance(value,str):
            if key in ('status','task_status','state'):statuses.append(value.upper())
            if key in ('url','image_url','image_urls','video_url','audio_url','music_url','result_url','video') and value.startswith(('https://','http://')):urls.append(value)
            if key in ('b64_json','base64'):encoded.append(value)
    walk(value)
    if any(status in ('FAILED','FAILURE','ERROR','CANCELED','CANCELLED') for status in statuses):
        receipt['provider_failed']=True
        raise ValueError('上游明确返回任务失败')
    if not urls and not encoded:raise TaskPending('上游任务尚未交付成品')
    if encoded:
        raw=base64.b64decode(encoded[0],validate=True)
        if len(raw)>512*1024*1024:raise ValueError('媒体交付过大')
        output.write_bytes(raw)
    else:
        downloaded=0
        # Download responses never receive the provider's authentication header.
        with urllib.request.urlopen(urls[0],timeout=180) as source,output.open('wb') as target:
            while True:
                chunk=source.read(65536)
                if not chunk:break
                downloaded+=len(chunk)
                if downloaded>512*1024*1024:raise ValueError('媒体交付过大')
                target.write(chunk)
    return output


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, path)


def run_vendor(name, args, source, images=None):
    sys.argv = [str(source / (name + '.py')), *[str(a) for a in args]]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            if name=='ai_image' and images and len(images)>1:
                import importlib
                module=importlib.import_module('ai_image')
                original_encode=module._encode_multipart
                def encode(fields, files):
                    extra=[('image[]',f'reference-{i}'+pathlib.Path(p).suffix,mimetypes.guess_type(p)[0] or 'image/png',pathlib.Path(p).read_bytes()) for i,p in enumerate(images)]
                    return original_encode(fields,extra+[f for f in files if f[0]=='mask'])
                module._encode_multipart=encode
                original_post=module.http_post
                def post(url,key,payload,**kwargs):
                    if 'image_urls' in payload:payload['image_urls']=[module.encode_image_data_uri(p) for p in images]
                    if isinstance(payload.get('extra_body'),dict) and 'image' in payload['extra_body']:payload['extra_body']['image']=[module.encode_image_data_uri(p) for p in images]
                    return original_post(url,key,payload,**kwargs)
                module.http_post=post
                module.main([str(a) for a in args])
            else:
                runpy.run_path(sys.argv[0], run_name='__main__')
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError('媒体工具未完成') from None


def compose(payload, output):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('缺少 ffmpeg，请在环境管理安装')
    files = [pathlib.Path(p) for p in payload['source_paths']]
    images = [p for p in files if (mimetypes.guess_type(p.name)[0] or '').startswith('image/')]
    videos = [p for p in files if (mimetypes.guess_type(p.name)[0] or '').startswith('video/')]
    audios = [p for p in files if (mimetypes.guess_type(p.name)[0] or '').startswith('audio/')]
    options = payload['options']
    width, height, fps = int(options.get('width', 1080)), int(options.get('height', 1920)), int(options.get('fps', 25))
    width, height = width // 2 * 2, height // 2 * 2
    duration = float(options.get('duration', 10))
    command = [ffmpeg, '-nostdin', '-y']
    if videos:
        command += ['-i', str(videos[0])]
    elif images:
        # Individual inputs avoid concat-file escaping for arbitrary filenames.
        for image in images:
            command += ['-loop', '1', '-t', str(duration / len(images)), '-i', str(image)]
    else:
        raise ValueError('合成需要图片或视频素材')
    audio_index = 1 if videos else len(images)
    for audio in audios[:2]:
        command += ['-i', str(audio)]
    filters = []
    count = 1 if videos else len(images)
    for i in range(count):
        filters.append(f'[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]')
    if count > 1:
        filters.append(''.join(f'[v{i}]' for i in range(count)) + f'concat=n={count}:v=1:a=0[video]')
        video_label = '[video]'
    else:
        video_label = '[v0]'
    if len(audios) >= 2:
        filters += [f'[{audio_index+1}:a]volume=0.2[bg]', f'[{audio_index}:a][bg]amix=inputs=2:duration=longest[audio]']
    command += ['-filter_complex', ';'.join(filters), '-map', video_label]
    if audios:
        command += ['-map', '[audio]' if len(audios) >= 2 else f'{audio_index}:a', '-c:a', 'aac']
    command += ['-t', str(duration), '-c:v', 'libx264', '-preset', 'fast', '-movflags', '+faststart', str(output)]
    completed = subprocess.run(command, capture_output=True, timeout=1800, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if completed.returncode:
        raise RuntimeError('视频合成失败，请检查素材格式')


def transcribe(payload, output):
    config, env = payload['config'], payload['env']
    source = pathlib.Path(payload['source_paths'][0])
    if config['provider'] == 'local':
        model_path = pathlib.Path(env['WHISPER_MODEL'])
        if not model_path.is_dir():
            raise ValueError('本机转写模型尚未安装')
        from faster_whisper import WhisperModel
        model = WhisperModel(str(model_path), device='cpu', compute_type='int8', local_files_only=True)
        segments, info = model.transcribe(str(source))
        segments = list(segments)
        output.write_text('\n'.join(s.text for s in segments), encoding='utf-8')
        subtitle = output.with_suffix('.srt')
        def timecode(seconds):
            millis = int(seconds * 1000)
            return f'{millis//3600000:02}:{millis//60000%60:02}:{millis//1000%60:02},{millis%1000:03}'
        subtitle.write_text('\n\n'.join(f'{i+1}\n{timecode(s.start)} --> {timecode(s.end)}\n{s.text}' for i, s in enumerate(segments)), encoding='utf-8')
    else:
        import httpx
        # Explicit single attempt. httpx does not retry POST by default.
        with source.open('rb') as file, httpx.Client(timeout=300, follow_redirects=False) as client:
            result = client.post(env['TRANSCRIBE_BASE_URL'].rstrip('/') + '/audio/transcriptions',
                                 headers={'Authorization': 'Bearer ' + env['TRANSCRIBE_API_KEY']},
                                 data={'model': env['TRANSCRIBE_MODEL']}, files={'file': (source.name, file, mimetypes.guess_type(source.name)[0] or 'application/octet-stream')})
        result.raise_for_status()
        value = result.json()
        if not isinstance(value.get('text'), str):
            raise RuntimeError('转写接口没有返回正文')
        output.write_text(value['text'], encoding='utf-8')


def main():
    payload = json.load(sys.stdin)
    directory = pathlib.Path(payload['directory']).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    outputs = directory / 'outputs' / payload['id']
    outputs.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / 'receipt.json'
    receipt = {'job_id': payload['id'], 'fingerprint': payload['fingerprint'], 'status': 'unknown', 'send_state': 'not_sent', 'outputs': [], 'tool_events': [], 'upstream_task_id': None}
    if payload.get('mode')=='reconcile':
        previous=json.loads(receipt_path.read_text(encoding='utf-8'))
        if previous.get('job_id')!=payload['id'] or previous.get('fingerprint')!=payload['fingerprint']:raise ValueError('原任务回执身份不符')
        receipt=previous;receipt['outputs']=[]
    from easel_workbench.runtime.distribution_runtime import process_identity
    receipt.update(worker_pid=os.getpid(),worker_identity=process_identity(os.getpid()))
    atomic(receipt_path, receipt)
    env = safe_env(payload['env'], directory)
    if payload.get('tool_bin'):env['PATH']=payload['tool_bin']+os.pathsep+env.get('PATH','')
    os.environ.clear()
    os.environ.update(env)
    os.chdir(directory)
    (directory / '.env').write_text('', encoding='utf-8')
    source = pathlib.Path(__file__).resolve().parent / 'vendor/easel/scripts'
    sys.path.insert(0, str(source))
    original = urllib.request.OpenerDirector.open

    def tracked_open(opener, fullurl, data=None, timeout=None):
        request = fullurl if isinstance(fullurl, urllib.request.Request) else urllib.request.Request(fullurl, data=data)
        url = urllib.parse.urlsplit(request.full_url)
        body = request.data or data or b''
        event = {'tool': 'http', 'method': request.get_method(), 'host': url.hostname, 'path': url.path,
                 'input_sha256': hashlib.sha256(body).hexdigest(), 'state': 'dispatching'}
        receipt['tool_events'].append(event)
        query=urllib.parse.parse_qsl(url.query)
        if event['method']=='GET' and receipt.get('upstream_task_id') and str(receipt['upstream_task_id']) in urllib.parse.unquote(request.full_url) and not any(k.lower() in ('key','api_key','token','access_token','secret') for k,v in query):
            receipt['_poll_url']=request.full_url
        if event['method'] not in ('GET', 'HEAD'):
            receipt['send_state'] = 'unknown'
        atomic(receipt_path, receipt)
        response = original(opener, fullurl, data, timeout) if timeout is not None else original(opener, fullurl, data)
        event['http_status'] = response.status
        event['state'] = 'responded'
        if event['method'] not in ('GET','HEAD'):receipt['send_state']='submitted'
        if 'json' in response.headers.get('Content-Type', ''):
            raw = response.read(20 * 1024 * 1024)
            event['output_sha256'] = hashlib.sha256(raw).hexdigest()
            try:
                value = json.loads(raw)
                def find_task(value):
                    if isinstance(value, dict):
                        for key in ('task_id', 'taskId', 'prediction_id'):
                            if value.get(key):
                                return str(value[key])
                        for v in value.values():
                            found = find_task(v)
                            if found:
                                return found
                    if isinstance(value, list):
                        for v in value:
                            found = find_task(v)
                            if found:
                                return found
                receipt['upstream_task_id'] = find_task(value) or (str(value['id']) if payload['stage'] in ('video','music') and isinstance(value,dict) and isinstance(value.get('id'),str) else None) or receipt['upstream_task_id']
                if isinstance(value, dict) and isinstance(value.get('usage'), dict):
                    receipt['usage'] = value['usage']
            except (ValueError, TypeError):
                pass
            # Preserve the response context-manager protocol expected by urllib.
            response.fp = io.BytesIO(raw)
            response.read = response.fp.read
        atomic(receipt_path, receipt)
        return response

    urllib.request.OpenerDirector.open = tracked_open
    try:
        stage, options = payload['stage'], payload['options']
        output = outputs / ('成品' + {'speech': '.mp3', 'image': '.png', 'video': '.mp4', 'music': '.mp3', 'transcribe': '.txt', 'compose': '.mp4'}[stage])
        if payload.get('mode')=='reconcile':
            read_only_reconcile(payload,receipt,output)
        elif stage == 'speech':
            args = ['clone', '--provider', payload['config']['provider'], '--text', payload['prompt'], '-o', output]
            if options.get('voice_id'):
                args += ['--voice-id', options['voice_id']]
            run_vendor('voice_clone', args, source)
        elif stage == 'image':
            images = list(dict.fromkeys([p for p in payload['source_paths'] if (mimetypes.guess_type(p)[0] or '').startswith('image/')]+payload.get('reference_paths',[])))
            args = ['img2img' if images else 'text2img', '--prompt', payload['instruction'], '-o', output]
            if images:
                args += ['--image', images[0]]
            if options.get('size'):
                args += ['--size', options['size']]
            if options.get('mode') in ('sync', 'async'):
                args += ['--mode', options['mode']]
            run_vendor('ai_image', args, source,images)
        elif stage == 'video':
            images = [p for p in payload['source_paths'] if (mimetypes.guess_type(p)[0] or '').startswith('image/')]
            args = ['image2video' if images else 'text2video', '--provider', payload['config']['provider'], '--prompt', payload['instruction'], '-o', output]
            if images:
                args += ['--image', images[0]]
            if options.get('duration'):
                args += ['--duration', int(options['duration'])]
            run_vendor('ai_video', args, source)
        elif stage == 'music':
            args = ['generate', '--provider', payload['config']['provider'], '--prompt', payload['instruction'], '--instrumental', '-o', output]
            if options.get('duration'):
                args += ['--duration', int(options['duration'])]
            run_vendor('ai_music', args, source)
        elif stage == 'transcribe':
            # httpx transcription has a conservative dispatch fence too.
            if payload['config']['provider'] != 'local':
                receipt['send_state'] = 'unknown'
                atomic(receipt_path, receipt)
            transcribe(payload, output)
        else:
            compose(payload, output)
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError('媒体工具没有交付实际文件')
        if stage=='image':
            from PIL import Image
            with Image.open(output) as actual:
                actual.load()
                extension={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}.get(actual.format)
            if not extension:raise ValueError('未交付可支持的图片格式')
            if output.suffix!=extension:
                renamed=output.with_suffix(extension);output.rename(renamed);output=renamed
        if stage in ('speech','music'):
            with output.open('rb') as stream:header=stream.read(32)
            if header.startswith(b'RIFF') and header[8:12]==b'WAVE':
                renamed=output.with_suffix('.wav');output.rename(renamed);output=renamed
            elif not (header.startswith(b'ID3') or header[:1]==b'\xff' or b'ftyp' in header):
                raise ValueError('未交付可识别的音频文件')
        if stage in ('video','compose'):
            with output.open('rb') as stream:header=stream.read(32)
            if not (b'ftyp' in header or header.startswith(b'\x1aE\xdf\xa3')):raise ValueError('未交付可识别的视频文件')
        for path in sorted(outputs.iterdir()):
            if path.is_file() and not path.is_symlink() and path.stat().st_size:
                meta = {'path': str(path.relative_to(directory)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'role': 'final' if path == output else 'intermediate'}
                ffprobe = shutil.which('ffprobe')
                if ffprobe and (mimetypes.guess_type(path.name)[0] or '').startswith(('audio/', 'video/')):
                    probe = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
                    if probe.returncode == 0:
                        with contextlib.suppress(ValueError, KeyError, TypeError):
                            meta['duration_ms'] = int(float(json.loads(probe.stdout)['format']['duration']) * 1000)
                receipt['outputs'].append(meta)
        receipt.update(status='completed', send_state='submitted')
    except TaskPending:
        receipt.update(status='unknown',error='上游原任务尚未取得成品；保留任务身份，不重新生成')
    except Exception:
        receipt.update(status='failed' if receipt.get('provider_failed') else 'unknown' if receipt['send_state'] == 'unknown' or receipt.get('upstream_task_id') else 'failed', error='媒体阶段未取得完整成品，请检查配置、依赖和原任务回执')
    atomic(receipt_path, receipt)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
