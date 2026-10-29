export type PlatformFamily='android'|'windows';
export interface PlatformProfile {family:PlatformFamily;os:'android'|'windows'|'ios'|'macos'|'other';layout:'compact'|'expanded';input:'touch'|'mouse'|'hybrid';display:'browser'|'standalone'|'webview';supportedNative:boolean}
export function detectPlatform(options:{width:number;userAgent:string;platform?:string;touchPoints:number;coarse:boolean;hover:boolean;standalone:boolean;webview:boolean;layout?:'auto'|'compact'|'expanded'}):PlatformProfile{
 const hint=(options.platform||'')+' '+options.userAgent;const os=/android/i.test(hint)?'android':/iphone|ipad|ipod/i.test(hint)||/mac/i.test(hint)&&options.touchPoints>1?'ios':/win/i.test(hint)?'windows':/mac/i.test(hint)?'macos':'other';
 const family:PlatformFamily=os==='android'||os==='ios'?'android':os==='windows'||os==='macos'?'windows':options.coarse&&!options.hover?'android':'windows';
 return {family,os,layout:options.layout&&options.layout!=='auto'?options.layout:options.width<900?'compact':'expanded',input:options.touchPoints&&options.hover?'hybrid':options.coarse?'touch':'mouse',display:options.webview?'webview':options.standalone?'standalone':'browser',supportedNative:os==='android'||os==='windows'};
}
export function browserProfile(layout:'auto'|'compact'|'expanded'='auto'):PlatformProfile{
 const hints=navigator as Navigator&{userAgentData?:{platform?:string};standalone?:boolean};return detectPlatform({width:innerWidth,userAgent:navigator.userAgent,platform:hints.userAgentData?.platform,touchPoints:navigator.maxTouchPoints||0,coarse:matchMedia('(pointer:coarse)').matches,hover:matchMedia('(hover:hover)').matches,standalone:matchMedia('(display-mode:standalone)').matches||!!hints.standalone,webview:/; wv\)|WebToApp/i.test(navigator.userAgent),layout});
}
