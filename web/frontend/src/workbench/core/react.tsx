import React,{createContext,useCallback,useContext,useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {useStore} from 'zustand';
import {createStore} from 'zustand/vanilla';
import {createWorkbenchClient,type ClientOptions,type PendingOperation,type ResourceState,type WorkbenchClient} from './client';
import type {ActivityDelegate,JsonRecord,NavigationDelegate,StudioAction} from './models';

const Context=createContext<{client:WorkbenchClient;navigation?:NavigationDelegate}|null>(null);
const fallbackNavigation:NavigationDelegate={get path(){return typeof location==='undefined'?'/toolbox':location.pathname+location.search},navigate:path=>location.assign(path),replace:path=>location.replace(path),back:()=>history.back()};
export interface CoreProviderProps {children:ReactNode;client?:WorkbenchClient;navigation?:NavigationDelegate;activities?:ActivityDelegate;options?:ClientOptions;autoBoot?:boolean}
export function CoreProvider({children,client:provided,navigation,activities,options,autoBoot=true}:CoreProviderProps){
  const ref=useRef<WorkbenchClient|null>(null);if(!ref.current)ref.current=provided??createWorkbenchClient({...options,navigation,activities});const client=ref.current;
  client.navigation=navigation??client.navigation;
  useEffect(()=>autoBoot?client.usage.bindDOM():undefined,[client,autoBoot]);
  useEffect(()=>{if(!autoBoot)return;let stopped=false;const resume=()=>{if(document.hidden)client.pauseVisible();else void client.resumeVisible()};void client.initialize().then(()=>{if(!stopped)resume()});window.addEventListener('online',resume);window.addEventListener('focus',resume);window.addEventListener('pageshow',resume);document.addEventListener('visibilitychange',resume);return()=>{stopped=true;window.removeEventListener('online',resume);window.removeEventListener('focus',resume);window.removeEventListener('pageshow',resume);document.removeEventListener('visibilitychange',resume);client.pauseVisible()}},[client,autoBoot]);
  // Navigation changes propagate without replacing the business client or draft stores.
  const value=useMemo(()=>({client,navigation:client.navigation}),[client,navigation?.path]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useWorkbench(){
  const context=useContext(Context);if(!context)throw Error('CoreProvider is required');const {client}=context;
  const session=useStore(client.session);
  const persistence=useStore(client.drafts.persistence);
  const navigation=context.navigation??fallbackNavigation;
  return {...session,client,api:client.api,service:client.service,ready:!!session.config&&!session.expired,persistenceError:persistence.error,legacyPending:client.legacyPending(),navigation,navigate:(path:string,options?:Parameters<NavigationDelegate['navigate']>[1])=>navigation.navigate(path,options),replace:(path:string,options?:Parameters<NavigationDelegate['replace']>[1])=>navigation.replace(path,options),back:()=>navigation.back(),refresh:()=>client.refresh()};
}
const emptyResource=createStore<ResourceState>(()=>({data:null,loading:false,error:'',revision:0,stale:false}));
export interface ResourceResult<T> {data:T|null;loading:boolean;error:string;revision:number;reload:()=>Promise<T|null>}
export function useResource<T=JsonRecord>(path:string|null|undefined,options:{interval?:number}={}):ResourceResult<T>{
  const {client}=useWorkbench(),store=useMemo(()=>path?client.resource(path):emptyResource,[client,path]),state=useStore(store);
  const reload=useCallback(()=>path?client.read<T>(path,true):Promise.resolve(null),[client,path]);
  useEffect(()=>{if(!path)return;const unwatch=client.watch(path,options.interval);void client.read<T>(path);return unwatch},[client,path,options.interval]);
  return {...state,data:state.data as T|null,reload};
}
export type DraftPatch<T> = Partial<T>|((previous:T)=>T);
export function useDraft<T extends object>(key:string,initial:T|(()=>T)):[T,(patch:DraftPatch<T>)=>void,()=>void]{
  const {client}=useWorkbench(),initialValue=typeof initial==='function'?(initial as ()=>T)():initial,initialRef=useRef(initialValue);initialRef.current=initialValue;
  const store=useMemo(()=>client.drafts.store<T>(key,initialValue),[client,key]),state=useStore(store);
  useEffect(()=>client.drafts.rebaseReset(key,initialValue),[client,key,initialValue]);
  const patch=useCallback((next:DraftPatch<T>)=>{const previous=store.getState().value,value=typeof next==='function'?(next as(previous:T)=>T)(previous):{...previous,...next};client.drafts.set(key,value)},[client,key,store]);
  const reset=useCallback(()=>client.drafts.reset(key,initialRef.current),[client,key]);
  return [state.value,patch,reset];
}
export interface CommandResult {run:(action:StudioAction,fields?:JsonRecord)=>Promise<JsonRecord>;retry:()=>Promise<JsonRecord>;pending:PendingOperation|null;busy:boolean;error:string;notice:string;clearNotice:()=>void}
export function useCommand(scope='studio'):CommandResult{
  const {client}=useWorkbench(),store=useMemo(()=>client.operation(scope),[client,scope]),state=useStore(store);
  const run=useCallback(async(action:StudioAction,fields:JsonRecord={})=>{const response=await client.mutate<JsonRecord>(scope,'/api/studio/commands',{...fields,action});return (response.result??response) as JsonRecord},[client,scope]);
  const retry=useCallback(async()=>{const response=await client.retry<JsonRecord>(scope);return(response.result??response) as JsonRecord},[client,scope]);
  return {...state,run,retry,clearNotice:()=>store.setState({notice:''})};
}
/** Generic non-Studio mutation status uses the same persistent command identity. */
export function useOperation(scope:string){const {client}=useWorkbench(),store=useMemo(()=>client.operation(scope),[client,scope]),state=useStore(store);return {...state,retry:()=>client.retry(scope)}}
export function useAsyncAction(){const [busy,setBusy]=useState(false),[error,setError]=useState(''),lock=useRef(false);const run=useCallback(async<T,>(action:()=>Promise<T>):Promise<T|undefined>=>{if(lock.current)return undefined;lock.current=true;setBusy(true);setError('');try{return await action()}catch(error){setError(error instanceof Error?error.message:'操作未完成');return undefined}finally{lock.current=false;setBusy(false)}},[]);return {busy,error,run,setError}}

export function useUsage(){return useWorkbench().client.usage}
