import { createClient } from "@supabase/supabase-js";
export const supabase = createClient(import.meta.env.VITE_SUPABASE_URL ?? "", import.meta.env.VITE_SUPABASE_ANON_KEY ?? "", { auth: { persistSession:true, autoRefreshToken:true, detectSessionInUrl:true } });
export const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/,"");
export async function api<T>(path:string, token:string, options:RequestInit={}) {
  const response=await fetch(`${API_URL}${path}`,{...options,headers:{"Content-Type":"application/json","Authorization":`Bearer ${token}`,...(options.headers??{})}});
  const body=await response.json().catch(()=>({error:"Invalid API response"}));
  if(!response.ok)throw new Error(body.error??`Request failed (${response.status})`);
  return body as T;
}