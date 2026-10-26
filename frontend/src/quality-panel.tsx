import {useQuery} from '@tanstack/react-query';
import {request} from './api';
import type {Asset,Project} from './types';

export function AssetQuality({asset,project,act}:{asset:Asset;project:Project;act:any}){
  const reviews=useQuery<any[]>({queryKey:['qa',project.id],queryFn:()=>request(`/api/projects/${project.id}/qa`),refetchInterval:8000});
  const review=reviews.data?.find(r=>r.asset_id===asset.id)?.body;
  const inconsistent=review && review.recommendation==='regenerate' && review.overall_score>=.7;
  return <div className="asset-quality">
    <p className="muted">{asset.approval_source==='user'?'User approved':asset.approval_source==='ai_reviewed'?'Selected after AI review':asset.approved?'Selected by technical checks':'Awaiting your review'}</p>
    {asset.metadata.qa_error && <p role="alert">{asset.metadata.qa_error}</p>}
    <button className="button" onClick={()=>act(()=>request(`/api/assets/${asset.id}/qa`,{model:project.settings.qa_model || 'auto'}),'Local visual review queued for a safe GPU window.')}>Review this asset with AI</button>
    {review && <details><summary>Advisory visual review · {Math.round(review.overall_score*100)}/100 · {inconsistent?'review':review.recommendation}</summary><p>{review.explanation}</p>{(review.consistency_note || inconsistent) && <p role="alert">{review.consistency_note || 'The model gave a high score but recommended regeneration. Review this conflicting advice manually.'}</p>}<p className="muted">{review.qa_model} · {review.confidence} confidence · scores are not calibrated probabilities</p>{review.issues.map((i:any,n:number)=><p key={n}>{i.severity}: {i.description}</p>)}<p>Technical decode: {review.technical_integrity?'passed':'failed'}. Sampled frames: {review.technical.sample_count}.</p><p className="muted">{review.technical.limits}</p></details>}
  </div>
}
