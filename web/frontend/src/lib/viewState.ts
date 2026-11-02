import {useCallback,useRef,useState,type Dispatch,type SetStateAction} from 'react';

/** Optional host storage for navigation metadata; never a business-data cache. */
export interface ViewStateStore<T> {read():T|null;write(value:T):void}
/** Unsent user input may use the host's existing approved draft repository. */
export interface DraftStore<T> extends ViewStateStore<T> {remove():void}

export function useStoredViewState<T>(store:ViewStateStore<T>|undefined,initial:()=>T):[T,Dispatch<SetStateAction<T>>]{
 const owner=useRef(store),[state,setState]=useState<T>(()=>store?.read()??initial()),current=useRef(state);
 if(owner.current!==store){owner.current=store;const next=store?.read()??initial();current.current=next;setState(next)}
 else current.current=state;
 const update=useCallback<Dispatch<SetStateAction<T>>>(value=>{
  const next=typeof value==='function'?(value as (previous:T)=>T)(current.current):value;
  current.current=next;store?.write(next);setState(next);
 },[store]);
 return [state,update];
}
