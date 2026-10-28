"""Offline native Qwen ASR/alignment. One admitted worker, sequential GPU stages."""
import argparse,gc,hashlib,json,os,socket,subprocess,traceback
from pathlib import Path

ALIGN_LANGUAGES={'English','Chinese','Cantonese','French','German','Italian','Portuguese','Russian','Spanish'}

def offline(*args,**kwargs):raise RuntimeError('Complete caption setup before creating captions; network access is disabled during inference.')

def progress(body,folder,value,stage):
    temporary=folder/'progress.json.part'
    temporary.write_text(json.dumps({'job_id':body['job_id'],'nonce':body['nonce'],'progress':value,'stage':stage}),encoding='utf-8')
    os.replace(temporary,folder/'progress.json')

def run(body,folder):
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoProcessor,AutoModelForMultimodalLM,AutoModelForTokenClassification
    torch.cuda.set_per_process_memory_fraction(.8,0)
    target=folder/'source.wav'
    subprocess.run([body['ffmpeg'],'-y','-v','error','-protocol_whitelist','file,pipe','-ss',str(body['source_start']),'-t',str(body['seconds']),'-i',body['source_path'],'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(target)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=180,creationflags=0x08000000 if os.name=='nt' else 0)
    audio,rate=sf.read(target,dtype='float32')
    if rate!=16000 or audio.ndim!=1 or not np.isfinite(audio).all():raise RuntimeError('The selected audio could not be prepared for captions.')
    duration=len(audio)/rate
    chunks=[{'start':0.,'end':duration,'text':body['text'],'language':body.get('language') or 'English'}] if body['mode']=='align' else []
    progress(body,folder,.04,'Loading caption tool')
    if body['mode']=='transcribe':
        processor=AutoProcessor.from_pretrained(body['asr_path'],local_files_only=True)
        if processor.feature_extractor.sampling_rate!=rate:raise RuntimeError('The recognition model requires a different sample rate. Run setup again.')
        model=AutoModelForMultimodalLM.from_pretrained(body['asr_path'],dtype=torch.bfloat16,device_map='cuda:0',attn_implementation='sdpa',local_files_only=True).eval()
        count=max(1,int((duration+29.999)//30))
        for index in range(count):
            start=index*30;end=min(duration,start+30);wave=audio[round(start*rate):round(end*rate)]
            inputs=processor.apply_transcription_request(audio=wave,language=body.get('language')).to('cuda',torch.bfloat16)
            with torch.inference_mode():output=model.generate(**inputs,max_new_tokens=512,do_sample=False)
            generated=output[:,inputs['input_ids'].shape[1]:]
            parsed=processor.decode(generated,return_format='parsed')[0]
            text=str(parsed.get('transcription','')).strip()
            if text:chunks.append({'start':start,'end':end,'text':text,'language':parsed.get('language') or body.get('language') or 'English'})
            del inputs,output,generated
            (folder/'recognition.partial.json').write_text(json.dumps(chunks,ensure_ascii=False),encoding='utf-8')
            progress(body,folder,.1+.35*(index+1)/count,'Recognizing recording')
        del model,processor
        gc.collect();torch.cuda.empty_cache()
        if torch.cuda.memory_allocated()>512*1024**2:raise RuntimeError('The recognition model did not release its memory before word timing.')
    if not chunks:raise RuntimeError('No speech was recognized. Choose a clearer recording; your audio is unchanged.')
    use_timing=bool(body.get('word_timing')) and not body.get('is_music') and all(c['language'] in ALIGN_LANGUAGES for c in chunks)
    words=[]
    if use_timing:
        progress(body,folder,.5,'Loading word timing tool')
        processor=AutoProcessor.from_pretrained(body['aligner_path'],local_files_only=True)
        if processor.feature_extractor.sampling_rate!=rate:raise RuntimeError('The timing model requires a different sample rate. Run setup again.')
        model=AutoModelForTokenClassification.from_pretrained(body['aligner_path'],dtype=torch.bfloat16,device_map='cuda:0',attn_implementation='sdpa',local_files_only=True).eval()
        for index,chunk in enumerate(chunks):
            wave=audio[round(chunk['start']*rate):round(chunk['end']*rate)]
            inputs,word_lists=processor.prepare_forced_aligner_inputs(audio=wave,transcript=chunk['text'],language=chunk['language'])
            inputs=inputs.to('cuda',torch.bfloat16)
            with torch.inference_mode():output=model(**inputs)
            timings=processor.decode_forced_alignment(logits=output.logits,input_ids=inputs['input_ids'],word_lists=word_lists,timestamp_token_id=model.config.timestamp_token_id)[0]
            for item in timings:
                start=max(0.,float(item['start_time']))+chunk['start'];end=min(chunk['end'],float(item['end_time'])+chunk['start'])
                if end>start:words.append({'start':start,'end':end,'text':str(item['text'])})
            del inputs,output
            progress(body,folder,.55+.35*(index+1)/len(chunks),'Matching words to speech')
        del model,processor;gc.collect();torch.cuda.empty_cache()
    items=[]
    if words:
        group=[]
        for word in words:
            if group and (len(' '.join(x['text'] for x in group))+len(word['text'])>72 or word['end']-group[0]['start']>6 or word['start']-group[-1]['end']>.6):
                items.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(x['text'] for x in group)});group=[]
            group.append(word)
        if group:items.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(x['text'] for x in group)})
    else:items=[{'start':c['start'],'end':c['end'],'text':c['text']} for c in chunks]
    result={'items':items,'words':words,'chunks':chunks,'duration':duration,'word_timing':bool(words),'timing_note':'Word times were inferred and need review.' if words else 'Times cover recognition chunks only. Adjust lyric/caption timing manually; no word-level timing is claimed.'}
    (folder/'captions.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    progress(body,folder,.95,'Caption draft ready for validation')
    return [{'name':'captions.json'}]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--sha256',required=True);args=parser.parse_args()
    raw=Path(args.input).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:raise RuntimeError('The frozen caption request changed.')
    body=json.loads(raw);folder=Path(body['output_dir']).resolve()
    if os.environ.get('SCENEFLOW_ADMITTED_JOB')!=body['job_id'] or Path(args.input).resolve().parent!=folder or Path(body['result_path']).resolve()!=folder/'result.json':raise RuntimeError('Start caption creation through the Studio queue.')
    socket.socket.connect=offline;socket.create_connection=offline
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TORCHDYNAMO_DISABLE='1')
    result={'job_id':body['job_id'],'nonce':body['nonce']}
    try:result['files']=run(body,folder)
    except Exception as error:traceback.print_exc();result.update(error='Caption creation could not finish. '+str(error)[:600],error_type=type(error).__name__)
    temporary=folder/'result.json.part';temporary.write_text(json.dumps(result),encoding='utf-8');os.replace(temporary,folder/'result.json')
    if result.get('error'):raise SystemExit(1)

if __name__=='__main__':main()
