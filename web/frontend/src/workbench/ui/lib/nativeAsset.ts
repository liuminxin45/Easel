/** Resolve the original Easel artwork from this exact immutable frontend. */
export function nativeAsset(path:string):string {
 const release=typeof document==='undefined'?undefined:document.querySelector<HTMLMetaElement>('meta[name="native-release"]')?.content;
 return release?'/native-assets/'+release+'/'+path:'./'+path;
}
