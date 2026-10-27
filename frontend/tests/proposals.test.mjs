import {test} from 'node:test';import assert from 'node:assert/strict';import {proposalSummary} from '../src/proposal-summary.ts';
const project={title:'My film',settings:{},scenes:[{id:'s',title:'The lantern',body:{duration:2,video_prompt:'Flicker'}}]};
test('a settings proposal shows the named scene and an actual before/after change',()=>{
  const [row]=proposalSummary({body:{actions:[{action:'revise_scene',scene_id:'s',duration:1.5,seed:null}]}},project);
  assert.equal(row.title,'Change The lantern');assert.deepEqual(row.fields,[{label:'Length (seconds)',before:2,after:1.5}]);assert.equal(row.operation,false);
});
test('generation proposals are clearly distinguished from edits',()=>{
  const [row]=proposalSummary({body:{actions:[{action:'regenerate_video',scene_id:'s'}]}},project);
  assert.match(row.title,/another clip.*The lantern/);assert.equal(row.operation,true);assert.equal(row.fields.length,0);
});
