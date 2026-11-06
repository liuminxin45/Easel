/** Gesture recognition only; native scrolling and session commands stay with their owners. */
export class SessionPress {
 private pending?:{id:number;x:number;y:number;timer:ReturnType<typeof setTimeout>};
 private blocked?:{id:number;until:number};
 constructor(private clock=Date.now,private schedule=(callback:()=>void,delay:number)=>setTimeout(callback,delay),private unschedule=(timer:ReturnType<typeof setTimeout>)=>clearTimeout(timer)){}
 begin(id:number,x:number,y:number,open:()=>void){
  this.cancel();this.blocked=undefined;
  const timer=this.schedule(()=>{if(this.pending?.id!==id)return;this.pending=undefined;this.blocked={id,until:Infinity};open()},450);
  this.pending={id,x,y,timer};
 }
 move(id:number,x:number,y:number){const p=this.pending;if(p?.id===id&&Math.hypot(x-p.x,y-p.y)>8)this.cancel()}
 end(id:number){if(this.pending?.id===id)this.cancel();if(this.blocked?.id===id)this.blocked.until=this.clock()+1000}
 nextPointer(){this.cancel();this.blocked=undefined}
 cancel(){if(this.pending)this.unschedule(this.pending.timer);this.pending=undefined}
 blocksClick(id?:number){const p=this.blocked;return !!p&&this.clock()<=p.until&&(id===undefined||id===p.id)}
 consumeClick(id?:number){if(!this.blocksClick(id))return false;this.blocked=undefined;return true}
}
