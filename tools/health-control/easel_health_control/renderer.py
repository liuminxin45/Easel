"""Workspace-local PNG tool for the real canary Agent; staging never invokes a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stage_runtime(python_executable, workspace):
    """Copy installed interpreter code, not its venv redirector or user settings."""
    workspace=Path(workspace).resolve();workspace.mkdir(parents=True,exist_ok=True)
    executable=Path(python_executable).resolve()
    cfg=executable.parent.parent/'pyvenv.cfg'
    base=executable.parent
    if cfg.is_file():
        lines={key.strip():value.strip() for line in cfg.read_text(encoding='utf-8').splitlines() if '=' in line for key,value in [line.split('=',1)]}
        home=lines.get('home','').strip()
        if not home:raise ValueError('renderer_python_base_missing')
        base=Path(home).resolve()
    libraries=sorted(p for p in base.glob('python*.dll') if re.fullmatch(r'python[0-9]{2,3}\.dll',p.name))
    if len(libraries)!=1 or not (base/'python.exe').is_file() or not (base/'Lib').is_dir():raise ValueError('renderer_requires_installed_windows_cpython')
    site=executable.parent.parent/'Lib/site-packages' if cfg.is_file() else base/'Lib/site-packages'
    if not (site/'PIL/Image.py').is_file():raise ValueError('renderer_pillow_not_installed')
    parent=workspace/'.tools';parent.mkdir(exist_ok=True)
    if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():raise ValueError('linked_renderer_root')
    target=parent/'renderer-python'
    if target.exists():
        manifest=json.loads((target/'renderer-manifest.json').read_text(encoding='utf-8'))
        if manifest.get('renderer_source_sha256')!=sha(__file__):raise ValueError('renderer_runtime_version_changed')
        for name,digest in manifest['files'].items():
            path=target/name
            if path.is_symlink() or not path.resolve().is_relative_to(target) or sha(path)!=digest:raise ValueError('renderer_runtime_changed')
        return {**manifest,'python':str(target/'python.exe'),'renderer':str(target/'renderer.py')}
    temporary=parent/('.renderer-'+uuid.uuid4().hex);temporary.mkdir()
    excluded={'__pycache__','site-packages','test','tests','idlelib','tkinter','turtledemo','ensurepip'}
    def copy_tree(source,destination):
        for directory,dirs,files in os.walk(source):
            dirs[:]=[d for d in dirs if d not in excluded]
            current=Path(directory)
            if current.is_symlink() or getattr(current,'is_junction',lambda:False)():raise ValueError('linked_renderer_source')
            for name in files:
                path=current/name
                if path.is_symlink() or path.suffix in ('.pyc','.pyo','.pdb'):continue
                out=destination/path.relative_to(source);out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,out)
    try:
        for path in [base/'python.exe',*base.glob('python*.dll'),*base.glob('vcruntime*.dll'),base/'LICENSE.txt']:
            if path.is_file():shutil.copyfile(path,temporary/path.name)
        copy_tree(base/'Lib',temporary/'Lib')
        copy_tree(base/'DLLs',temporary/'DLLs')
        copy_tree(site/'PIL',temporary/'Lib/site-packages/PIL')
        for directory in site.glob('pillow*.libs'):
            if directory.is_dir():copy_tree(directory,temporary/'Lib/site-packages'/directory.name)
        # _pth ignores ambient PYTHONHOME/PYTHONPATH and prevents a fallback to
        # the inaccessible AppData base interpreter or unrelated user packages.
        (temporary/(libraries[0].stem+'._pth')).write_text('.\nLib\nDLLs\nLib/site-packages\nimport site\n',encoding='utf-8')
        shutil.copyfile(__file__,temporary/'renderer.py')
        fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        font=next((fonts/name for name in ['msyh.ttc','simhei.ttf','simsun.ttc'] if (fonts/name).is_file()),None)
        if font is None:raise ValueError('renderer_chinese_font_missing')
        (temporary/'fonts').mkdir();shutil.copyfile(font,temporary/'fonts'/font.name)
        files={p.relative_to(temporary).as_posix():sha(p) for p in temporary.rglob('*') if p.is_file()}
        manifest={'schema':1,'renderer_source_sha256':sha(__file__),'source_python':str(executable),'base_python':str(base/'python.exe'),
                  'files':files,'bytes':sum((temporary/name).stat().st_size for name in files),'font':'fonts/'+font.name}
        (temporary/'renderer-manifest.json').write_text(json.dumps(manifest,sort_keys=True),encoding='utf-8')
        temporary.rename(target)
        return {**manifest,'python':str(target/'python.exe'),'renderer':str(target/'renderer.py')}
    except BaseException:
        # Only this invocation's checked workspace child is removed.
        resolved_temporary=temporary.resolve();resolved_parent=parent.resolve()
        if (resolved_temporary!=resolved_parent and resolved_temporary.is_relative_to(resolved_parent)
                and temporary.name.startswith('.renderer-')):shutil.rmtree(temporary,ignore_errors=True)
        raise


def render(payload,output,root):
    from PIL import Image,ImageDraw,ImageFont
    from PIL.PngImagePlugin import PngInfo
    root=Path(root).resolve();output=Path(output).resolve()
    if not output.is_relative_to(root/'outputs'):raise ValueError('renderer_output_outside_workspace_outputs')
    operation=payload.get('operation_id')
    if not isinstance(operation,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',operation):raise ValueError('renderer_operation_missing')
    title=payload.get('title','');body=payload.get('body','')
    if not isinstance(title,str) or not 1<=len(title)<=160 or not isinstance(body,str) or not 1<=len(body)<=1000:raise ValueError('renderer_text_invalid')
    font_root=Path(__file__).resolve().parent/'fonts'
    font=next(iter(font_root.glob('*')),None)
    if font is None:
        fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        font=next((fonts/name for name in ['msyh.ttc','simhei.ttf','simsun.ttc'] if (fonts/name).is_file()),None)
    if font is None:raise ValueError('renderer_chinese_font_missing')
    image=Image.new('RGB',(960,1280),'#f4f1e9');draw=ImageDraw.Draw(image)
    title_font=ImageFont.truetype(str(font),52);body_font=ImageFont.truetype(str(font),32);small=ImageFont.truetype(str(font),22)
    draw.rectangle((56,58,72,116),fill='#168b86');draw.text((94,70),'热点信息图 · 来源快照',font=small,fill='#365453')
    def lines(text,font,width):
        result=[]
        for paragraph in text.splitlines():
            line=''
            for character in paragraph:
                if line and draw.textlength(line+character,font=font)>width:result.append(line);line=''
                line+=character
            result.append(line)
        return result
    y=158
    for line in lines(title,title_font,832):
        if y>480:raise ValueError('renderer_title_exceeds_layout')
        draw.text((64,y),line,font=title_font,fill='#142d33');y+=76
    y+=30;draw.line((64,y,896,y),fill='#168b86',width=3);y+=45
    for line in lines(body,body_font,832):
        if y>1070:raise ValueError('renderer_body_exceeds_layout')
        draw.text((64,y),line,font=body_font,fill='#263a40');y+=51
    source=str(payload.get('source_url',''))[:180]
    for number,line in enumerate(lines(source,small,832)[:3]):
        draw.text((64,1130+number*24),line,font=small,fill='#52676b')
    draw.text((64,1210),'隔离验收候选 · 未采纳 · 未发布',font=small,fill='#52676b')
    info=PngInfo();info.add_text('easel_canary_operation',operation)
    info.add_text('source_url',source);info.add_text('renderer','native-agent-local-tool')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name('.'+output.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        image.save(temporary,format='PNG',pnginfo=info)
        os.link(temporary,output)  # Atomic create; never replaces an earlier artifact.
    finally:temporary.unlink(missing_ok=True)
    return {'path':str(output),'sha256':sha(output),'width':960,'height':1280,'operation_id':operation}


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--stage-python');parser.add_argument('--workspace')
    parser.add_argument('--input');parser.add_argument('--output');args=parser.parse_args(argv)
    if args.stage_python:
        result=stage_runtime(args.stage_python,args.workspace)
        print(json.dumps({key:result[key] for key in ['python','renderer','font','bytes']},ensure_ascii=True));return 0
    if not args.input or not args.output or not args.workspace:parser.error('render requires --input --output --workspace')
    result=render(json.loads(Path(args.input).read_text(encoding='utf-8')),args.output,args.workspace)
    print(json.dumps(result,ensure_ascii=True));return 0


if __name__=='__main__':raise SystemExit(main())
