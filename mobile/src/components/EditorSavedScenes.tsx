import { useI18n, translate } from "@/i18n";
import { Button } from "./Button";
import React, { useEffect, useState } from "react";
import { Platform, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { EDITOR_SCENES } from "../api/editorScenes";
import { isJobPending } from "../lib/jobStatus";
import { usePrivateMedia } from "../lib/usePrivateMedia";
import { loadEditorMedia } from "../lib/nativeEditorFiles";
import { Text } from "./Text";

export type EditorSceneMedia = { id:string; name:string; uri:string };
function SceneMedia({id,name,jobId,onReady,photo,onRetry}:{onRetry:()=>void;photo:boolean;id:string;name:string;jobId:string;onReady:(scene:EditorSceneMedia)=>void}){
  useI18n();
 const [downloadError,setDownloadError]=useState(false);
 const job=useQuery({queryKey:["job",jobId],queryFn:()=>api.getJob(jobId),refetchInterval:q=>q.state.data&&isJobPending(q.state.data)?2000:false});
 const result=job.data?.state==="delivered"&&job.data.outputKind===(photo?"photo":"video")?job.data.exports?.[0]:undefined;
 const {source,error}=usePrivateMedia(result?.url??"");
 useEffect(()=>{
  if(!source)return;let active=true;setDownloadError(false);
  void (Platform.OS==="web"?Promise.resolve(source.uri):loadEditorMedia(source,photo,result?.mimeType))
   .then(uri=>{if(active)onReady({id,name,uri});}).catch(()=>{if(active)setDownloadError(true);});
  return()=>{active=false;};
 },[source?.uri,id,name,onReady,result?.mimeType,photo]);
 if(job.isError||error||downloadError||(job.data?.state==="delivered"&&!result))return <View style={{padding:12,gap:4}}><Text>{translate("Could not load {name}.", { name: translate(name) })}</Text><Button label={translate("Retry {name}", { name: translate(name) })} variant="ghost" disabled={job.isFetching} onPress={()=>{void job.refetch().finally(onRetry);}}/></View>;
 if(job.data&&isJobPending(job.data))return <Text>{translate("Creating {name} scene…", { name: translate(name) })}</Text>;
 if(job.data&&job.data.state!=="delivered")return <Text>{translate("Review {name} in your library.", { name: translate(name) })}</Text>;
 return null;
}
export function EditorSavedScenes({draftKey,revision,onReady,photo}:{photo:boolean;draftKey:string;revision:number;onReady:(scene:EditorSceneMedia)=>void}){
  useI18n();
 const [retries,setRetries]=useState<Record<string,number>>({});
 const saved=useQuery({queryKey:["editor-scenes",draftKey,revision],queryFn:async()=>{
  const raw=await AsyncStorage.getItem(draftKey+":scenes");
  const value=raw?JSON.parse(raw):{scenes:{}};
  return EDITOR_SCENES.flatMap(scene=>typeof value?.scenes?.[scene.id]?.jobId==="string"?[{...scene,jobId:value.scenes[scene.id].jobId as string}]:[]);
 }});
 if(saved.isError)return <View style={{padding:12}}><Text>{translate("Could not restore saved scenes.")}</Text><Button label={translate("Retry saved scenes")} variant="ghost" onPress={()=>void saved.refetch()}/></View>;
 return <>{saved.data?.map(scene=><SceneMedia photo={photo} key={scene.id+":"+(retries[scene.id]??0)} onRetry={()=>setRetries(values=>({...values,[scene.id]:(values[scene.id]??0)+1}))} {...scene} onReady={onReady}/>)}</>;
}
