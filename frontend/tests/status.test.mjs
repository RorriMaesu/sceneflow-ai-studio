import {test} from 'node:test';import assert from 'node:assert/strict';
import {productionState} from '../src/production-state.ts';
const project={id:'p',title:'My video',scenes:[{id:'s',title:'Opening'}]};
test('unknown work status never claims that production is ready',()=>assert.equal(productionState(project,[]).paused,null));
test('an explicit task can run in a paused project without implying a resume',()=>{
  const result=productionState(project,[{project_id:'p',scene_id:'s',kind:'video',status:'submitted'}],{paused:1});
  assert.equal(result.paused,true);assert.match(result.label,/Paused/);assert.match(result.detail,/Creating a clip.*Opening/);
});
test('other projects do not affect this projects status',()=>{
  assert.equal(productionState(project,[{project_id:'other',status:'running'}],{paused:0}).label,'Ready for your next step');
  assert.equal(productionState(project,[{project_id:'p',status:'needs_attention'}],{paused:0}).label,'Needs your attention');
});
test('manual control does not suggest that a global resume will produce a video',()=>assert.equal(productionState({...project,mode:'manual'},[],{paused:1}).label,'Manual control'));
