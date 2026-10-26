export type Mode = 'manual' | 'hybrid' | 'automatic'
export type Settings = Record<string, any>
export interface Asset { id: string; project_id: string; scene_id: string; job_id: string|null; source_asset_id: string|null; kind: string; sha256: string; metadata: Record<string,any>; approved: number; approval_source: string|null; created: number }
export interface Scene { id:string; project_id:string; title:string; position:number; revision:number; revision_id:string; body:Record<string,any>; selected_image_id:string|null; selected_video_id:string|null; assets:Asset[] }
export interface Project { id:string; title:string; brief:string; mode:Mode; revision:number; settings:Settings; scene_count?:number; scenes:Scene[]; timeline:any; updated:number }
export interface Job { id:string; project_id:string; scene_id:string|null; kind:string; status:string; progress:number; snapshot:Record<string,any>; error:string|null; created:number; dependencies:string[] }
export interface Bootstrap { version:string; phase:string; projects:Project[]; jobs:Job[]; assets:Asset[]; resources:any; services:{comfy:{connected:boolean;version?:string};ollama:{connected:boolean;models:any[]}}; settings:Settings }
export interface Workflow { id:string; name:string; family:string; task:string; status:string; reasons:string[]; capabilities:Record<string,any>; tested?:boolean; graph?:any; mappings?:any }
