"""Bounded dialogue drafts use the shared planner and require explicit review."""
import hashlib,json,httpx
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from .store import db,encode,uid,now,Conflict
from .security import require_session
from . import script_audio

router=APIRouter(prefix='/api/projects')


def migrate():
    script_audio.migrate(db)
    db.execute('CREATE TABLE IF NOT EXISTS script_proposals(id TEXT PRIMARY KEY,project_id TEXT,job_id TEXT,signature TEXT,body TEXT,status TEXT,created REAL)')


def signature(project_id,con=None):
    scope=script_audio.cast_scope(project_id)
    def read(connection):
        value={table:[dict(r) for r in connection.execute(sql,args)] for table,sql,args in [
            ('cast','SELECT id,name,voice,language,revision FROM cast_members WHERE project_id=? ORDER BY id',(scope,)),
            ('lines','SELECT id,text,cast_id,revision FROM script_lines WHERE project_id=? ORDER BY created,id',(project_id,)),
            ('scenes','SELECT id,revision FROM scenes WHERE project_id=? ORDER BY id',(project_id,)),
            ('project','SELECT revision FROM projects WHERE id=?',(project_id,))]}
        if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='productions'").fetchone():
            value['shared']=[dict(r) for r in connection.execute('SELECT canon,revision FROM productions WHERE root_project_id=?',(scope,))]
        return hashlib.sha256(encode(value).encode()).hexdigest()
    if con:return read(con)
    with db.connect() as connection:return read(connection)


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Character(Strict):
    name:str=Field(min_length=1,max_length=100)
    voice:str=Field(pattern='^(Ryan|Aiden|Vivian|Serena|Dylan|Eric|Uncle_Fu|Ono_Anna|Sohee)$')
class Dialogue(Strict):
    speaker:str=Field(max_length=100)
    text:str=Field(min_length=1,max_length=600)
class Script(Strict):
    characters:list[Character]=Field(max_length=6)
    lines:list[Dialogue]=Field(min_length=1,max_length=40)
class Request(Strict):
    model:str=Field(min_length=1,max_length=200)
    instruction:str=Field(default='',max_length=3000)
    count:int=Field(default=8,ge=1,le=40)


@router.get('/{identifier}/script-drafts')
async def drafts(identifier:str,session=Depends(require_session)):
    migrate();db.project(identifier)
    return [{**r,'body':json.loads(r['body'])} for r in db.all("SELECT * FROM script_proposals WHERE project_id=? AND status='pending' ORDER BY created DESC",(identifier,))]
@router.post('/{identifier}/script-drafts')
async def propose(identifier:str,body:Request,session=Depends(require_session)):
    from .director import context,model_details
    from .production import queue_snapshot
    migrate();project=db.project(identifier);await model_details(body.model)
    cast=script_audio.view(identifier)
    snap={'project_id':identifier,'scene_id':None,'signature':signature(identifier),'context':context(project),'cast':cast['cast'],'existing_lines':[{k:l[k] for k in ['cast_id','text']} for l in cast['lines'][-12:]],**body.model_dump(),'manual_override':True,'manual_requested_at':now()}
    return {'job_id':queue_snapshot('script',snap)['id']}


async def execute(job,snapshot):
    from .director import structured,prepare_gpu,unload
    from .production import update_job
    migrate()
    async with httpx.AsyncClient(timeout=30) as client:
        if reason:=await prepare_gpu(client,snapshot['model']):
            update_job(job['id'],'queued',error=reason);return
        update_job(job['id'],'running',started=now(),error=None)
        try:
            result=await structured(client,snapshot['model'],[{'role':'system','content':'Draft short spoken dialogue or narration for the selected sequence. Use the shared story guide and existing characters. Return exactly count lines, each up to 600 characters. Append after existing_lines. Reuse existing character names exactly; propose only needed new characters with available preset voices. Empty speaker means narrator. Do not include stage directions inside spoken text. This draft does not generate audio or change any script.'},{'role':'user','content':encode({k:snapshot[k] for k in ['context','cast','existing_lines','instruction','count']})}],Script,{'num_predict':6000})
            names={c['name'].casefold() for c in snapshot['cast']}
            # Some planners repeat the supplied cast in this list. Reuse those
            # characters and their saved voices rather than adding duplicates.
            result.characters=[c for c in result.characters if c.name.casefold() not in names]
            added=[c.name.casefold() for c in result.characters]
            if len(set(added))!=len(added) or any(n in names for n in added):raise ValueError('The draft duplicated an existing character. No script was changed; try again.')
            names.update(added)
            if len(result.lines)!=snapshot['count'] or any(l.speaker and l.speaker.casefold() not in names for l in result.lines):raise ValueError('The draft contains an unknown speaker or wrong line count. No script was changed.')
            db.execute('INSERT INTO script_proposals VALUES(?,?,?,?,?,?,?)',(uid(),job['project_id'],job['id'],snapshot['signature'],encode(result.model_dump()),'pending',now()))
        finally:await unload(client,snapshot['model'])
    update_job(job['id'],'completed',progress=1,finished=now())


@router.post('/{identifier}/script-drafts/{proposal_id}/apply')
async def apply(identifier:str,proposal_id:str,session=Depends(require_session)):
    migrate();db.project(identifier);scope=script_audio.cast_scope(identifier)
    with db.connect(True) as con:
        row=con.execute("SELECT * FROM script_proposals WHERE id=? AND project_id=? AND status='pending'",(proposal_id,identifier)).fetchone()
        if not row or row['signature']!=signature(identifier,con):raise Conflict('The script, cast or story changed. Request a fresh draft before adding it.')
        value=Script.model_validate_json(row['body'])
        cast={r['name'].casefold():r['id'] for r in con.execute('SELECT id,name FROM cast_members WHERE project_id=?',(scope,))}
        for character in value.characters:
            if character.name.casefold() in cast:raise Conflict('That character was added after the draft. Request a fresh draft.')
            key=uid();cast[character.name.casefold()]=key
            con.execute('INSERT INTO cast_members VALUES(?,?,?,?,?,?,?)',(key,scope,character.name,character.voice,'English',1,now()))
        for i,line in enumerate(value.lines):
            speaker=cast.get(line.speaker.casefold()) if line.speaker else None
            if line.speaker and not speaker:raise ValueError('The script names a character outside this production.')
            con.execute('INSERT INTO script_lines VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),identifier,None,speaker,line.text,0,1,None,now()+i*.00001,1))
        con.execute("UPDATE script_proposals SET status='applied' WHERE id=?",(proposal_id,))
    script_audio.retime(identifier)
    return script_audio.view(identifier)
