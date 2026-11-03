import {createContext,useContext,type ReactNode} from 'react';

const Context=createContext(true);
/** A closed private section pauses reads without unmounting its draft owners. */
export function useResourceVisibility():boolean{return useContext(Context)}
export function ResourceVisibility({visible,children}:{visible:boolean;children:ReactNode}){
 const parent=useResourceVisibility();
 return <Context.Provider value={parent&&visible}>{children}</Context.Provider>;
}
