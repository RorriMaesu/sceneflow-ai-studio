import {test} from 'node:test';import assert from 'node:assert/strict';
import {nextStep,neededScenes} from '../src/flow.ts';
const scene=(id)=>({id,body:{},revision_id:'r',assets:[],selected_image_id:null,selected_video_id:null});
const project={id:'p',scenes:[scene('one'),scene('two')],timeline:{clips:[]}};
test('guided next actions respect dependencies and never require choosing a model filename',()=>{
  assert.equal(nextStep({...project,scenes:[]},[]).page,'Storyboard');
  assert.equal(nextStep(project,[]).page,'Image Studio');
  const photos=project.scenes.map(s=>({...s,selected_image_id:'photo',assets:[{id:'photo',approved:1}]}));
  assert.equal(nextStep({...project,scenes:photos},[]).page,'Video Studio');
  assert.equal(neededScenes({...project,scenes:photos},'video').length,2);
  assert.equal(nextStep(project,[{project_id:'p',status:'running'}]).page,'Generation Queue');
});
test('photo review is offered before regenerating an available current candidate',()=>{
  const candidate={...scene('one'),assets:[{id:'a',kind:'image',metadata:{scene_revision_id:'r'}}]};
  assert.equal(neededScenes({...project,scenes:[candidate]},'image').length,0);
  assert.equal(neededScenes({...project,scenes:[candidate]},'video').length,0);
});
