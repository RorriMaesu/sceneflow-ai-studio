"""One admitted sound task in a private environment. No server or automatic downloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import traceback


def offline(*args, **kwargs):
    raise RuntimeError('Network downloads are disabled during creation. Complete this tool’s setup first.')


def chunks(text, limit=180):
    remaining=text.strip()
    while len(remaining)>limit:
        cut=max(remaining.rfind(mark,0,limit) for mark in [' ','.','!','?','。','！','？','\n'])
        cut=cut+1 if cut>=limit//3 else limit
        yield remaining[:cut].strip()
        remaining=remaining[cut:].strip()
    if remaining:yield remaining


def save_audio(path, audio, rate):
    import numpy as np
    import soundfile as sf
    if hasattr(audio,'detach'):audio=audio.detach().float().cpu().numpy()
    audio=np.asarray(audio,dtype=np.float32)
    if not np.isfinite(audio).all() or audio.size==0:
        raise RuntimeError('The model returned empty or invalid sound.')
    if audio.ndim==3:audio=audio[0]
    if audio.ndim==2 and audio.shape[0]<=2:audio=audio.T
    sf.write(str(path),audio,int(rate),subtype='PCM_16')


def graphics_budget(torch):
    # Keep a real allocator ceiling below the display reserve, even if upstream changes.
    torch.cuda.set_per_process_memory_fraction(.84,0)


def speech(body, output):
    import numpy as np
    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel
    graphics_budget(torch)
    torch.manual_seed(int(body.get('seed',0)))
    model=Qwen3TTSModel.from_pretrained(body['pack_path'],device_map='cuda:0',dtype=torch.bfloat16,
                                      attn_implementation='sdpa',local_files_only=True,low_cpu_mem_usage=True)
    results=[]
    for index,text in enumerate(chunks(body['text'])):
        torch.manual_seed(int(body.get('seed',0))+index)
        options={'text':text,'language':body.get('language','English'),'max_new_tokens':1024,'do_sample':True}
        if body['pack_id']=='voices-character':
            options.update(ref_audio=body['reference_path'],ref_text=body.get('reference_text',''),x_vector_only_mode=not bool(body.get('reference_text')))
            waves,rate=model.generate_voice_clone(**options)
        else:
            options.update(speaker=body.get('voice','Ryan'))
            if body.get('delivery'):options['instruct']=body['delivery']
            waves,rate=model.generate_custom_voice(**options)
        segment=output/f'segment-{index:03d}.wav'
        save_audio(segment,waves[0],rate)
        if results:results.append(np.zeros(int(rate*.12),dtype=np.float32))
        results.append(np.asarray(waves[0],dtype=np.float32).reshape(-1))
    save_audio(output/'voice.wav',np.concatenate(results),rate)
    return [{'name':'voice.wav','sample_rate':rate}]


def effects(body, output):
    import torch
    from moss_soundeffect_v2 import MossSoundEffectPipeline
    graphics_budget(torch)
    model=MossSoundEffectPipeline.from_pretrained(body['pack_path'],torch_dtype=torch.bfloat16,device='cuda',local_files_only=True)
    audio=model(prompt=body['prompt'],seconds=float(body['seconds']),num_inference_steps=100,cfg_scale=4.0,seed=int(body.get('seed',0)))
    save_audio(output/'effects.wav',audio,48000)
    return [{'name':'effects.wav','sample_rate':48000}]


def music_view(body):
    """Upstream refreshes support code. Keep its working view separate from pinned weights."""
    source=Path(body['pack_path'])
    view=Path(body['model_view'])
    view.mkdir(parents=True,exist_ok=True)
    for item in source.rglob('*'):
        relative=item.relative_to(source)
        if item.is_symlink():raise RuntimeError('Linked model files cannot be used for generation.')
        if item.is_dir():continue
        destination=view/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():continue
        if item.stat().st_size>32*1024**2:
            # Views are explicitly placed on the model volume, so no duplicate multi-GB weights.
            os.link(item,destination)
        else:
            shutil.copyfile(item,destination)
    return view


def music(body, output):
    import torch
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    from acestep.inference import GenerationParams,GenerationConfig,generate_music
    graphics_budget(torch)
    view=music_view(body)
    os.environ['ACESTEP_CHECKPOINTS_DIR']=str(view)
    os.environ['ACESTEP_LM_BACKEND']='pt'
    dit=AceStepHandler()
    message,success=dit.initialize_service(project_root=str(view.parent),config_path='acestep-v15-turbo',device='cuda',
                                         use_flash_attention=False,compile_model=False,offload_to_cpu=True,
                                         offload_dit_to_cpu=True,quantization=None,vae_checkpoint='official')
    if not success:raise RuntimeError('The music generator could not initialize: '+str(message))
    llm=LLMHandler()
    message,success=llm.initialize(checkpoint_dir=str(view),lm_model_path='acestep-5Hz-lm-1.7B',backend='pt',device='cuda',offload_to_cpu=True,dtype=torch.bfloat16)
    if not success:raise RuntimeError('The music planner could not initialize: '+str(message))
    params=GenerationParams(caption=body['prompt'],lyrics=body.get('lyrics',''),instrumental=bool(body.get('instrumental',True)),
                            duration=float(body['seconds']),seed=int(body.get('seed',0)),inference_steps=8,
                            thinking=True,vocal_language=body.get('language','en'))
    config=GenerationConfig(batch_size=1,allow_lm_batch=False,use_random_seed=False,seeds=[int(body.get('seed',0))],audio_format='wav')
    result=generate_music(dit,llm,params,config,save_dir=str(output))
    if not result.success or not result.audios:
        raise RuntimeError('The music generator did not finish: '+str(result.error or result.status_message))
    original=Path(result.audios[0]['path']).resolve()
    if not original.is_relative_to(output.resolve()) or not original.is_file():
        raise RuntimeError('The music generator did not save an owned sound file.')
    target=output/'music.wav'
    if original!=target:shutil.copyfile(original,target)
    return [{'name':'music.wav'}]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--sha256',required=True)
    args=parser.parse_args()
    raw=Path(args.input).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:
        raise RuntimeError('The frozen creation request changed.')
    body=json.loads(raw)
    if os.environ.get('SCENEFLOW_ADMITTED_JOB')!=body['job_id']:
        raise RuntimeError('Start creation through the Studio queue.')
    output=Path(body['output_dir']).resolve()
    if Path(args.input).resolve().parent!=output or Path(body['result_path']).resolve()!=output/'result.json':
        raise RuntimeError('The request output folder is invalid.')
    socket.socket.connect=offline
    socket.create_connection=offline
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_XET='1',HF_HUB_DISABLE_TELEMETRY='1',TORCHDYNAMO_DISABLE='1')
    result={'job_id':body['job_id'],'nonce':body['nonce']}
    try:
        operation={'speech':speech,'music':music,'effects':effects}.get(body['provider'])
        if operation is None:raise RuntimeError('This creation provider is not supported.')
        result['files']=operation(body,output)
    except Exception as error:
        traceback.print_exc()
        result.update(error='The sound tool could not finish. '+str(error)[:500],error_type=type(error).__name__)
    temporary=output/'result.json.part'
    temporary.write_text(json.dumps(result),encoding='utf-8')
    os.replace(temporary,output/'result.json')
    if result.get('error'):raise SystemExit(1)


if __name__=='__main__':main()
