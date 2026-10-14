import {Platform} from "react-native";
import type {Job,PlatformKey} from "@/api/types";
const storage:typeof import("./editedMediaStorage")=Platform.OS==="web"?require("./editedMediaStorage.web"):require("./editedMediaStorage");
let writes:Promise<unknown>=Promise.resolve();
const blocked=new Set<string>();
const scope=(email:string)=>(process.env.EXPO_PUBLIC_API_URL??"demo")+"|"+email;
export async function listLocalEdits(email:string):Promise<Job[]>{
 await writes.catch(()=>{});
 return (await storage.list(scope(email))).sort((a,b)=>b.createdAt.localeCompare(a.createdAt));
}
export async function readLocalEdit(email:string,id:string){
 if(!/^edit_[a-z0-9_]+$/.test(id))throw Error("Invalid edited creation.");
 return storage.read(scope(email),id);
}
export async function saveLocalEdit(email:string,input:{dataUri:string;thumbnail:string;title:string;platform:PlatformKey;caption:string}):Promise<Job>{
 const match=/^data:(image\/png|video\/mp4|video\/webm)(?:;codecs=[a-zA-Z0-9., "'-]{1,80})?;base64,([A-Za-z0-9+/=]+)$/.exec(input.dataUri);
 if(!match||match[2].length>32*1024*1024)throw Error("This edited export exceeds the 24 MB local limit or is invalid.");
 if(!/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(input.thumbnail)||input.thumbnail.length>200000)throw Error("Invalid preview image.");
 const id="edit_"+Date.now().toString(36)+"_"+Math.random().toString(36).slice(2,10);
 const mimeType=match[1] as "image/png"|"video/mp4"|"video/webm";
 const job:Job={id,title:input.title+" · Edited",state:"delivered",version:1,resultVersion:"1",createdAt:new Date().toISOString(),outputKind:mimeType==="image/png"?"photo":"video",platforms:[input.platform],sourceImage:input.thumbnail,exports:[{platform:input.platform,caption:input.caption,url:"addy-edit://"+id,mimeType}]};
 const owner=scope(email);
 const pending=writes.catch(()=>{}).then(async()=>{
  if(blocked.has(owner))throw Error("Saving stopped after account deletion.");
  await storage.save(owner,job,input.dataUri,mimeType);
 });
 writes=pending;await pending;return job;
}
export async function clearLocalEdits(email:string):Promise<void>{
 const owner=scope(email);blocked.add(owner);await writes.catch(()=>{});await storage.clear(owner);
}
