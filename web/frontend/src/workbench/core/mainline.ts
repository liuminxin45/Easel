import {array,record,string,type JsonRecord,type Version,type Work} from './models';
import type {DraftRepository} from './persistence';

function canonical(value:unknown):unknown{if(Array.isArray(value))return value.map(canonical);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([,child])=>child!==undefined).sort(([a],[b])=>a.localeCompare(b)).map(([key,child])=>[key,canonical(child)]));return value}
/** Inputs only: storage bookkeeping is irrelevant; attachment and operation IDs are not. */
export function draftFingerprint(value:unknown):string{return JSON.stringify(canonical(Object.fromEntries(Object.entries(record(value)).filter(([key])=>key!=='id'&&key!=='updatedAt'))))}
export function unchangedDraft(repository:Pick<DraftRepository,'get'>,key:string,frozen:unknown):boolean{const current=repository.get(key);return current!==null&&draftFingerprint(current)===draftFingerprint(frozen)}
export function discussionBase(work:Pick<Work,'versions'>,round:JsonRecord,scope=''):Version|undefined{return work.versions.find(version=>version.status==='completed'&&version.id===(scope||string(round.candidate_id)))||work.versions.filter(version=>version.status==='completed').at(-1)}
export function appendDiscussionDirection(original:unknown,reply:unknown):string{const before=string(original),direction=string(reply);return before+(before?'\n\n':'')+'已选讨论方向：\n'+direction}
export function publicationContextPath(workId:string,versionId='',publicationId='',register=false):string{return '/toolbox?'+new URLSearchParams({section:'publications',...(workId?{work:workId}:{}),...(versionId?{version:versionId}:{}),...(publicationId?{item:publicationId}:{}),...(register?{register:'1'}:{})})}
