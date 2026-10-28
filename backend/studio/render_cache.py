"""Content-addressed, verified render sections. Cache loss only costs recomputation."""
import hashlib,json,os
from . import storage
from .media import probe,run_tool,executable
from .store import encode,uid

RECIPE=2


def digest(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


class RenderCache:
    def __init__(self,job,store,settings):
        self.job=job;self.store=store;self.settings=settings
        self.root=storage.role_folder('cache')/'render-sections-v2'
        storage.reject_links(self.root);self.root.mkdir(parents=True,exist_ok=True)
        self.tool=run_tool([executable('ffmpeg'),'-version']).splitlines()[0]
        self.stats={'reused':0,'rendered':0,'invalid':0,'max_inputs':0,'recipe':RECIPE}

    def section(self,recipe,frames,build,inputs=1):
        key=hashlib.sha256(encode({'recipe_version':RECIPE,'tool':self.tool,'settings':self.settings,'inputs':recipe,'frames':frames}).encode()).hexdigest()
        path=storage.reject_links(self.root/(key+'.mp4'));record=storage.reject_links(self.root/(key+'.json'))
        self.stats['max_inputs']=max(self.stats['max_inputs'],inputs)
        if path.is_file() and record.is_file():
            try:
                if record.stat().st_size>4096:raise ValueError()
                value=json.loads(record.read_text(encoding='utf-8'))
                if value['frames']!=frames or value['sha256']!=digest(path):raise ValueError()
                self.stats['reused']+=1
                return {'path':path,'frames':frames,'key':key}
            except (ValueError,KeyError,OSError):self.stats['invalid']+=1
        storage.require_space(self.root,max(64*1024**2,frames*self.settings['width']*self.settings['height']*.04+frames/self.settings['fps']*192000))
        temporary=storage.reject_links(self.root/(key+'.'+uid()+'.part.mp4'))
        try:
            build(temporary)
            info=probe(temporary)
            if info['frames']!=frames or info['width']!=self.settings['width'] or info['height']!=self.settings['height'] or abs(info['fps']-self.settings['fps'])>.02 or info['audio_streams']!=1:raise ValueError('A rendered section failed its frame, size or audio check. Earlier sections are kept.')
            value={'sha256':digest(temporary),'frames':frames,'bytes':temporary.stat().st_size}
            os.replace(temporary,path)
            note=record.with_name(record.name+'.'+uid()+'.part');note.write_text(encode(value),encoding='utf-8');os.replace(note,record)
            self.stats['rendered']+=1
        finally:temporary.unlink(missing_ok=True)
        return {'path':path,'frames':frames,'key':key}
