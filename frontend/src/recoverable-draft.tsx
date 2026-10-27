import {useEffect, useState} from 'react';
import {changed,readDraft,writeDraft} from './draft-store';

export function useRecoverableDraft<T>(key:string, server:T, revision:number, valid:(v:any)=>boolean){
  const [record,setRecord]=useState(()=>{
    try {return readDraft<T>(localStorage,key,valid)||{version:1 as const,value:server,baseline:server,revision};}
    catch {return {version:1 as const,value:server,baseline:server,revision};}
  });
  const [storageError,setStorageError]=useState('');
  const dirty=changed(record.value,record.baseline);
  const conflict=dirty&&record.revision!==revision;
  useEffect(()=>{
    try {writeDraft(localStorage,key,record);setStorageError('');}
    catch {setStorageError('This browser could not protect your draft. Save your changes before leaving this screen.');}
  },[key,record]);
  useEffect(()=>{
    if(!dirty&&revision>record.revision)setRecord({version:1,value:server,baseline:server,revision});
  },[revision,dirty]);
  useEffect(()=>{
    if(!dirty||!storageError)return;
    const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};
    window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
  },[dirty,storageError]);
  const setValue=(next:T|((old:T)=>T))=>setRecord(r=>({...r,value:typeof next==='function'?(next as (v:T)=>T)(r.value):next}));
  const adopt=(value:T,base:number)=>setRecord({version:1,value,baseline:value,revision:base});
  return {value:record.value,setValue,revision:record.revision,dirty,conflict,storageError,adopt,discard:()=>adopt(server,revision)};
}

export function DraftNotice({draft,savedLabel='All changes saved to your local studio.'}:{draft:{dirty:boolean;conflict:boolean;storageError:string;discard:()=>void};savedLabel?:string}){
  return <div className={'draft-notice'+(draft.conflict||draft.storageError?' draft-warning':'')}>
    <p role={draft.conflict||draft.storageError?'alert':'status'}>{draft.storageError|| (draft.conflict?'A newer saved version exists. Your draft is protected here. Review it before replacing or discarding anything.':draft.dirty?'Draft protected in this browser · save to apply your changes.':savedLabel)}</p>
    {draft.dirty&&<button className="button" onClick={draft.discard}>Discard draft and use saved version</button>}
  </div>
}
