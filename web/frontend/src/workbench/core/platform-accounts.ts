import {string} from './models';

export function platformAccountStatus(value:unknown):string{return ({not_connected:'尚未连接',login:'等待扫码',checking:'正在核对',connected:'已连接',account_mismatch:'账号身份不符',identity_unconfirmed:'身份尚未核实',qr_ready:'二维码已就绪',unknown:'状态待核对',unsupported:'未接入',available:'已验证',trial:'待试验'} as Record<string,string>)[string(value)]||'状态待核对'}
