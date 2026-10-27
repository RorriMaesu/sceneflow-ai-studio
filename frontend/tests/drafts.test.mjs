import {test} from 'node:test';
import assert from 'node:assert/strict';
import {changed,readDraft,writeDraft,draftConflicts} from '../src/draft-store.ts';
const memory=()=>{const map=new Map();return {getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)}};
const valid=v=>Array.isArray(v?.clips)&&Array.isArray(v?.audio)&&!!v?.settings;
test('a timeline trim survives navigation/reload and remains separate from the saved cut',()=>{
  const storage=memory(),saved={clips:[{trim_in:0,trim_out:2}],audio:[],settings:{fps:30}};
  const draft={...saved,clips:[{trim_in:.0625,trim_out:2}]};
  writeDraft(storage,'timeline.project-a',{version:1,revision:4,value:draft,baseline:saved});
  const restored=readDraft(storage,'timeline.project-a',valid);
  assert.equal(restored.value.clips[0].trim_in,.0625);assert.equal(restored.baseline.clips[0].trim_in,0);assert.equal(restored.revision,4);
  assert.equal(readDraft(storage,'timeline.project-b',valid),null);
  assert.notEqual(restored.revision,5,'a newer server revision must not relabel the old draft');
});
test('undo to the saved cut clears the draft and malformed storage is ignored',()=>{
  const storage=memory(),saved={clips:[],audio:[],settings:{}};
  writeDraft(storage,'a',{version:1,revision:1,value:{...saved,a:1},baseline:saved});
  writeDraft(storage,'a',{version:1,revision:1,value:saved,baseline:saved});assert.equal(readDraft(storage,'a',valid),null);
  storage.setItem('sceneflow.safe-draft.a','{"version":1,"revision":1,"value":{}}');assert.equal(readDraft(storage,'a',valid),null);
  assert.equal(changed(saved,saved),false);
});
test('storage failures are surfaced rather than reported as successful saves',()=>{
  assert.throws(()=>writeDraft({setItem(){throw Error('full')},removeItem(){}},'a',{version:1,revision:1,value:2,baseline:1}),/full/);
});
test('an older cached screen cannot turn a freshly saved draft into a false conflict',()=>{
  assert.equal(draftConflicts(2,1),false);assert.equal(draftConflicts(2,2),false);assert.equal(draftConflicts(2,3),true);
});
test('a save completed after leaving a screen is recognized despite server bookkeeping',()=>{
  const draft={clips:[{trim_in:.0625}],audio:[],settings:{fps:30,manual_edit:false},revision:2};
  const saved={...draft,settings:{fps:30,manual_edit:true},revision:3};
  assert.equal(changed(draft,saved),false);
  assert.equal(changed({...draft,clips:[{trim_in:.125}]},saved),true);
});
