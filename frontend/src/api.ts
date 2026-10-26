import { create } from 'zustand'

interface Connection { url:string; token:string; set:(url:string,token:string)=>void; disconnect:()=>void }
const initial = new URLSearchParams(location.hash.slice(1))
export const initialPairCode = initial.get('pair') || ''
if (initialPairCode) history.replaceState(null,'',location.pathname+location.search)
export const useConnection = create<Connection>((set)=>({
  url:localStorage.getItem('sceneflow.agent') || (location.hostname==='127.0.0.1'&&location.port!=='5173'?location.origin:'http://127.0.0.1:8770'),
  token:localStorage.getItem('sceneflow.session') || '',
  set:(url,token)=>{localStorage.setItem('sceneflow.agent',url);localStorage.setItem('sceneflow.session',token);set({url,token})},
  disconnect:()=>{localStorage.removeItem('sceneflow.session');set({token:''})}
}))

export async function request<T=any>(path:string, body?:unknown, method?:string):Promise<T> {
  const {url,token}=useConnection.getState()
  const options:RequestInit & {targetAddressSpace?:string}={method:method || (body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})}, ...(body===undefined?{}:{body:JSON.stringify(body)}),targetAddressSpace:'loopback'}
  let response:Response
  try { response=await fetch(url+path,options) } catch { throw new Error('Your local Studio Agent is not reachable. Start START_STUDIO.bat, or allow local-network access in your browser. The local interface is also available at '+url) }
  if (!response.ok) { const data=await response.json().catch(()=>({detail:response.statusText}));if(response.status===401&&path!=='/api/pair') useConnection.getState().disconnect();throw new Error(typeof data.detail==='string'?data.detail:'Check the highlighted settings and try again.') }
  return response.json()
}

export async function upload(path:string,file:File) {
  const {url,token}=useConnection.getState();const data=new FormData();data.append('file',file)
  const response=await fetch(url+path,{method:'POST',headers:{Authorization:`Bearer ${token}`},body:data, targetAddressSpace:'loopback'} as RequestInit)
  const value=await response.json();if(!response.ok)throw new Error(value.detail);return value
}
