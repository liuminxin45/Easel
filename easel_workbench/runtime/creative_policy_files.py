"""Immutable human-readable policy text; JSON contains references, not duplicates."""
import copy,hashlib
def canonical_policy(document):
 result=copy.deepcopy(document);files={}
 for collection in ('methods','profiles'):
  for row in result[collection]:
   if 'instructions' not in row:continue
   instructions=row.pop('instructions');body='\n'.join(instructions);row['prompt_segments']=[len(part) for part in instructions];sha=hashlib.sha256(body.encode()).hexdigest();relative='规范/创作方案/策略文本/'+sha+'.md'
   row['prompt_file']=relative;row['prompt_sha256']=sha;files[relative]=body
 return result,files

def instructions_from_file(entry,raw):
 text=raw.decode('utf-8-sig');lengths=entry.get('prompt_segments')
 if not lengths:return [text]
 if not isinstance(lengths,list) or any(type(n) is not int or n<0 for n in lengths) or sum(lengths)+len(lengths)-1!=len(text):raise ValueError('提示词段落索引无效')
 result=[];offset=0
 for length in lengths:result.append(text[offset:offset+length]);offset+=length+1
 if '\n'.join(result)!=text:raise ValueError('提示词段落边界无效')
 return result
