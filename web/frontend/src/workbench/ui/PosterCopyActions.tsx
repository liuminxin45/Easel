import type {OutputNode} from '../../lib/api';
import {CopyTextButton} from '../../components/CopyableText';

/** The registered poster artifact is first-line title, followed by caption. */
export function posterCopyParts(file:OutputNode, text:string):{title:string;body:string}|null {
 if(file.name!=='标题与配文.txt'||!/^__workbench__\/[A-Za-z0-9_-]+\/标题与配文\.txt$/.test(file.path))return null;
 const match=/^([^\r\n]+)\r?\n(?:\r?\n)?([\s\S]+)$/.exec(text);
 if(!match||!match[1].trim()||!match[2].trim())return null;
 return {title:match[1],body:match[2]};
}

export default function PosterCopyActions({title,body}:{title:string;body:string}) {
 return <div>
  <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:12}}>
   <CopyTextButton label="标题" text={title} showLabel/>
   <CopyTextButton label="正文" text={body} showLabel/>
  </div>
 </div>;
}
