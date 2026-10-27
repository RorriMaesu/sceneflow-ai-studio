import copy
import hashlib
import json
from pathlib import Path

import httpx

from .config import ROOT, settings
from .store import db, encode, now


def node(kind, **inputs):
    return {'class_type': kind, 'inputs': inputs}


def qwen_graph(s, prefix):
    return {
        'model': node('UNETLoader', unet_name='qwen_image_2.1_int8_convrot.safetensors', weight_dtype='default'),
        'clip': node('CLIPLoader', clip_name='qwen3vl_8b_int8_convrot.safetensors', type='qwen_image', device='default'),
        'text': node('TextEncodeQwenImage21', clip=['clip', 0], prompt=s['positive_prompt'], negative_prompt=s.get('negative_prompt', ''), resolution=1024, images={}),
        'vae': node('VAELoader', vae_name='qwen_image_2.1_vae_bf16.safetensors'),
        'latent': node('EmptyLatentImage', width=s['width'], height=s['height'], batch_size=1),
        'sample': node('KSampler', model=['model', 0], seed=s['seed'], steps=s.get('image_steps', 12), cfg=1.0, sampler_name='euler', scheduler='simple', positive=['text', 0], negative=['text', 1], latent_image=['latent', 0], denoise=1.0),
        'decode': node('VAEDecode', samples=['sample', 0], vae=['vae', 0]),
        'save': node('SaveImage', images=['decode', 0], filename_prefix=prefix),
    }


def wan_graph(s, prefix, image):
    graph = {
        'image': node('LoadImage', image=image),
        'clip': node('CLIPLoader', clip_name='umt5_xxl_fp8_e4m3fn_scaled.safetensors', type='wan', device='default'),
        'positive': node('CLIPTextEncode', clip=['clip', 0], text=s['positive_prompt']),
        'negative': node('CLIPTextEncode', clip=['clip', 0], text=s.get('negative_prompt', '')),
        'vae': node('VAELoader', vae_name='wan_2.1_vae.safetensors'),
        'condition': node('WanImageToVideo', positive=['positive', 0], negative=['negative', 0], vae=['vae', 0], width=s['width'], height=s['height'], length=s['frames'], batch_size=1, start_image=['image', 0]),
        'decode': node('VAEDecode', samples=['low_sample', 0], vae=['vae', 0]),
        'video': node('CreateVideo', images=['decode', 0], fps=s['fps']),
        'save': node('SaveVideo', video=['video', 0], filename_prefix=prefix, format='mp4', codec='h264'),
    }
    for stage, start, end in [('high', 0, 2), ('low', 2, 4)]:
        graph[stage+'_model'] = node('UNETLoader', unet_name=f'wan2.2_i2v_{stage}_noise_14B_fp8_scaled.safetensors', weight_dtype='default')
        graph[stage+'_lora'] = node('LoraLoaderModelOnly', model=[stage+'_model', 0], lora_name=f'wan2.2_i2v_lightx2v_4steps_lora_v1_{stage}_noise.safetensors', strength_model=1.0)
        graph[stage+'_shift'] = node('ModelSamplingSD3', model=[stage+'_lora', 0], shift=5.0)
        graph[stage+'_sample'] = node('KSamplerAdvanced', model=[stage+'_shift', 0], positive=['condition', 0], negative=['condition', 1], latent_image=['condition', 2] if stage == 'high' else ['high_sample', 0], add_noise='enable' if stage == 'high' else 'disable', noise_seed=s['seed'] if stage == 'high' else 0, steps=4, cfg=1.0, sampler_name='euler', scheduler='simple', start_at_step=start, end_at_step=end, return_with_leftover_noise='enable' if stage == 'high' else 'disable')
    return graph


def qwen_reference_graph(s,prefix,images,mask=None):
    graph=qwen_graph(s,prefix)
    graph['text']['inputs'].pop('images',None)
    graph['text']['inputs'].update(vae=['vae',0],resolution=0)
    for index,image in enumerate(images[:3]):
        key='reference_'+str(index+1);graph[key]=node('LoadImage',image=image)
        graph[key+'_scale']=node('ImageScale',image=[key,0],upscale_method='lanczos',width=s['width'] if index==0 else 512,height=s['height'] if index==0 else 0,crop='disabled')
        graph['text']['inputs']['images.image_'+str(index+1)]=[key+'_scale',0]
    graph['sample']['inputs']['latent_image']=['text',2]
    graph.pop('latent')
    if mask:
        graph['mask_load']=node('LoadImage',image=mask)
        graph['mask']=node('ImageToMask',image=['mask_load',0],channel='red')
        graph['edit_latent']=node('VAEEncode',pixels=['reference_1_scale',0],vae=['vae',0])
        graph['edit_noise_mask']=node('SetLatentNoiseMask',samples=['edit_latent',0],mask=['mask',0])
        graph['sample']['inputs'].update(latent_image=['edit_noise_mask',0],denoise=s.get('edit_strength',.6))
        graph['composite']=node('ImageCompositeMasked',destination=['reference_1_scale',0],source=['decode',0],x=0,y=0,resize_source=False,mask=['mask',0])
        graph['save']['inputs']['images']=['composite',0]
    return graph


BUILTINS = [
    {'id':'qwen-image-21-reference','name':'Qwen Image 2.1 · References & correction','family':'Qwen Image 2.1','task':'text_to_image','capabilities':{'negative_prompt':True,'reference_images':True,'image_editing':True,'masked_composite':True,'audio':False},'constraints':{'multiple':32,'max_width':2048,'max_height':2048},'mappings':{},'output_nodes':['save']},
    {'id': 'qwen-image-21', 'name': 'Qwen Image 2.1 · INT8', 'family': 'Qwen Image 2.1', 'task': 'text_to_image', 'capabilities': {'negative_prompt': True, 'reference_images': False, 'image_editing':False, 'audio': False}, 'constraints': {'multiple': 32, 'max_width': 2048, 'max_height': 2048}, 'mappings': {}, 'output_nodes': ['save']},
    {'id': 'wan22-i2v', 'name': 'Wan 2.2 · I2V A14B FP8', 'family': 'Wan 2.2', 'task': 'image_to_video', 'capabilities': {'negative_prompt': True, 'source_image': True, 'audio': False, 'first_last_frame': False}, 'constraints': {'multiple': 16, 'frames_multiple': 4, 'frames_offset': 1, 'max_width': 832, 'max_height': 480, 'max_frames': 81}, 'mappings': {}, 'output_nodes': ['save']},
]
DUMMY = {'positive_prompt': '', 'negative_prompt': '', 'width': 640, 'height': 352, 'seed': 1, 'frames': 49, 'fps': 16}
SAFE_NODES = {'SetLatentNoiseMask', 'ImageToMask', 'ImageCompositeMasked', 'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode', 'TextEncodeQwenImage21', 'EmptyLatentImage', 'EmptySD3LatentImage', 'WanImageToVideo', 'KSampler', 'KSamplerAdvanced', 'ModelSamplingSD3', 'LoraLoaderModelOnly', 'VAEDecode', 'VAEDecodeTiled', 'LoadImage', 'SaveImage', 'SaveImageAdvanced', 'CreateVideo', 'SaveVideo', 'CheckpointLoaderSimple', 'VAEEncode', 'ImageScale', 'CLIPVisionLoader', 'CLIPVisionEncode', 'WanFirstLastFrameToVideo', 'LoadAudio', 'SaveAudio', 'LTXVImgToVideo', 'LTXVConditioning', 'LTXVScheduler', 'SamplerCustomAdvanced', 'RandomNoise', 'KSamplerSelect', 'CFGGuider', 'BasicGuider', 'LoraLoader'}


def graph_hash(graph):
    return hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_graph(graph, info, output_nodes):
    reasons = []
    if not isinstance(graph, dict) or not 1 <= len(graph) <= 250:
        return ['Import API-format workflow JSON containing 1–250 nodes.']
    if not output_nodes or any(key not in graph for key in output_nodes):
        reasons.append('Select valid output nodes in the mapping editor.')
    for key, item in graph.items():
        if not isinstance(key,str) or not isinstance(item,dict) or not isinstance(item.get('inputs'),dict):
            reasons.append('Workflow nodes need string IDs, class_type and an input object.')
            continue
        kind = item.get('class_type')
        if kind not in SAFE_NODES:
            reasons.append(f'{kind}: this node is not in the local execution allowlist.')
            continue
        schema = info.get(kind)
        if not schema:
            reasons.append(f'{kind}: required node is not installed.')
            continue
        inputs = item.get('inputs', {})
        if key in output_nodes and not schema.get('output_node',False):
            reasons.append(f'{kind}: selected output node does not save media.')
        for name, spec in schema.get('input', {}).get('required', {}).items():
            if name not in inputs:
                if name == 'images' and kind == 'TextEncodeQwenImage21':
                    continue
                reasons.append(f'{kind}: missing required input {name}.')
        for name, value in inputs.items():
            spec = {**schema.get('input', {}).get('required', {}), **schema.get('input', {}).get('optional', {})}.get(name)
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if value[0] not in graph:
                    reasons.append(f'{kind}: input {name} references a missing node.')
            elif spec and isinstance(spec[0], list) and value not in spec[0] and not (kind=='LoadImage' and name=='image'):
                reasons.append(f'{kind}: selected {name} is not available ({value}).')
    return list(dict.fromkeys(reasons))


class Registry:
    def __init__(self):
        self.info = {}

    async def discover(self):
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(settings['comfy_url']+'/object_info')
            response.raise_for_status()
            self.info = response.json()
        for entry in BUILTINS:
            previous = db.one('SELECT body FROM workflow_registry WHERE id=?', (entry['id'],))
            preview=qwen_reference_graph(DUMMY,'sceneflow/preview',['reference.png']) if entry['id']=='qwen-image-21-reference' else qwen_graph(DUMMY,'sceneflow/preview') if entry['task']=='text_to_image' else wan_graph(DUMMY,'sceneflow/preview','example.png')
            data = {**entry, 'graph': preview}
            if previous:
                old = json.loads(previous['body'])
                data['tested'] = old.get('tested', False) and old.get('workflow_hash') == graph_hash(data['graph'])
            data['reasons'] = validate_graph(data['graph'], self.info, data['output_nodes'])
            data['status'] = 'ready' if not data['reasons'] else 'unavailable'
            data['workflow_hash'] = graph_hash(data['graph'])
            db.execute('INSERT OR REPLACE INTO workflow_registry VALUES(?,?,?)', (data['id'], encode(data), now()))
        for entry in self.list():
            if entry.get('imported'):
                entry['reasons'] = validate_graph(entry['graph'], self.info, entry['output_nodes'])+validate_media_mappings(entry)
                entry['status'] = 'ready' if not entry['reasons'] else 'unavailable'
                db.execute('UPDATE workflow_registry SET body=?,updated=? WHERE id=?', (encode(entry), now(), entry['id']))
        db.event('workflows.discovered', {'count': len(self.list())})
        return self.list()

    def list(self):
        return [json.loads(row['body']) for row in db.all('SELECT body FROM workflow_registry ORDER BY id')]

    def get(self, identifier):
        row = db.one('SELECT body FROM workflow_registry WHERE id=?', (identifier,))
        if not row:
            raise ValueError('The selected workflow has not been discovered. Refresh the Model Library.')
        return json.loads(row['body'])

    def build(self, identifier, snapshot, prefix, image=None, references=None, mask=None):
        entry = copy.deepcopy(snapshot.get('workflow_definition') or self.get(identifier))
        if entry['status'] != 'ready':
            raise ValueError('The selected workflow is unavailable: '+'; '.join(entry['reasons']))
        c = entry['constraints']
        w, h = snapshot['width'], snapshot['height']
        if w % c['multiple'] or h % c['multiple'] or w > c.get('max_width', 2048) or h > c.get('max_height', 2048):
            raise ValueError('Resolution is outside this verified workflow preset. Use dimensions supported by the Model Library.')
        if entry['task'] == 'image_to_video' and (snapshot['frames'] > c.get('max_frames', 81) or (snapshot['frames']-c.get('frames_offset', 0)) % c.get('frames_multiple', 1)):
            raise ValueError('The frame count does not match this workflow’s validated limits.')
        if identifier == 'qwen-image-21-reference':
            graph=qwen_reference_graph(snapshot,prefix,references or ['reference.png'],mask)
        elif identifier == 'qwen-image-21':
            graph = qwen_graph(snapshot, prefix)
        elif identifier == 'wan22-i2v':
            if not image:
                raise ValueError('Choose a starting still before animation.')
            graph = wan_graph(snapshot, prefix, image)
        else:
            graph = copy.deepcopy(entry['graph'])
            media_reasons=validate_media_mappings(entry)
            if media_reasons:raise ValueError('; '.join(media_reasons))
            values = {**snapshot, 'source_image': image, 'output_prefix': prefix}
            for key, mapping in entry['mappings'].items():
                if key in values and values[key] is not None:
                    for target in mapping if isinstance(mapping, list) else [mapping]:
                        graph[target['node']]['inputs'][target['input']] = values[key]
        for key in entry['output_nodes']:
            graph[key]['inputs']['filename_prefix'] = prefix
        return graph, entry

    def verified(self, identifier, evidence):
        entry = self.get(identifier)
        entry.update(tested=True, last_generation=evidence, verified_at=now())
        db.execute('UPDATE workflow_registry SET body=?,updated=? WHERE id=?', (encode(entry), now(), identifier))


registry = Registry()


def validate_media_mappings(entry):
    reasons=[];graph=entry.get('graph',{});mappings=entry.get('mappings',{})
    targets=mappings.get('source_image',[]) if isinstance(mappings,dict) else []
    targets=targets if isinstance(targets,list) else [targets]
    for key,value in graph.items():
        if not isinstance(value,dict):continue
        if value.get('class_type')=='LoadAudio':reasons.append('Audio conditioning requires a separately verified adapter; imported sound can be mixed in the timeline.')
        if value.get('class_type')=='LoadImage' and (entry.get('task')!='image_to_video' or not any(isinstance(t,dict) and t.get('node')==key and t.get('input')=='image' for t in targets)):
            reasons.append('Every image loader must use the exact registered source_image mapping. Static reference/editing inputs are not supported by this adapter.')
    return reasons
