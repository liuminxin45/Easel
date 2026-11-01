/** Display-only labels. The saved key, contents and resume route stay intact. */
export function localInputTitle(row:Record<string,unknown>):string {
 for(const field of ['title','name','text','material','goal','body']){
  const value=row[field];
  if(typeof value==='string'&&value.trim())return Array.from(value.trim()).slice(0,70).join('');
 }
 const key=typeof row.id==='string'?row.id:'';
 const labels:[RegExp,string][]=[
  [/^chat:/,'会话草稿'],[/^completion-note:/,'采纳说明'],[/^completion:/,'采纳与交付选择'],
  [/^creator:experience(?:$|:)/,'经验整理'],[/^easel:profile-files:/,'画像资料'],
  [/^creator:profile-bindings:/,'画像素材与默认技能'],[/^creator:profile:/,'画像编辑'],
  [/^creator:skill:/,'技能候选编辑'],[/^feedback:/,'作品反馈'],[/^discussion:/,'讨论草稿'],
  [/^review:/,'版本核对'],[/^text-edit:/,'文案修改'],[/^easel:metrics(?:$|:)/,'复盘草稿'],
 ];
 return labels.find(([pattern])=>pattern.test(key))?.[1]||'保留的输入';
}
