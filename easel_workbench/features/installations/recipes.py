"""Existing pinned project-local recipes; no installation or global PATH writes."""
RECIPES = {
    'browser': {'name': '平台连接专用浏览器与二维码识别', 'packages': ['playwright==1.64.1','opencv-python==4.14.0.94','numpy==2.4.6'], 'module': 'playwright', 'group': '平台连接'},
    'biliup': {'name': 'B站扫码登录依赖', 'packages': ['biliup==1.3.4','segno==1.6.6'], 'module': 'biliup', 'group': '平台连接'},
    'ffmpeg': {'name': 'ffmpeg', 'packages': ['imageio-ffmpeg==0.6.0'], 'module': 'imageio_ffmpeg', 'group': 'rm'},
    'fw': {'name': 'faster-whisper', 'packages': ['faster-whisper==1.2.1'], 'module': 'faster_whisper', 'group': 'rm'},
    'model': {'name': 'Whisper large-v3 模型', 'packages': ['huggingface-hub'], 'module': 'huggingface_hub', 'group': 'rm'},
    'rmdeps': {'name': 'Remotion 工程依赖', 'packages': [], 'module': '', 'group': 'rm', 'needs_dir': True},
    'shell': {'name': 'Chrome Headless Shell', 'packages': [], 'module': '', 'group': 'rm', 'needs_dir': True},
    'pylibs': {'name': '常用 Python 库', 'packages': ['Pillow==12.3.0','edge-tts','pdfplumber','requests==2.34.2'], 'module': 'edge_tts', 'group': 'common'},
    'markdown': {'name': '公众号 Markdown 排版', 'packages': ['Markdown==3.11.2'], 'module': 'markdown', 'group': 'common'},
}

BASE_PACKAGES=['httpx==0.28.1','Pillow==12.3.0','requests==2.34.2']
