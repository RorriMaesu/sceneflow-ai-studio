import math


def project_settings(values):
    if not isinstance(values,dict):raise ValueError('Project settings must be an object.')
    if 'visual_rules' in values and (not isinstance(values['visual_rules'],str) or len(values['visual_rules'])>6000):raise ValueError('Keep locked visual rules under 6000 characters.')
    bounds={'scene_count':(1,40),'width':(64,2048),'height':(64,2048),'fps':(1,60),'frames':(1,241),'image_steps':(1,60),'candidates':(1,4),'video_attempts':(1,4),'run_budget_minutes':(0,1440),'max_retries':(0,2),'qa_threshold':(0,1)}
    for key,(low,high) in bounds.items():
        if key in values and (not isinstance(values[key],(int,float)) or isinstance(values[key],bool) or not math.isfinite(values[key]) or not low<=values[key]<=high):
            raise ValueError(f'{key} must be between {low} and {high}.')
    for key in ['width','height','fps','frames','image_steps','candidates','video_attempts','max_retries']:
        if key in values and int(values[key])!=values[key]:raise ValueError(f'{key} must be a whole number.')
    for key in ['qa_enabled','qa_auto','qa_regenerate','auto_export','auto_approve_images','auto_approve_videos']:
        if key in values and not isinstance(values[key],bool):raise ValueError(f'{key} must be on or off.')
    enums={'qa_rubric':['lenient','balanced','strict'],'qa_image_mode':['every','selected','suspicious','off'],'qa_video_mode':['every','suspicious','off'],'audio_mode':['silent','preserve','mixed'],'failure_policy':['continue','stop','partial']}
    for key,options in enums.items():
        if key in values and values[key] not in options:raise ValueError('Unsupported '+key)
    if 'gates' in values and (not isinstance(values['gates'],dict) or set(values['gates'])-{'storyboard','prompts','image','video','timeline'} or any(not isinstance(v,bool) for v in values['gates'].values())):
        raise ValueError('Review gates must use the supported stage names and on/off values.')
    for key in ['style_guide','synopsis','characters','visual_rules']:
        if key in values and len(str(values[key]))>12000:raise ValueError('Creative context exceeds the supported length.')
    return values


def scene_body(body):
    if body is None:return
    limits={'image_prompt':6000,'video_prompt':6000,'negative_prompt':2000,'summary':4000,'notes':12000,'start_state':2000,'end_state':2000}
    for key,limit in limits.items():
        if key in body and (not isinstance(body[key],str) or len(body[key])>limit):raise ValueError(f'{key} exceeds its supported text length.')
    if 'duration' in body and (not isinstance(body['duration'],(int,float)) or not math.isfinite(body['duration']) or not 1<=body['duration']<=5):raise ValueError('Use scene durations from one to five seconds for the verified Wan preset.')
    if 'seed' in body and (not isinstance(body['seed'],int) or not 0<=body['seed']<2**63):raise ValueError('Use a whole seed from zero to 2^63−1.')
