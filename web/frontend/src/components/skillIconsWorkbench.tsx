import {useId,type ComponentType} from 'react';
import avatar from '../assets/workbench/oil-pig-avatar.jpg';

type Icon=ComponentType<{size?:number}>;
/** Exact approved character pixels, shared by the seven project skill identities. */
const badges:Record<string,string>={
 'content-production':'M1 1h6v6H1zM2 5l1.5-1.5L5 5l1-1 1 2M2 2h2',
 'content-writing':'M1 1h4l2 2v4H1zM5 1v2h2M2.5 4h3M2.5 5.5h2',
 'image-production':'M1 1h6v6H1zM2 5l1.5-1.5L5 5M5.5 2v2M4.5 3h2',
 'delivery-review':'M1.5 4l1.7 1.7L6.5 2.4',
 'publication-analysis':'M1 1v6h6M2.5 5V3.5M4.5 5V2M6.5 5V1',
 'reference-analysis':'M5.3 5.3 7 7M5.8 3.4a2.4 2.4 0 1 1-4.8 0 2.4 2.4 0 0 1 4.8 0M2.3 3.4h2.2',
 'topic-research':'M3 1.2a2 2 0 0 0-1.3 3.5c.5.4.8.8.8 1.3h1c0-.5.3-.9.8-1.3A2 2 0 0 0 3 1.2ZM2.4 7h1.2M6 1v2M5 2h2',
};

const projectIcon=(skillId:string,badge:string):Icon=>function WorkbenchSkillIcon({size=26}){
 const clip=useId();
 return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" data-workbench-skill-icon={skillId}>
  <defs><clipPath id={clip}><rect width="22" height="22" rx="4"/></clipPath></defs>
  <g clipPath={`url(#${clip})`}>
   <svg x="0" y="0" width="22" height="22" viewBox="0 0 1254 1254" preserveAspectRatio="xMidYMid meet">
    <image href={avatar} width="1254" height="1254"/>
   </svg>
  </g>
  <g data-workbench-skill-purpose={skillId}>
   <rect x="14.5" y="14.5" width="9.5" height="9.5" rx="2" fill="var(--surface, white)" stroke="currentColor" strokeWidth=".7"/>
   <path d={badge} transform="translate(15.3 15.3)" stroke="currentColor" strokeWidth="1.05" strokeLinecap="round" strokeLinejoin="round"/>
  </g>
 </svg>;
};
export const workbenchSkillIcons:Record<string,Icon>=Object.fromEntries(Object.entries(badges).map(([id,path])=>[id,projectIcon(id,path)]));
