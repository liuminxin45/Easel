/** One read subscription: hidden pages pause, slow reads never overlap. */
export interface VisiblePoll {
  stop: () => void;
  refresh: () => void;
  done: Promise<void>;
}
export interface VisiblePollOptions {
  interval: number;
  maxDelay?: number;
  onError?: (error: unknown, failures: number) => boolean | void;
}
export function visiblePoll(read: () => Promise<boolean | void>, options: VisiblePollOptions): VisiblePoll {
  let stopped=false,running=false,failures=0,timer:ReturnType<typeof setTimeout>|undefined;
  let finish!:()=>void;
  const done=new Promise<void>(resolve=>{finish=resolve});
  const visible=()=>typeof document==='undefined'||!document.hidden;
  const clear=()=>{if(timer!==undefined)clearTimeout(timer);timer=undefined};
  const stop=()=>{if(stopped)return;stopped=true;clear();if(typeof document!=='undefined')document.removeEventListener('visibilitychange',changed);finish()};
  const schedule=(delay=options.interval)=>{clear();if(stopped||running||!visible())return;timer=setTimeout(()=>{timer=undefined;void tick()},delay)};
  const tick=async()=>{
    if(stopped||running||!visible())return;
    running=true;let delay=options.interval;
    try{const keep=await read();failures=0;if(keep===false)stop()}
    catch(error){failures++;delay=Math.min(options.maxDelay??15000,options.interval*2**Math.min(failures,8));if(options.onError?.(error,failures)===false)stop()}
    finally{running=false;if(!stopped)schedule(delay)}
  };
  const refresh=()=>{clear();if(!running&&visible())void tick()};
  function changed(){if(!visible())clear();else refresh()}
  if(typeof document!=='undefined')document.addEventListener('visibilitychange',changed);
  schedule();return {stop,refresh,done};
}
