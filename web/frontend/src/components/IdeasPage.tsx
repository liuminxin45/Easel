import { useState, useEffect, useCallback, useMemo } from 'react';
import { fetchIdeas, createIdea, updateIdea, deleteIdea, createSchedule } from '../lib/api';
import type { Idea, IdeaInput } from '../lib/api';
import IdeasView,{NEXT} from './IdeasView';

interface IdeasPageProps {
  onUseTopic: (title: string) => void;
}

const EMPTY: IdeaInput = { title: '', note: '', source: '', status: 'pending' };

export default function IdeasPage({ onUseTopic }: IdeasPageProps) {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [form, setForm] = useState<IdeaInput | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [toast, setToast] = useState('');

  const load = useCallback(() => { fetchIdeas().then(setIdeas).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);

  const showToast = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200); };
  const byStatus = useMemo(() => {
    const g: Record<string, Idea[]> = { pending: [], doing: [], done: [] };
    for (const it of ideas) (g[it.status] || g.pending).push(it);
    return g;
  }, [ideas]);

  const openNew = () => { setEditId(null); setForm({ ...EMPTY }); };
  const openEdit = (it: Idea) => { setEditId(it.id); setForm({ title: it.title, note: it.note, source: it.source, status: it.status }); };
  const save = async () => {
    if (!form || !form.title.trim()) return;
    if (editId) await updateIdea(editId, form); else await createIdea(form);
    setForm(null); setEditId(null); load();
  };
  const advance = async (it: Idea) => { await updateIdea(it.id, { ...it, status: NEXT[it.status] }); load(); };
  const remove = async (it: Idea) => { await deleteIdea(it.id); load(); };
  const schedule = async (it: Idea) => {
    // 用本地日期（日历页按本地渲染）：toISOString 是 UTC，东八区 0-8 点会落到「昨天」
    const d = new Date();
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    await createSchedule({ title: it.title, date, platform: '', time: '', status: 'idea', note: it.note });
    showToast('已加入日历（今天）');
  };

  return <IdeasView {...{byStatus,form,editId,toast,openNew,openEdit,setForm,save,advance,remove,schedule,onUseTopic}}/>;
}
