import { Component, useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { fetchTrendSources, fetchTrends, createIdea } from '../lib/api';
import type { TrendGroup, TrendSource } from '../lib/api';
import TrendsView from './TrendsView';
import TrendSourcesDialog from './TrendSourcesDialog';

interface TrendsPageProps {
  onUseTopic: (title: string) => void;   // 一键做成内容 → 跳 chat
  refreshAll?: () => Promise<unknown>;
  listLimit?: number;
}

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

function TrendsPanel({ onUseTopic, refreshAll, listLimit = 15 }: TrendsPageProps) {
  const [sources, setSources] = useState<TrendSource[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [groups, setGroups] = useState<TrendGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [updated, setUpdated] = useState(0);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [managerOpen, setManagerOpen] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saveError, setSaveError] = useState('');
  const requestId = useRef(0);
  const discoveryId = useRef(0);
  const initialized = useRef(false);

  const save = async (key: string, title: string, source: string) => {
    if (saved.has(key)) return;
    try {
      await createIdea({ title, source, status: 'pending' });
      setSaved((prev) => new Set(prev).add(key));
    } catch { setSaveError('收藏失败，请稍后重试。'); }
  };

  const load = useCallback((pfs: string[]) => {
    const id = ++requestId.current;
    if (pfs.length === 0) { setGroups([]); setLoading(false); setError(''); return; }
    setGroups((prev) => prev.filter((g) => pfs.includes(g.platform)));
    setLoading(true);
    setError('');
    fetchTrends(pfs.join(','), listLimit)
      .then((d) => { if (requestId.current === id) { setGroups(d.trends); setUpdated(d.updated); setWarnings(d.warnings); } })
      .catch((e: unknown) => {
        if (requestId.current === id) setError(e instanceof Error ? e.message : '热点拉取失败，请稍后重试。');
      })
      .finally(() => { if (requestId.current === id) setLoading(false); });
  }, [listLimit]);

  const discover = useCallback(() => {
    const id = ++discoveryId.current;
    requestId.current++;
    setReady(false);
    setLoading(false);
    setError('');
    return fetchTrendSources().then((d) => {
      if (discoveryId.current !== id) return;
      setSources(d.sources);
      setWarnings(d.warnings);
      const first = !initialized.current;
      initialized.current = true;
      setSelected((prev) => first ? d.sources.filter((s) => s.default).map((s) => s.id)
        : d.sources.filter((s) => prev.includes(s.id)).map((s) => s.id));
      setGroups((prev) => prev.filter((g) => d.sources.some((s) => s.id === g.platform)));
      setReady(true);
    }).catch((e: unknown) => {
      if (discoveryId.current === id) {
        setGroups([]);
        setSources([]);
        setError(e instanceof Error ? e.message : '无法加载热点数据源。');
      }
    });
  }, []);

  const invalidate = useCallback(() => { requestId.current++; discoveryId.current++; }, []);
  useEffect(() => { void discover(); return invalidate; }, [discover, invalidate]);
  useEffect(() => { if (ready) load(selected); }, [load, selected, ready]);
  useEffect(() => {
    if (!groups.some(group => group.error?.code === 'busy')) return;
    const timer = window.setTimeout(() => load(selected), 1500);
    return () => window.clearTimeout(timer);
  }, [groups, selected, load]);

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try { if (refreshAll) await refreshAll(); await discover(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : '刷新失败，请重试。'); }
    finally { setRefreshing(false); }
  };

  const toggle = (k: string) =>
    setSelected((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]);

  return <><TrendsView sources={sources} selected={selected} groups={groups} ready={ready} loading={loading} refreshing={refreshing||loading||groups.some(group=>group.error?.code==='busy')}
    updated={updated} error={error||saveError} warnings={warnings} saved={saved}
    onToggle={toggle} onRefresh={()=>{void refresh()}} onManage={()=>setManagerOpen(true)}
    onSave={(g,it)=>{void save(`${g.platform}:${it.id}`,it.title,g.label)}} onUse={(_,it)=>onUseTopic(it.title)}/>
    {managerOpen&&<TrendSourcesDialog onClose={()=>setManagerOpen(false)} onChanged={addedId=>{
      void discover().then(()=>{if(addedId)setSelected(prev=>[...new Set([...prev,addedId])])});
    }}/>}</>;
}
