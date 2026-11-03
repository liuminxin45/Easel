import { Component, useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { fetchTrendSources, fetchTrends, createIdea,peekApiData,subscribeApiData } from '../lib/api';
import {useStoredViewState,type ViewStateStore} from '../lib/viewState';
import type { TrendGroup, TrendSource } from '../lib/api';
import { IconFire, IconRefresh, IconBookmark, IconCheck, IconChat } from './icons';
import TrendSourcesDialog from './TrendSourcesDialog';

interface TrendsPageProps {
  onUseTopic: (title: string, sourceId?: string, note?: string) => void;   // 一键做成内容 → 跳 chat
  refreshAll?: () => Promise<unknown>;
  onRead?: (sourceId: string) => void;
  listLimit?: number;
  quietBackgroundRefresh?: boolean;
  listMaxHeight?: number;
  viewState?:ViewStateStore<TrendsViewState>;
  onContentReady?:()=>void;
}
export interface TrendsViewState {selected:string[];initialized?:boolean}

class TrendBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <div className="page-scroll trends-page"><div className="notice-error" role="alert">热点页面暂时无法显示，其他工作台功能仍可使用。<button className="btn btn-sm" onClick={() => this.setState({ failed: false })}>重新加载热点</button></div></div> : this.props.children;
  }
}

export default function TrendsPage(props: TrendsPageProps) {
  return <TrendBoundary><TrendsPanel {...props} /></TrendBoundary>;
}

function TrendsPanel({ onUseTopic, onRead, refreshAll, listLimit = 15, quietBackgroundRefresh = false, listMaxHeight,viewState,onContentReady }: TrendsPageProps) {
  const sourceSnapshot=peekApiData<Awaited<ReturnType<typeof fetchTrendSources>>>('/api/trends/sources');
  const [view,setView]=useStoredViewState<TrendsViewState>(viewState,()=>({selected:sourceSnapshot?.sources.filter(source=>source.default).map(source=>source.id)??[]}));
  const selected=view.selected;
  const setSelected=(value:string[]|((previous:string[])=>string[]))=>setView(previous=>({...previous,initialized:true,selected:typeof value==='function'?value(previous.selected):value}));
  const trendPath='/api/trends?limit='+listLimit+'&platforms='+encodeURIComponent(selected.join(','));
  const snapshot=peekApiData<Awaited<ReturnType<typeof fetchTrends>>>(trendPath);
  const [sources, setSources] = useState<TrendSource[]>(()=>sourceSnapshot?.sources??[]);
  const [ready, setReady] = useState(!!sourceSnapshot);
  const [groups, setGroups] = useState<TrendGroup[]>(()=>snapshot?.trends??[]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [updated, setUpdated] = useState(()=>snapshot?.updated??0);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [managerOpen, setManagerOpen] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saveError, setSaveError] = useState('');
  const requestId = useRef(0);
  const discoveryId = useRef(0);
  const initialized = useRef(view.initialized??!!sourceSnapshot);
  const selectedRef=useRef(selected);selectedRef.current=selected;

  const save = async (key: string, title: string, source: string, sourceId: string) => {
    if (saved.has(key)) return;
    try {
      await createIdea({ title, source, source_id: sourceId, status: 'pending' });
      setSaved((prev) => new Set(prev).add(key));
    } catch { setSaveError('收藏失败，请稍后重试。'); }
  };

  const load = useCallback((pfs: string[], background = false,force=false) => {
    const id = ++requestId.current;
    if (pfs.length === 0) { setGroups([]); setLoading(false); setError(''); return; }
    setGroups((prev) => prev.filter((g) => pfs.includes(g.platform)));
    if (!quietBackgroundRefresh || !background) { setLoading(true); setError(''); }
    fetchTrends(pfs.join(','), listLimit,force)
      .then((d) => { if (requestId.current === id) { setGroups(d.trends); setUpdated(d.updated); setWarnings(d.warnings); if (quietBackgroundRefresh && background) setError(''); } })
      .catch((e: unknown) => {
        if (requestId.current === id) setError(e instanceof Error ? e.message : '热点拉取失败，请稍后重试。');
      })
      .finally(() => { if (requestId.current === id) setLoading(false); });
  }, [listLimit, quietBackgroundRefresh]);

  const discover = useCallback((force=false) => {
    const id = ++discoveryId.current;
    requestId.current++;
    if(!peekApiData('/api/trends/sources'))setReady(false);
    setLoading(false);
    setError('');
    return fetchTrendSources(force).then((d) => {
      if (discoveryId.current !== id) return;
      setSources(d.sources);
      setWarnings(d.warnings);
      const first = !initialized.current;
      initialized.current = true;
      setSelected(first ? d.sources.filter((s) => s.default).map((s) => s.id)
        : d.sources.filter((s) => selectedRef.current.includes(s.id)).map((s) => s.id));
      setGroups((prev) => prev.filter((g) => d.sources.some((s) => s.id === g.platform)));
      setReady(true);
    }).catch((e: unknown) => {
      if (discoveryId.current === id) {
        setError(e instanceof Error ? e.message : '无法加载热点数据源。');
      }
    });
  }, []);

  const invalidate = useCallback(() => { requestId.current++; discoveryId.current++; }, []);
  useEffect(() => { void discover(); return invalidate; }, [discover, invalidate]);
  useEffect(() => { if (ready) load(selected,!!peekApiData(trendPath)); }, [load, selected, ready]);
  useEffect(()=>subscribeApiData<Awaited<ReturnType<typeof fetchTrends>>>(trendPath,data=>{setGroups(data.trends);setUpdated(data.updated);setWarnings(data.warnings);setError('');setLoading(false)},error=>setError(error.message)),[trendPath]);
  useEffect(()=>subscribeApiData<Awaited<ReturnType<typeof fetchTrendSources>>>('/api/trends/sources',data=>{setSources(data.sources);setWarnings(data.warnings);setSelected(data.sources.filter(source=>selectedRef.current.includes(source.id)).map(source=>source.id));setReady(true)},error=>setError(error.message)),[]);
  useEffect(()=>{if((ready||error)&&!loading)onContentReady?.()},[ready,error,loading,groups,onContentReady]);
  useEffect(() => {
    if (!groups.some(group => group.error?.code === 'busy')) return;
    const timer = window.setTimeout(() => load(selected, true), 1500);
    return () => window.clearTimeout(timer);
  }, [groups, selected, load]);

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try { if (refreshAll) await refreshAll(); await discover(true); load(selectedRef.current,true,true); }
    catch (caught) { setError(caught instanceof Error ? caught.message : '刷新失败，请重试。'); }
    finally { setRefreshing(false); }
  };

  const toggle = (k: string) =>
    setSelected((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]);

  const refreshBusy = refreshing || (!refreshAll && loading);

  return (
    <div className="page-scroll trends-page" aria-busy={loading}>
      <div className="page-head">
        <div>
          <h1 className="page-title"><IconFire size={22} /> 热点雷达</h1>
          <p className="page-subtitle">
            汇集平台热搜与自定义数据源，挑选题，一键交给 AI 做成你的内容。
            {updated > 0 && <span style={{ color: 'var(--text-tertiary)' }}> · {new Date(updated * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 查询</span>}
          </p>
        </div>
        <div className="trend-actions"><button className="btn btn-sm" onClick={() => setManagerOpen(true)}>数据源</button>
        <button className="btn btn-sm" onClick={() => { void refresh(); }} disabled={refreshBusy}>
          <IconRefresh size={14} /> {refreshBusy ? '刷新中…' : '刷新'}
        </button></div>
      </div>

      <div className="trend-platforms">
        {sources.map((p) => (
          <button key={p.id} className={`chip ${selected.includes(p.id) ? 'active' : ''}`}
            aria-pressed={selected.includes(p.id)} onClick={() => toggle(p.id)}>{p.label}</button>
        ))}
      </div>

      {error && <div className="notice-error" role="alert">{error}</div>}
      {saveError && <div className="notice-error" role="alert">{saveError}</div>}
      {warnings.map((warning, i) => <div className="notice-error" role="status" key={i}>{warning}</div>)}
      {!ready && !error && <div className="trend-platforms" role="status">正在加载数据源…</div>}
      {ready && sources.length === 0 && <div className="trend-platforms">尚未启用数据源，请在本地热点数据源配置中添加或启用。</div>}
      {ready && sources.length > 0 && selected.length === 0 && <div className="trend-platforms">请选择上方的数据源查看热点。</div>}
      {loading && <div className="trend-platforms" role="status">正在获取热点…</div>}

      <div className="trend-grid">
        {groups.map((g) => (
          <div key={g.platform} className="card trend-col">
            <div className="trend-col-head">{g.label}<span className="trend-count">{g.items.length}</span></div>
            <div className="trend-source-status">
              {g.fetched_at && <span>采集于 {new Date(g.fetched_at).toLocaleString('zh-CN')}</span>}
              {g.stale && <span> · 缓存已过期</span>}
              {g.error && <div role="status">{g.error.message}{g.stale ? '，暂用上次结果' : ''}</div>}
            </div>
            <div className="trend-list" role="region" aria-label={g.label+'热点列表'} tabIndex={g.items.length>15?0:undefined} data-native-scroll-region={'news:'+g.platform} style={listMaxHeight===undefined?undefined:{maxHeight:listMaxHeight,overflowY:'auto',overscrollBehavior:'contain'}}>
              {g.items.length === 0 && !loading && (
                <div className="trend-empty">
                  {!g.ok ? '该数据源暂时不可用' : '采集成功，暂无热点'}
                </div>
              )}
              {g.items.map((it, i) => (
                <div key={it.id} className="trend-item" data-native-anchor={'news:'+it.id}>
                  <span className={`trend-rank ${i < 3 ? 'top' : ''}`}>{i + 1}</span>
                  <div className="trend-main">
                    <a className="trend-title" href={it.url || undefined} target={onRead?undefined:'_blank'} rel="noreferrer"
                      onClick={event=>{if(onRead&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0){event.preventDefault();onRead(it.id)}}} title={it.title}>{it.title}</a>
                    {it.hot && <span className="trend-hot">{it.hot}</span>}
                  </div>
                  <div className="trend-item-actions">
                    <button className="trend-save" title={saved.has(`${g.platform}:${it.id}`) ? '已收藏到选题库' : '收藏到选题库'}
                      aria-label={`${saved.has(`${g.platform}:${it.id}`) ? '已收藏' : '收藏选题'}：${it.title}`}
                      onClick={() => save(`${g.platform}:${it.id}`, it.title, g.label, it.id)}>
                      {saved.has(`${g.platform}:${it.id}`) ? <IconCheck size={14} /> : <IconBookmark size={14} />}
                    </button>
                    <button className="trend-use" title="做成内容" aria-label={`做成内容：${it.title}`}
                      onClick={() => onUseTopic(it.title,it.id)}><IconChat size={14} /></button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      {managerOpen && <TrendSourcesDialog onClose={() => setManagerOpen(false)} onChanged={addedId => {
        void discover().then(() => { if (addedId) setSelected(prev => [...new Set([...prev, addedId])]); });
      }} />}
    </div>
  );
}
