import {array,record,string} from './models';

/** Publication responses contain artifact objects; writes accept only file IDs. */
export function publicationEvidenceIds(value:unknown):string[]{return [...new Set(array<unknown>(value).map(item=>typeof item==='string'?item:string(record(item).id)).filter(Boolean))]}
export function appendPublicationEvidence(existing:unknown,uploaded:unknown):string[]{return [...new Set([...publicationEvidenceIds(existing),...publicationEvidenceIds(uploaded)])]}
