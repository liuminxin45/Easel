"""Current official media code location; legacy vendor is historical evidence only."""
import hashlib
import json
from pathlib import Path

OFFICIAL_SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/shared/scripts'
MEDIA_FILES = ('model_registry.py','voice_clone.py','ai_image.py','ai_video.py','ai_music.py')


class MediaSourceMismatch(ValueError):
    pass


def media_source():
    files={name:hashlib.sha256((OFFICIAL_SCRIPTS/name).read_bytes()).hexdigest() for name in MEDIA_FILES}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'kind':'official_main_tree','path':'skills/shared/scripts','files':files,'source_tree_sha256':digest}


def require_media_source(payload):
    if payload.get('mode')=='reconcile':return None
    current=media_source()
    if payload.get('source_release')!=current['source_tree_sha256']:
        raise MediaSourceMismatch('原媒体任务的冻结源码缺失或与当前官方实现不符；未发送，不可用新实现重做旧任务。')
    return current
