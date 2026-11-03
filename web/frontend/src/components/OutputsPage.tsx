import DownloadLink from './DownloadLink';
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { fetchOutputs, fetchOutputContent, mediaUrl, deleteOutput } from '../lib/api';
import type { OutputNode, OutputMeta } from '../lib/api';
import { renderMarkdown } from '../lib/sanitize';
import {useStoredViewState,type ViewStateStore} from '../lib/viewState';
import {peekApiData,subscribeApiData} from '../lib/api';
import { IconOutputs, IconImage, IconVideo, IconMusic, IconFile, IconFolder, IconRefresh, IconChevron, IconTrash } from './icons';
import {outputsBrowser,type OutputsDataSource,type OutputsBrowserState} from '../lib/outputBrowser';
export type {OutputsDataSource,OutputsListInput,OutputsListPage} from '../lib/outputBrowser';

const FILTERS: { key: string; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
  { key: 'audio', label: '音频' },
  { key: 'text', label: '文档' },
];

const KIND_LABEL: Record<string, string> = {
  article: '文章', 'xhs-note': '小红书', video: '视频', cards: '卡片',
  poster: '海报', audio: '音频', other: '其他',
};
const STATUS_LABEL: Record<string, string> = { draft: '草稿', ready: '待发', published: '已发' };
const STATUS_COLOR: Record<string, string> = { draft: 'var(--text-tertiary)', ready: 'var(--amber)', published: 'var(--green)' };

const badge: CSSProperties = {
  fontSize: 11, padding: '1px 7px', borderRadius: 999,
  background: 'var(--surface-hover)', color: 'var(--text-secondary)', whiteSpace: 'nowrap',
};
const statusBadge = (s: string): CSSProperties => ({
  ...badge,
  background: `color-mix(in srgb, ${STATUS_COLOR[s] || 'var(--text-tertiary)'} 13%, transparent)`,
  color: STATUS_COLOR[s] || 'var(--text-secondary)',
});

function kindIcon(kind: string | undefined, size = 30) {
  if (kind === 'video') return <IconVideo size={size} />;
  if (kind === 'audio') return <IconMusic size={size} />;
  if (kind === 'image') return <IconImage size={size} />;
  return <IconFile size={size} />;
}
const isHtml = (name: string) => /\.html?$/i.test(name);
const kindLabel = (f: OutputNode) =>
  f.kind === 'text' ? (isHtml(f.name) ? '卡片' : '文档')
    : f.kind === 'image' ? '图片' : f.kind === 'video' ? '视频' : f.kind === 'audio' ? '音频' : '文件';

/** 递归找目录下第一张图/视频作封面缩略图。 */
function firstMedia(node: OutputNode): OutputNode | null {
  if (node.type === 'file') return (node.kind === 'image' || node.kind === 'video') ? node : null;
  for (const c of node.children || []) {
    const m = firstMedia(c);
    if (m) return m;
  }
  return null;
}

/** 展示头声明的封面 → 伪 file 节点（供 Thumb 渲染）。 */
function coverNode(m?: OutputMeta): OutputNode | null {
  if (!m?.cover) return null;
  const kind = /\.(mp4|mov|webm|mkv)$/i.test(m.cover) ? 'video' : 'image';
  return { name: 'cover', type: 'file', path: m.cover, kind } as OutputNode;
}

/** 按节点路径解析目录链；展示名称可以重复或在刷新后改变。 */
function resolvePath(roots: OutputNode[], paths: string[]): OutputNode[] {
  let nodes = roots;
  const directories: OutputNode[] = [];
  for (const path of paths) {
    const found = nodes.find((n) => n.type === 'dir' && n.path === path);
    if (!found) break;   // 路径失效（被删/改）→ 停在能解析到的层
    directories.push(found);
    nodes = found.children || [];
  }
  return directories;
}

function Thumb({ f, big, lazy=false }: { f: OutputNode | null; big?: boolean;lazy?:boolean }) {
  if (f && f.kind === 'image') return <img src={mediaUrl(f.path)} alt="" loading="lazy" />;
  if (f && f.kind === 'video'&&!lazy) return <video src={mediaUrl(f.path)} preload="metadata" muted />;
  return <div className="gcard-ph">{kindIcon(f?.kind, big ? 34 : 30)}</div>;
}

export interface OutputsViewState {stack:string[];filter:string;jumpPath?:string;query?:string}
interface OutputsPageProps {
  /** 从对话跳转进来的目录（outputs 相对路径，不含 outputs/ 前缀）；消费后由父层清空 */
  jumpPath?: string;
  onJumpHandled?: () => void;
  /** Host-owned metadata and lifecycle actions; the native gallery stays shared. */
  renderProjectDetails?: (project: OutputNode) => ReactNode;
  canDelete?: (node: OutputNode) => boolean;
  registerLayer?: (close:()=>void)=>()=>void;
  viewState?:ViewStateStore<OutputsViewState>;
  onContentReady?:()=>void;
  dataSource?:OutputsDataSource;
}

export default function OutputsPage({ jumpPath, onJumpHandled, renderProjectDetails, canDelete = () => true, registerLayer,viewState,onContentReady,dataSource }: OutputsPageProps) {
  const [roots, setRoots] = useState<OutputNode[]>(()=>dataSource?[]:peekApiData<OutputNode[]>('/api/outputs')??[]);
  const [legacyTreeError, setTreeError] = useState('');
  const [legacyTreeLoading, setTreeLoading] = useState(()=>!dataSource&&peekApiData('/api/outputs')===undefined);
  const treeSeq = useRef(0);
  const jumpSeq = useRef(0);
  const [view,setView]=useStoredViewState<OutputsViewState>(viewState,()=>({stack:[] as string[],filter:'all'}));
  const stack=view.stack,filter=view.filter;
  const browser=useMemo(()=>dataSource?outputsBrowser(dataSource):null,[dataSource]);
  const [lazy,setLazy]=useState<OutputsBrowserState|null>(()=>browser?.snapshot()??null),[query,setQuery]=useState(view.query||''),[jumpError,setJumpError]=useState('');
  const parent=stack.at(-1)||'',kind=filter==='all'?undefined:filter,listKey=JSON.stringify([parent,query,kind||'']);
  const lazyCurrent=lazy?.key===listKey?lazy:null;
  const lazySeed=dataSource?.peek?.({parent:parent||undefined,query:query||undefined,kind});
  const treeError=dataSource?(jumpError||lazyCurrent?.error||''):legacyTreeError,treeLoading=dataSource?!!lazyCurrent?.loading||!lazyCurrent&&!lazySeed:legacyTreeLoading;
  const setFilter=(filter:string)=>setView(previous=>({...previous,filter}));
  const [selected, setSelected] = useState<OutputNode | null>(null);
  const [content, setContent] = useState('');
  const [contentError,setContentError]=useState('');
  const [loading, setLoading] = useState(false);
  const reqSeq = useRef(0);
  useEffect(()=>{
    if(!selected)return;
    const close=()=>setSelected(null),release=registerLayer?.(close);
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();close()}};
    document.addEventListener('keydown',escape);
    return()=>{release?.();document.removeEventListener('keydown',escape)};
  },[selected?.path,registerLayer]);

  useEffect(()=>{if(!browser)return;setLazy(browser.snapshot());return browser.subscribe(()=>setLazy(browser.snapshot()))},[browser]);
  useEffect(()=>{if(!dataSource)return;const timer=setTimeout(()=>setQuery((view.query||'').trim()),250);return()=>clearTimeout(timer)},[dataSource,view.query]);
  const load = useCallback((force=false) => {
    if(browser){setJumpError('');void browser.select({parent:parent||undefined,query:query||undefined,kind},stack,force);return;}
    const seq = ++treeSeq.current;
    setTreeError('');
    setTreeLoading(peekApiData('/api/outputs')===undefined);
    fetchOutputs(force).then((data) => { if (seq === treeSeq.current) setRoots(data); })
      .catch((error: unknown) => { if (seq === treeSeq.current) setTreeError(error instanceof Error ? error.message : '加载产物列表失败'); })
      .finally(() => { if (seq === treeSeq.current) setTreeLoading(false); });
  }, [browser,browser?parent:'',browser?kind:undefined,browser?query:'',browser?stack:undefined]);
  useEffect(() => { load(); }, [load]);
  useEffect(()=>{if(dataSource)return;return subscribeApiData<OutputNode[]>('/api/outputs',value=>{setRoots(value);setTreeError('');setTreeLoading(false)},error=>setTreeError(error.message))},[dataSource]);
  useEffect(()=>{if(dataSource||!treeLoading&&!treeError)onContentReady?.()},[dataSource,treeLoading,treeError,roots,onContentReady]);
  useEffect(()=>()=>browser?.cancel(),[browser]);
  useEffect(()=>{if(!browser||!lazyCurrent?.indexing)return;let timer:ReturnType<typeof setTimeout>|undefined;const refresh=()=>{if(typeof document==='undefined'||!document.hidden)load(true)};timer=setTimeout(refresh,2000);document.addEventListener('visibilitychange',refresh);return()=>{if(timer)clearTimeout(timer);document.removeEventListener('visibilitychange',refresh)}},[browser,lazyCurrent,load]);

  const directories = useMemo(() => browser?browser.directoryNodes(stack):resolvePath(roots, stack), [browser,lazy,roots,stack]);
  const currentNodes = dataSource?(lazyCurrent?.items||lazySeed?.items||[]):directories.length ? directories[directories.length - 1].children || [] : roots;
  const dirs = useMemo(
    () => currentNodes.filter((n) => n.type === 'dir').sort((a, b) => (b.mtime || 0) - (a.mtime || 0)),
    [currentNodes]);
  const files = useMemo(() => {
    const fs = currentNodes.filter((n) => n.type === 'file').sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
    return filter === 'all' ? fs : fs.filter((f) => f.kind === filter);
  }, [currentNodes, filter]);

  const selectedProject = useMemo(() => {
    let selected: OutputNode | undefined;
    for (const node of directories) {
      if (node.meta) selected = node;
    }
    return selected;
  }, [directories]);

  const atTop = directories.length === 0;
  const atProjectRoot = directories.length === 1;
  // 当前项目的展示头（进入项目后才有），用于「成品/素材」分区
  const projectMeta = useMemo(
    () => selectedProject?.meta,
    [selectedProject]);
  const deliverableSet = useMemo(
    () => new Set(projectMeta?.deliverablePaths || []),
    [projectMeta, atProjectRoot]);
  const hasSplit = deliverableSet.size > 0;
  const deliverableFiles = useMemo(
    () => (hasSplit ? files.filter((f) => deliverableSet.has(f.path)) : []),
    [files, deliverableSet, hasSplit]);
  const restFiles = useMemo(
    () => (hasSplit ? files.filter((f) => !deliverableSet.has(f.path)) : files),
    [files, deliverableSet, hasSplit]);

  const enterDir = useCallback((path: string) => { jumpSeq.current++;if(dataSource)setQuery('');setView(previous=>({...previous,stack:[...(dataSource?stack:directories.map(node => node.path)),path],filter:'all',...(dataSource?{query:'',...(jumpPath?{jumpPath}:{})}:{})})); }, [dataSource,stack,directories,jumpPath,setView]);
  const goTo = useCallback((depth: number) => { jumpSeq.current++;if(dataSource)setQuery('');setView(previous=>({...previous,stack:previous.stack.slice(0,depth),filter:'all',...(dataSource?{query:'',...(jumpPath?{jumpPath}:{})}:{})})); }, [dataSource,jumpPath,setView]);

  const remove = useCallback(async (node: OutputNode, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!canDelete(node)) return;
    const isDir = node.type === 'dir';
    const label = isDir ? `项目/文件夹「${node.meta?.title || node.name}」及其全部内容` : `文件「${node.name}」`;
    if (!window.confirm(`确定删除${label}？\n此操作不可恢复。`)) return;
    try {
      await deleteOutput(node.path);
      setSelected((cur) => (cur?.path === node.path ? null : cur));
      load(true);
    } catch (err) {
      alert((err as Error).message || '删除失败');
    }
  }, [load, canDelete]);

  const open = useCallback(async (f: OutputNode,force=false) => {
    const seq = ++reqSeq.current;
    setSelected(f); setContent('');setContentError('');
    if (f.kind === 'text' && !isHtml(f.name)) {
      setLoading(true);
      try {
        const res = await fetchOutputContent(f.path,force);
        if (seq === reqSeq.current) setContent(res.isBinary ? '' : res.content);
      } catch(error){if(seq===reqSeq.current)setContentError(error instanceof Error?error.message:'正文读取失败，请重试。')}finally { if (seq === reqSeq.current) setLoading(false); }
    }
  }, []);
  useEffect(()=>{
    if(!selected||selected.kind!=='text'||isHtml(selected.name))return;
    const path='/api/output/'+selected.path.split('/').map(encodeURIComponent).join('/');
    return subscribeApiData<Awaited<ReturnType<typeof fetchOutputContent>>>(path,value=>{setContent(value.isBinary?'':value.content);setContentError('');setLoading(false)},error=>{setContentError(error.message);setLoading(false)});
  },[selected?.path]);

  // Resolve the declared path, which may differ from a virtual node's display name.
  useEffect(() => {
    if (!jumpPath || view.jumpPath===jumpPath) return;
    if(browser){let cancelled=false;const sequence=++jumpSeq.current;setJumpError('');void browser.resolve(jumpPath).then(nodes=>{if(cancelled||sequence!==jumpSeq.current)return;const node=nodes.at(-1);if(!node)throw Error('此内容暂不可用，请刷新列表后重试。');setQuery('');setView(previous=>({...previous,stack:nodes.filter(value=>value.type==='dir').map(value=>value.path),filter:'all',query:'',jumpPath}));if(node.type==='file')void open(node);else setSelected(null);onJumpHandled?.()}).catch(error=>{if(!cancelled&&sequence===jumpSeq.current)setJumpError(error instanceof Error?error.message:'内容位置读取失败，请重试。')});return()=>{cancelled=true};}
    if(roots.length===0)return;
    const wanted = jumpPath.split('/').filter(Boolean).join('/');
    const find = (nodes: OutputNode[], parents: string[]): {node: OutputNode; parents: string[]} | undefined => {
      for (const node of nodes) {
        const path = node.type === 'dir' ? [...parents, node.path] : parents;
        if (node.path === wanted) return {node, parents: path};
        if (node.type === 'dir') {
          const match = find(node.children || [], path);
          if (match) return match;
        }
      }
      return undefined;
    };
    const found = find(roots, []);
    if (found) {
      setView(previous=>({...previous,stack:found.parents,filter:'all',jumpPath}));
      if (found.node.type === 'file') void open(found.node);
      else setSelected(null);
    }
    onJumpHandled?.();
  }, [browser,jumpPath, roots, open, onJumpHandled,view.jumpPath,setView]);

  const preview = () => {
    if (!selected) return null;
    const url = mediaUrl(selected.path);
    if (selected.kind === 'image') return <><img src={url} alt={selected.name} style={{ maxWidth: '100%', borderRadius: 'var(--radius)' }} /><DownloadLink href={url} download={selected.name}>下载原图</DownloadLink></>;
    if (selected.kind === 'video') return <><video src={url} controls style={{ maxWidth: '100%', borderRadius: 'var(--radius)' }} /><DownloadLink href={url} download={selected.name}>下载原件</DownloadLink></>;
    if (selected.kind === 'audio') return <><audio src={url} controls style={{ width: '100%' }} /><DownloadLink href={url} download={selected.name}>下载原件</DownloadLink></>;
    if (selected.kind === 'text' && isHtml(selected.name)) return (
      <>
        {/* allow-scripts：让预览页自带的「复制到公众号」按钮(execCommand('copy'))能运行；
            allow="clipboard-write"：授予剪贴板写权限。不给 allow-same-origin —— iframe 保持
            opaque origin，脚本跑得起来但访问不到本站，安全。(修复：内嵌预览里复制按钮点了没反应) */}
        <iframe src={`${url}?v=${selected.mtime ?? 0}`} title={selected.name} sandbox="allow-scripts" allow="clipboard-write"
          style={{ width: '100%', height: '68vh', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: '#fff' }} />
        <DownloadLink href={url} download={selected.name}>下载原件</DownloadLink><div style={{ marginTop: 8 }}><a href={url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-start)', fontSize: 13 }}>在新标签打开 ↗</a></div>
      </>
    );
    if (selected.kind === 'text') {
      if (loading) return <div className="loading"><div className="spinner" />加载中…</div>;
      return <>{contentError&&<div className="notice-error" role="alert">{contentError} <button className="btn btn-sm" onClick={()=>open(selected,true)}>重试预览</button></div>}<div className="outputs-viewer-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} /><DownloadLink href={url} download={selected.name}>下载原件</DownloadLink></>;
    }
    return <div style={{ color: 'var(--text-secondary)', fontSize: 14 }}>无法预览。<DownloadLink href={url} download={selected.name} style={{ color: 'var(--accent-start)' }}>下载 {selected.name}</DownloadLink></div>;
  };

  /** 项目/文件夹卡片：顶层项目用展示头（标题/平台/状态/封面），嵌套子文件夹回退朴素样式。 */
  const renderDir = (d: OutputNode) => {
    const m = d.meta;
    const cover = coverNode(m) || (dataSource?null:firstMedia(d));
    return (
      <div key={d.path} className="card card-hover gcard" onClick={() => enterDir(d.path)}>
        <div className="gcard-thumb">
          <span className="gcard-kind">{m?.kind ? (KIND_LABEL[m.kind] || m.kind) : '文件夹'}</span>
          {canDelete(d) && <button className="gcard-del" title="删除" onClick={(e) => remove(d, e)}><IconTrash size={14} /></button>}
          {cover ? <Thumb f={cover} big lazy={!!dataSource} /> : <div className="gcard-ph"><IconFolder size={38} /></div>}
        </div>
        <div className="gcard-meta">
          <div className="gcard-name" title={m?.title || d.name}>
            {!m && <IconFolder size={13} />} {m?.title || d.name}
          </div>
          <div className="gcard-sub" style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {m?.platform && <span style={badge}>{m.platform}</span>}
            {m?.status && <span style={statusBadge(m.status)}>{STATUS_LABEL[m.status] || m.status}</span>}
            <span>{d.fileCount ?? 0} 个文件</span>
          </div>
        </div>
      </div>
    );
  };

  const renderFile = (f: OutputNode) => (
    <div key={f.path} className="card card-hover gcard" onClick={() => open(f)}>
      <div className="gcard-thumb">
        <span className="gcard-kind">{kindLabel(f)}</span>
        {canDelete(f) && <button className="gcard-del" title="删除" onClick={(e) => remove(f, e)}><IconTrash size={14} /></button>}
        <Thumb f={dataSource?(coverNode(f.meta)||f):f} lazy={!!dataSource} />
      </div>
      <div className="gcard-meta">
        <div className="gcard-name" title={f.name}>{f.name}</div>
      </div>
    </div>
  );

  const empty = dirs.length === 0 && files.length === 0;

  return (
    <div className="gallery-page">
      <div className="gallery-head">
        <div>
          <h1 className="page-title">内容库</h1>
          {stack.length > 0 && <nav className="gallery-breadcrumb" aria-label="内容库路径">
            <button className="crumb" onClick={() => goTo(0)}>内容库</button>
            {directories.map((node, i) => (
              <span key={node.path}>
                <span className="crumb-sep">/</span>
                {i === directories.length - 1
                  ? (projectMeta?.title && i === 0 ? projectMeta.title : node.name)
                  : <button className="crumb" onClick={() => goTo(i + 1)}>{node.name}</button>}
              </span>
            ))}
          </nav>}
          <p className="page-subtitle">
            {treeLoading && currentNodes.length === 0 || lazyCurrent?.indexing ? '正在读取项目与素材…' : treeError && currentNodes.length === 0 ? '项目数量暂未取得' : dataSource&&atTop
              ? `已加载 ${currentNodes.length} 个项目。点项目进去看成品与素材。` : atTop
              ? `按项目归档，共 ${roots.length} 个项目。点项目进去看成品与素材。`
              : `${dirs.length} 个文件夹 · ${files.length} 个文件（可继续点开子文件夹）`}
          </p>
        </div>
        <button className="btn btn-sm" onClick={()=>load(true)} disabled={treeLoading}><IconRefresh size={14} /> {treeLoading ? '读取中…' : '刷新'}</button>
      </div>

      {dataSource&&<div className="gallery-filters"><input className="field" type="search" aria-label="搜索内容" placeholder="搜索内容" value={view.query||''} maxLength={200} onChange={event=>setView(previous=>({...previous,query:event.target.value}))}/></div>}

      {selectedProject && renderProjectDetails?.(selectedProject)}

      {treeError && <div className="notice-error" role="alert">内容读取失败：{treeError} <button className="btn btn-sm" onClick={()=>load(true)}>重试</button></div>}
      {(treeLoading||lazyCurrent?.indexing) && currentNodes.length === 0 && <div className="loading" role="status">正在读取内容库…</div>}

      {/* 项目主题标签（进入项目根时展示） */}
      {atProjectRoot && projectMeta?.tags && projectMeta.tags.length > 0 && (
        <div className="gallery-filters" style={{ marginBottom: 4 }}>
          {projectMeta.tags.map((t) => <span key={t} style={badge}>#{t}</span>)}
        </div>
      )}

      {/* 面包屑返回 + 文件过滤（进入任意层后显示） */}
      {directories.length > 0 && (
        <div className="gallery-filters">
          <button className="btn btn-sm" onClick={() => goTo(directories.length - 1)}>
            <span style={{ transform: 'rotate(180deg)', display: 'inline-flex' }}><IconChevron size={13} /></span> 返回上级
          </button>
          {(files.length > 0||dataSource) && FILTERS.map((f) => (
            <button key={f.key} className={`chip ${filter === f.key ? 'active' : ''}`} onClick={() => setFilter(f.key)}>{f.label}</button>
          ))}
        </div>
      )}

      {empty && !treeError && !treeLoading && !lazyCurrent?.indexing ? (
        <div className="empty-state" style={{ height: 300 }}>
          <div className="empty-icon"><IconOutputs size={44} /></div>
          <p>{atTop ? '还没有产物——去对话或技能库生成第一条内容吧' : '这个文件夹是空的'}</p>
        </div>
      ) : hasSplit ? (
        <>
          {/* 成品区 */}
          {deliverableFiles.length > 0 && (
            <>
              <div className="section-label" style={{ margin: '6px 0 8px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
                成品 · {deliverableFiles.length}
              </div>
              <div className="gallery-grid">{deliverableFiles.map(renderFile)}</div>
            </>
          )}
          {/* 素材 / 过程文件区 */}
          {(dirs.length > 0 || restFiles.length > 0) && (
            <>
              <div className="section-label" style={{ margin: '18px 0 8px', fontSize: 13, fontWeight: 600, color: 'var(--text-tertiary)' }}>
                素材 / 过程文件
              </div>
              <div className="gallery-grid">
                {dirs.map(renderDir)}
                {restFiles.map(renderFile)}
              </div>
            </>
          )}
        </>
      ) : (
        <div className="gallery-grid">
          {dirs.map(renderDir)}
          {files.map(renderFile)}
        </div>
      )}

      {dataSource&&lazyCurrent?.next_cursor&&<button className="btn" disabled={lazyCurrent.loadingMore} onClick={()=>void browser?.more()}>{lazyCurrent.loadingMore?'正在读取…':'加载更多'}</button>}

      {selected && (
        <div className="drawer-overlay" onClick={() => setSelected(null)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ minWidth: 0 }}>
                <div className="skill-detail-title" style={{ fontSize: 16 }}>{selected.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 3, fontFamily: "'SF Mono','Consolas',monospace" }}>{selected.path}</div>
              </div>
              <button className="icon-btn" aria-label="关闭预览" onClick={() => setSelected(null)}>×</button>
            </div>
            <div className="drawer-body">{preview()}</div>
            {canDelete(selected) && <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
              <button className="btn btn-sm btn-danger" onClick={(e) => remove(selected, e)}><IconTrash size={13} /> 删除此文件</button>
            </div>}
          </div>
        </div>
      )}
    </div>
  );
}
