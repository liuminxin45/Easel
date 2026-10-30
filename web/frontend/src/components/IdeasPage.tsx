import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { fetchIdeas, createIdea, updateIdea, deleteIdea, createSchedule } from '../lib/api';
import type { Idea, IdeaInput } from '../lib/api';
import IdeasView,{NEXT} from './IdeasView';

interface IdeasPageProps {
  onUseTopic: (title: string) => void;
  draftStore?: IdeasPageDraftStore;
}

export interface IdeasPageDraft { form: IdeaInput | null; editId: string | null; revision?: number }
export interface IdeasPageDraftStore {
  read: () => IdeasPageDraft | null;
  write: (draft: IdeasPageDraft) => void;
  remove: () => void;
}

const EMPTY: IdeaInput = { title: '', note: '', source: '', status: 'pending' };

export default function IdeasPage({ onUseTopic, draftStore }: IdeasPageProps) {
  const initialDraft = useRef(draftStore?.read());
  const currentDraft = useRef<IdeasPageDraft>(initialDraft.current?.form ? initialDraft.current : { form: null, editId: null });
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [form, setFormState] = useState<IdeaInput | null>(currentDraft.current.form);
  const [editId, setEditId] = useState<string | null>(currentDraft.current.editId);
  const [toast, setToast] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => { fetchIdeas().then(setIdeas).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);

  const showToast = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200); };
  const byStatus = useMemo(() => {
    const g: Record<string, Idea[]> = { pending: [], doing: [], done: [] };
    for (const it of ideas) (g[it.status] || g.pending).push(it);
    return g;
  }, [ideas]);

  const showForm = (draft: IdeasPageDraft) => {
    currentDraft.current = draft;
    setEditId(draft.editId); setFormState(draft.form);
  };
  const setForm = (value: IdeaInput | null) => {
    const draft = { ...currentDraft.current, form: value };
    showForm(draft);
    // Closing a modal keeps its unsent input; only an accepted exact save clears it.
    if (value) draftStore?.write(draft);
  };
  const openNew = () => { const saved = draftStore?.read(); showForm(saved?.form ? saved : { editId: null, form: { ...EMPTY } }); };
  const openEdit = (it: Idea) => {
    const saved = draftStore?.read();
    showForm(saved?.editId === it.id ? saved : { editId: it.id, form: { title: it.title, note: it.note, source: it.source, status: it.status }, revision: (it as Idea & { revision?: number }).revision });
  };
  const save = async () => {
    if (!form || !form.title.trim() || busy) return;
    const submitted = currentDraft.current;
    setBusy(true);
    try {
      if (submitted.editId) await updateIdea(submitted.editId, submitted.form!); else await createIdea(submitted.form!);
      if (JSON.stringify(currentDraft.current) === JSON.stringify(submitted)) showForm({ form: null, editId: null });
      const stored = draftStore?.read();
      if (stored && JSON.stringify({ form: stored.form, editId: stored.editId, revision: stored.revision }) === JSON.stringify({ form: submitted.form, editId: submitted.editId, revision: submitted.revision })) draftStore?.remove();
      load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : '保存失败，原输入已保留');
    } finally { setBusy(false); }
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

  return <IdeasView {...{byStatus,form,editId,toast,busy,openNew,openEdit,setForm,save,advance,remove,schedule,onUseTopic}}/>;
}
