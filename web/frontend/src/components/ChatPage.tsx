import { useState, useRef, useEffect, useLayoutEffect, type ReactNode } from 'react';
import MessageBubble from './MessageBubble';
import {StatusCard} from './InteractionNotice';
import QuestionCards from './QuestionCards';
import type {QuestionServices} from './QuestionCards';
import BrushEntry,{BrushItem} from './BrushEntry';
import {useBrushPopover} from './useBrushPopover';
import type {Artifact} from '../lib/artifacts';
import type { ChatSession, ChatMessage, StreamState } from '../lib/store';
import { uploadFiles, adoptOversize } from '../lib/api';
import type { UploadedFile } from '../lib/api';
import { IconArrowUp, IconStop, IconPlus, IconFile } from './icons';
import type {ViewStateStore} from '../lib/viewState';
export interface ChatViewState {top:number;following:boolean}

export interface ChatCommand { id: string; label: string; description?: string; disabled?: boolean; group?:string;tab?:string;tabLabel?:string;status?:string;prompt?:string; }
export interface ChatComposerBindings {
  text: string;
  attachments: UploadedFile[];
  onTextChange: (value: string) => void;
  onUpload: (files: File[]) => Promise<void>;
  onRemoveAttachment: (id: string) => void;
  commands?: ChatCommand[];
  selectedCommand?: ChatCommand;
  onCommandSelect?: (id: string | null, remainingText?: string) => void;
  busy?: boolean;
  disabled?: boolean;
  canSend?: boolean;
  label?: string;
  placeholder?: string;
  sendLabel?: string;
  status?: string;
  registerLayer?: (close: () => void) => (() => void) | undefined;
}
interface ChatPageProps {
  apiDirect: boolean;
  session: ChatSession;
  stream?: StreamState;          // 进行中的流式态（来自 App，切页也不丢）
  onSend: (displayText: string, attachments?: UploadedFile[]) => void;
  onStop: () => void;
  onResend: (
    userIndex: number,
    displayText: string,
    attachments?: UploadedFile[],
    legacyAgentText?: string,
  ) => void; // 重试：仅对最后一轮
  onQuestionAnswered?: (questionId: string) => void;   // 某道问答题提交成功（App 记录答过，重放不再出现）
  onQuestionClosed?: (id: string, status: string) => void;
  composer?: ChatComposerBindings;
  header?: ReactNode;
  footer?: ReactNode;
  notice?: ReactNode;
  emptyState?: { title?: string; subtitle?: string; brand?: string; icon?: ReactNode; suggestions?: typeof SUGGESTIONS };
  canResend?: (message: ChatMessage, index: number) => boolean;
  renderMessageExtra?: (message: ChatMessage, index: number) => ReactNode;
  linkifyArtifactPaths?: boolean;
  questionServices?:QuestionServices;
  messageArtifacts?:(message:ChatMessage)=>Artifact[]|undefined;
  resolveArtifactPath?:(message:ChatMessage,path:string,kind:'media'|'library')=>string|undefined;
  viewState?:ViewStateStore<ChatViewState>;
  onContentReady?:()=>void;
}

// 空态推荐（贴合 Easel 社媒创作场景）
const SUGGESTIONS = [
  { icon: '🔥', title: '蹭个热点', prompt: '看看现在微博和抖音有什么热搜，挑几个适合我做二创的选题' },
  { icon: '✍️', title: '写小红书文案', prompt: '帮我写一条小红书种草文案，主题先问我' },
  { icon: '🎴', title: '做金句卡片', prompt: '把一句走心的话做成一张适合发朋友圈的金句卡片' },
  { icon: '🎬', title: '口播脚本', prompt: '帮我写一条 60 秒的口播短视频脚本，主题先问我' },
];

function greeting(): string {
  const h = new Date().getHours();
  const g = h < 6 ? '夜深了' : h < 12 ? '上午好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好';
  return `${g}，想创作点什么？`;
}

export default function ChatPage({ apiDirect, session, stream, onSend, onStop, onResend, onQuestionAnswered, onQuestionClosed,
  composer, header, footer, notice, emptyState, canResend, renderMessageExtra, linkifyArtifactPaths,questionServices,messageArtifacts,resolveArtifactPath,viewState,onContentReady }: ChatPageProps) {
  const [localInput, setLocalInput] = useState('');
  const [localAttachments, setLocalAttachments] = useState<UploadedFile[]>([]);
  const input = composer?.text ?? localInput;
  const attachments = composer?.attachments ?? localAttachments;
  const setInput = (value: string) => composer ? composer.onTextChange(value) : setLocalInput(value);
  const [commandMenu, setCommandMenu] = useState(false);
  const [commandIndex, setCommandIndex] = useState(0);
  const [slashDismissed, setSlashDismissed] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [maxMb, setMaxMb] = useState(50);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesRef=useRef<HTMLDivElement>(null),following=useRef(viewState?.read()?.following??true),restored=useRef(false),viewOwner=useRef(viewState);
  const composerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const commandListRef = useRef<HTMLDivElement>(null);
  const commandPanelRef = useRef<HTMLDivElement>(null);
  const isComposingRef = useRef(false);

  const isStreaming = !!stream;
  const isEmpty = session.messages.length === 0 && !isStreaming;
  const busy = isStreaming || !!composer?.busy;
  const slash = input.startsWith('/') && !slashDismissed;
  const commandQuery = slash ? input.slice(1).split(/[\s]/, 1)[0].toLowerCase() : '';
  const commands = (composer?.commands || []).filter(command => !commandQuery ||
    `${command.label} ${command.description || ''} ${command.id}`.toLowerCase().includes(commandQuery));
  const showCommands = !!composer?.commands && (commandMenu || slash);
  useBrushPopover(showCommands,composerRef,commandPanelRef,`${commandQuery}:${commands.length}`);
  const enabledCommandIndices=commands.flatMap((command,index)=>command.disabled?[]:[index]);
  const activeCommandIndex=enabledCommandIndices.includes(commandIndex)?commandIndex:enabledCommandIndices[0]??-1;
  const pickCommand = (id: string | null) => {
    if (busy || composer?.disabled || composer?.commands?.find(command=>command.id===id)?.disabled) return;
    const match = slash ? /^\/[^\s]*(?:[ \t]|\r?\n)?([\s\S]*)$/.exec(input) : null;
    composer?.onCommandSelect?.(id, match?.[1]);
    setCommandMenu(false); setSlashDismissed(true); setCommandIndex(0);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };
  useEffect(() => {
    if (!showCommands) return;
    const close = () => { setCommandMenu(false); setSlashDismissed(true); textareaRef.current?.focus(); };
    const outside = (event: PointerEvent) => { if (!composerRef.current?.contains(event.target as Node)) { setCommandMenu(false); setSlashDismissed(true); } };
    document.addEventListener('pointerdown', outside);
    const release = composer?.registerLayer?.(close);
    return () => { document.removeEventListener('pointerdown', outside); release?.(); };
  }, [showCommands, composer?.registerLayer]);

  useLayoutEffect(()=>{
    if(showCommands&&activeCommandIndex>=0)commandListRef.current?.querySelector<HTMLElement>(`[data-command-index="${activeCommandIndex}"]`)?.scrollIntoView({block:'nearest'});
  },[showCommands,activeCommandIndex,commandQuery]);

  useEffect(() => {
    if (composer) return;
    fetch('/api/upload/limits').then((r) => r.json())
      .then((d) => { if (d?.max_mb) setMaxMb(d.max_mb); }).catch(() => {});
  }, [!!composer]);

  const doUpload = async (fs: FileList | File[]) => {
    const arr = Array.from(fs);
    if (!arr.length) return;
    if (composer) {
      setUploading(true); setUploadError('');
      try { await composer.onUpload(arr); }
      catch (error) { setUploadError(error instanceof Error ? error.message : '素材未添加，原输入仍保留。'); }
      finally { setUploading(false); }
      return;
    }
    const cap = maxMb * 1024 * 1024;
    const big = arr.filter((f) => f.size > cap);
    const small = arr.filter((f) => f.size <= cap);

    if (big.length) {
      // 超限：不走上传通道，复制进收件箱后作为普通附件（界面零新增元素）
      setUploading(true);
      try {
        const saved = await adoptOversize(big, session.id);
        setLocalAttachments((a) => [...a, ...saved]);
      } catch (err) {
        alert((err as Error).message || '超限文件处理失败');
      } finally {
        setUploading(false);
      }
    }
    if (!small.length) return;
    setUploading(true);
    try {
      const saved = await uploadFiles(small, session.id);
      setLocalAttachments((a) => [...a, ...saved]);
    } catch (err) {
      alert((err as Error).message || '上传失败');
    } finally {
      setUploading(false);
    }
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    if (e.dataTransfer.files?.length) doUpload(e.dataTransfer.files);
  };
  const onPaste = (e: React.ClipboardEvent) => {
    if (e.clipboardData.files?.length) { e.preventDefault(); doUpload(e.clipboardData.files); }
  };
  const removeAttachment = (file: UploadedFile) => composer ? composer.onRemoveAttachment(file.id)
    : setLocalAttachments(a => a.filter(x => x.path !== file.path));

  useLayoutEffect(() => {
    if(viewOwner.current!==viewState){viewOwner.current=viewState;following.current=viewState?.read()?.following??true;restored.current=false}
    const element=messagesRef.current;if(!element||isEmpty)return;
    if(!restored.current){restored.current=true;const saved=viewState?.read();if(saved&&!saved.following){following.current=false;element.scrollTop=saved.top;onContentReady?.();return}}
    if(following.current)element.scrollTo({top:element.scrollHeight,behavior:stream?'instant':'smooth'});
    onContentReady?.();
  }, [session.messages, stream?.content, stream?.thinking, stream?.activity, stream?.stillWorking, isEmpty,onContentReady,viewState]);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 180) + 'px';
    }
  }, [input, isEmpty]);

  const handleSend = () => {
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0 && composer?.canSend !== true) || busy || uploading || composer?.disabled || composer?.canSend === false) return;
    // 附件通过结构化字段发送；用户消息气泡只显示用户实际输入的文字。
    following.current=true;
    onSend(trimmed, attachments);
    // A controlled host clears its draft only after an authoritative receipt.
    if (!composer) { setLocalInput(''); setLocalAttachments([]); }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 输入法确认候选词/英文的回车交给输入法处理，不能触发发送。
    // 部分浏览器先触发 compositionend，此时仍需用 229 识别输入法按键。
    if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return;
    if (showCommands) {
      if (e.key === 'Escape') { e.preventDefault(); setCommandMenu(false); setSlashDismissed(true); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();const current=enabledCommandIndices.indexOf(activeCommandIndex),next=Math.max(0,Math.min(enabledCommandIndices.length-1,current+(e.key==='ArrowDown'?1:-1)));setCommandIndex(enabledCommandIndices[next]??0);return;
      }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault();if(activeCommandIndex>=0)pickCommand(commands[activeCommandIndex]!.id);return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const inputBox = (hero: boolean) => (
    <div ref={composerRef} className={`composer ${hero ? 'composer-hero' : ''} ${dragOver ? 'composer-drag' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
      onDrop={onDrop}>
      {composer?.selectedCommand && <div className="composer-attachments"><span className="attach-chip" data-chat-command={composer.selectedCommand.id}>
        <span>/{composer.selectedCommand.label}</span><button className="attach-x" disabled={busy || composer.disabled}
          aria-label="移除所选技能" onClick={() => pickCommand(null)}>×</button>
      </span></div>}
      {attachments.length > 0 && (
        <div className="composer-attachments">
          {attachments.map((a) => (
            <span key={a.path} className="attach-chip" title={a.path}>
              <IconFile size={12} /> <span className="attach-name">{a.name}</span>
              <button className="attach-x" onClick={() => removeAttachment(a)} title="移除">×</button>
            </span>
          ))}
        </div>
      )}
      <div className="composer-top">
        {apiDirect ? <span className="composer-hint">API 直连 · 文字与附件分析</span>
          : <BrushEntry items={composer?.commands} onSelect={id=>{const choice=composer?.commands?.find(item=>item.id===id);pickCommand(id);if(!input.trim()&&choice)setInput(choice.prompt||`帮我${choice.label}`);requestAnimationFrame(()=>textareaRef.current?.focus())}} registerLayer={composer?.registerLayer} disabled={busy||composer?.disabled} onPick={(t) => { setInput(t); requestAnimationFrame(() => textareaRef.current?.focus()); }} />}
        <textarea
          ref={textareaRef}
          className="chat-input"
          aria-label={composer?.label}
          placeholder={dragOver ? '松手上传素材…' : composer?.placeholder || (hero ? '把你的想法告诉我，选题 / 文案 / 卡片 / 视频 / 发布都行…（可拖入图片/文档当素材）' : '发消息…（Enter 发送，Shift+Enter 换行，可拖入/粘贴素材）')}
          value={input}
          onChange={(e) => { setInput(e.target.value); setSlashDismissed(false); setCommandIndex(0); }}
          onCompositionStart={() => { isComposingRef.current = true; }}
          onCompositionEnd={() => { isComposingRef.current = false; }}
          onBlur={() => { isComposingRef.current = false; }}
          onKeyDown={handleKeyDown}
          onPaste={onPaste}
          rows={1}
          autoFocus={hero}
        />
      </div>
      <input ref={fileInputRef} type="file" multiple hidden
        onChange={(e) => { if (e.target.files) doUpload(e.target.files); e.target.value = ''; }} />
      <div className="composer-bar">
        <button className="composer-attach-btn" onClick={() => fileInputRef.current?.click()}
          aria-label="添加素材"
          disabled={busy || uploading || composer?.disabled} title={composer ? '添加素材（图片/文档）' : `添加素材（图片/文档）；超过 ${maxMb}MB 的大文件将自动存为本地素材（不走上传）`}>
          <IconPlus size={15} /> {uploading ? '上传中…' : '素材'}
        </button>
        <span className="composer-hint">{isStreaming ? '生成中…' : 'Enter 发送 · Shift+Enter 换行'}</span>
        {isStreaming ? (
          <button className="send-btn" onClick={onStop} title="停止生成"><IconStop size={15} /></button>
        ) : (
          <button className="send-btn" onClick={handleSend} disabled={(!input.trim() && !attachments.length && composer?.canSend !== true) || uploading || busy || composer?.disabled || composer?.canSend === false}
            title={composer?.sendLabel || '发送'} aria-label={composer?.sendLabel || '发送'}><IconArrowUp size={17} /></button>
        )}
      </div>
      {composer?.status && <div className="composer-hint" role="status">{composer.status}</div>}
      {uploadError && <StatusCard className="ew-status-card-compact" tone="error">{uploadError}</StatusCard>}
      {showCommands && <div ref={commandPanelRef} className="chat-command-menu brush-panel" role="menu" aria-label="选择技能">
        <div className="brush-panel-head"><div className="brush-panel-title" style={{flex:1}}>选择技能</div><button type="button" className="brush-close" role="menuitem" aria-label="关闭技能菜单" onClick={()=>{setCommandMenu(false);setSlashDismissed(true);textareaRef.current?.focus()}}>×</button></div>
        <div ref={commandListRef} className="brush-body">
          <BrushItem item={{label:'上传素材',description:'图片或文档'}} role="menuitem" aria-label="上传素材" disabled={busy||uploading||composer?.disabled} onClick={() => {setCommandMenu(false);setSlashDismissed(true);fileInputRef.current?.click()}}/>
          <div className="brush-grp"><div className="brush-grp-name">技能 · {commands.length}</div>
            {commands.map((command,index)=><BrushItem key={command.id} item={command} labelPrefix="/" role="menuitem" aria-label={'/'+command.label} title={command.description} data-command-index={index} active={index===activeCommandIndex} aria-current={index===activeCommandIndex?true:undefined} disabled={busy||composer?.disabled||command.disabled} onClick={()=>pickCommand(command.id)}/>)}
            {!commands.length&&<p className="brush-panel-sub">没有匹配的可用技能</p>}
          </div>
        </div>
      </div>}
    </div>
  );

  // ---- 空态：居中欢迎页 ----
  if (isEmpty) {
    return (
      <div className="chat-page">
        {header}{notice}
        <div className="chat-hero">
          <div className="chat-hero-brand">
            {emptyState?.icon || <img src="./static/easel-icon-transparent.png" alt="" />}
            <span>{emptyState?.brand || 'Easel'}</span>
          </div>
          <h1 className="chat-hero-title">{emptyState?.title || greeting()}</h1>
          <p className="chat-hero-sub">{emptyState?.subtitle || (apiDirect ? 'API 直连：写文案、策划选题、分析附件。本机工具和自动发布未启用。'
            : '从选题到发布，一站式帮你把想法做成能发的内容。')}</p>
          {inputBox(true)}
          <div className="suggestions">
            {(emptyState?.suggestions || SUGGESTIONS).filter((s) => !apiDirect || ['写小红书文案', '口播脚本'].includes(s.title)).map((s) => (
              <button key={s.title} className="card card-hover suggestion-card"
                onClick={() => { if (!isStreaming) onSend(s.prompt); }}>
                <span className="suggestion-icon">{s.icon}</span>
                <span className="suggestion-body">
                  <span className="suggestion-title">{s.title}</span>
                  <span className="suggestion-text">{s.prompt}</span>
                </span>
              </button>
            ))}
          </div>
          {footer}
        </div>
      </div>
    );
  }

  // ---- 对话态 ----
  const displayMessages: ChatMessage[] = [...session.messages];
  if (isStreaming) displayMessages.push({ role: 'assistant', content: stream!.content || '' });

  return (
    <div className="chat-page">
      {header}{notice}
      <div className="chat-messages" ref={messagesRef} data-native-scroll="chat-messages" data-native-scroll-owner={viewState?'page':undefined} onScroll={event=>{const element=event.currentTarget;following.current=element.scrollHeight-element.scrollTop-element.clientHeight<80;viewState?.write({top:element.scrollTop,following:following.current})}}>
        <div className="chat-thread">
          {displayMessages.map((msg, i) => {
            const isLast = i === displayMessages.length - 1;
            const live = isStreaming && isLast && msg.role === 'assistant';
            const isFinal = !live && i < session.messages.length;
            let actions;
            if (isFinal) {
              const copy = () => navigator.clipboard?.writeText(msg.content);
              // 只允许对「最后一轮」重试，契合 OpenClaw append-only 模型（不改写历史）；已移除编辑
              const isLastFinal = i === session.messages.length - 1;
              if (msg.role === 'user') {
                actions = {
                  onCopy: copy,
                  onRetry: isLastFinal && (canResend?.(msg, i) ?? true)
                    ? () => onResend(i, msg.content, msg.attachments, msg.agentContent)
                    : undefined,
                  canModify: !isStreaming,
                };
              } else {
                const pi = i - 1;
                const prevUser = pi >= 0 && session.messages[pi]?.role === 'user' ? session.messages[pi] : null;
                actions = {
                  onCopy: copy,
                  onRetry: (isLastFinal && prevUser && (canResend?.(prevUser, pi) ?? true))
                    ? () => onResend(pi, prevUser.content, prevUser.attachments, prevUser.agentContent)
                    : undefined,
                  canModify: !isStreaming,
                };
              }
            }
            return (
              <div key={`${i}-${msg.role}`} data-native-anchor={'chat:'+((msg as ChatMessage&{id?:string;turnId?:string}).id||(msg as ChatMessage&{turnId?:string}).turnId||`${i}-${msg.role}`)}>
              <MessageBubble
                key={`${i}-${msg.role}`}
                message={msg}
                isStreaming={live}
                thinking={live ? stream!.thinking : ''}
                activity={live ? stream!.activity : ''}
                stillWorking={live ? stream!.stillWorking : ''}
                actions={actions}
                linkifyArtifactPaths={linkifyArtifactPaths}
                artifacts={messageArtifacts?.(msg)}
                resolveArtifactPath={resolveArtifactPath}
              />
              {renderMessageExtra?.(msg, i)}
              {!live && msg.questions && <QuestionCards questions={msg.questions} onDone={onQuestionAnswered} onClosed={onQuestionClosed} services={questionServices} />}
              </div>
            );
          })}
          {isStreaming && (stream!.questions?.length ?? 0) > 0 && (
            <QuestionCards questions={stream!.questions || []} onDone={(qid) => onQuestionAnswered?.(qid)} onClosed={onQuestionClosed} services={questionServices} />
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-input-inner">{inputBox(false)}</div>
        {footer}
      </div>
    </div>
  );
}
