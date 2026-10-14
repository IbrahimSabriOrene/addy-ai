import type { Job } from "@/api/types";
type Record = {id:string;owner:string;job:Job;blob?:Blob;bytes?:ArrayBuffer;mimeType:string};
async function database():Promise<IDBDatabase>{
 return new Promise((resolve,reject)=>{
  const request=indexedDB.open("addy-edited-media",1);
  request.onupgradeneeded=()=>{const store=request.result.createObjectStore("edits",{keyPath:"id"});store.createIndex("owner","owner");};
  request.onerror=()=>reject(request.error);request.onsuccess=()=>resolve(request.result);
 });
}
async function transact<T>(mode:IDBTransactionMode,work:(store:IDBObjectStore,set:(value:T)=>void)=>void):Promise<T>{
 const db=await database();
 try{return await new Promise<T>((resolve,reject)=>{
  const tx=db.transaction("edits",mode);let value:T;
  tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error??Error("Storage transaction cancelled."));
  work(tx.objectStore("edits"),result=>{value=result;});
 });}finally{db.close();}
}
export async function save(owner:string,job:Job,dataUri:string,mimeType:string):Promise<void>{
 const bytes=await (await fetch(dataUri)).arrayBuffer();
 await transact<void>("readwrite",(store,set)=>{store.add({id:job.id,owner,job,bytes,mimeType});set(undefined);});
}
export async function list(owner:string):Promise<Job[]>{
 return transact<Job[]>("readonly",(store,set)=>{
  const jobs:Job[]=[];const request=store.index("owner").openCursor(IDBKeyRange.only(owner));
  request.onsuccess=()=>{const cursor=request.result;if(cursor){jobs.push((cursor.value as Record).job);cursor.continue();}else set(jobs);};
 });
}
export async function read(owner:string,id:string):Promise<{uri:string;mimeType:string}>{
 const record=await transact<Record|undefined>("readonly",(store,set)=>{const request=store.get(id);request.onsuccess=()=>set(request.result);});
 if(!record||record.owner!==owner)throw Error("This edited creation is not saved for this account.");
 return {uri:URL.createObjectURL(record.bytes?new Blob([record.bytes],{type:record.mimeType}):record.blob!),mimeType:record.mimeType};
}
export async function clear(owner:string):Promise<void>{
 await transact<void>("readwrite",(store,set)=>{
  const request=store.index("owner").openCursor(IDBKeyRange.only(owner));
  request.onsuccess=()=>{const cursor=request.result;if(cursor){cursor.delete();cursor.continue();}else set(undefined);};
 });
}
