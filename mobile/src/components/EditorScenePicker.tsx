import { useI18n, translate } from "@/i18n";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { usePrivateMedia } from "../lib/usePrivateMedia";
import { isJobPending } from "../lib/jobStatus";
import React, { useState } from "react";
import { Image, Modal, Platform, ScrollView, View } from "react-native";
import * as FileSystem from "expo-file-system/legacy";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getCatalogue } from "../api/creation";
import { api, req, USE_MOCK } from "../api/client";
import { EDITOR_SCENES, generateEditorScene, type EditorSceneId } from "../api/editorScenes";
import { Button } from "./Button";
import { Text } from "./Text";

type Consent = { granted: boolean; disclosureVersion: string; disclosure: string };
export function EditorScenePicker({source,draftKey,onClose,onCreated,photo}:{photo:boolean;source:string;draftKey:string;onClose:()=>void;onCreated:(id:string)=>void}) {
  useI18n();
 const qc=useQueryClient();
 const [selected,setSelected]=useState<EditorSceneId>("editor_lifestyle");
 const [busy,setBusy]=useState(false),[error,setError]=useState("");
 const catalogue=useQuery({queryKey:["editor-scene-catalogue"],queryFn:getCatalogue});
 const consent=useQuery({queryKey:["editor-scene-consent"],enabled:!USE_MOCK,queryFn:()=>req<Consent>("/v1/account/ai-consent")});
 const kind=photo?"photo":"video";
 const mode=catalogue.data?.modes?.[kind]??catalogue.data;
 const baseKey=draftKey+":video-base-portrait";
 const baseReceipt=useQuery({queryKey:["editor-video-base",baseKey,selected],enabled:!photo&&!USE_MOCK,queryFn:async()=>{
  const raw=await AsyncStorage.getItem(baseKey+":scenes");const id=raw?JSON.parse(raw)?.scenes?.[selected]?.jobId:null;return typeof id==="string"?id:null;
 }});
 const baseJob=useQuery({queryKey:["job",baseReceipt.data],enabled:!!baseReceipt.data,queryFn:()=>api.getJob(baseReceipt.data!),refetchInterval:q=>q.state.data&&isJobPending(q.state.data)?2000:false});
 const baseExport=baseJob.data?.state==="delivered"&&baseJob.data.outputKind==="photo"?baseJob.data.exports?.[0]:undefined;
 const baseMedia=usePrivateMedia(baseExport?.url??"");
 const photoMode=catalogue.data?.modes?.photo??catalogue.data;
 const enabled=!USE_MOCK&&mode?.generationEnabled&&mode.executionMode==="google"&&catalogue.data?.prices[kind]===1&&(photo||(photoMode?.generationEnabled&&photoMode.executionMode==="google"&&catalogue.data?.prices.photo===1));
 async function generate(){
  setBusy(true);setError("");let temporary="";
  try{
   if(!enabled||!consent.data?.granted)throw Error("Scene generation is unavailable or needs AI-sharing permission.");
   if(!photo&&baseExport&&baseJob.data?.resultVersion){
    const asset=await req<{assetKey:string}>("/v1/jobs/"+baseJob.data.id+"/photo-asset",{method:"POST",body:JSON.stringify({expectedResultVersion:baseJob.data.resultVersion,platform:baseExport.platform})});
    const id=await generateEditorScene(draftKey,"",selected,1,"video",asset.assetKey);onCreated(id);return;
   }
   if(!photo&&baseReceipt.data)throw Error("The scene photo is still pending or needs review in your library.");
   let uri=source;
   if(Platform.OS!=="web"){
    const match=/^data:image\/png;base64,([A-Za-z0-9+/=]+)$/.exec(source);
    if(!match||match[1].length>14*1024*1024||!FileSystem.cacheDirectory)throw Error("Could not prepare this product image.");
    temporary=FileSystem.cacheDirectory+"addy-scene-"+Date.now()+"-"+Math.random().toString(36).slice(2)+".png";
    await FileSystem.writeAsStringAsync(temporary,match[1],{encoding:FileSystem.EncodingType.Base64});uri=temporary;
   }
   const id=await generateEditorScene(photo?draftKey:baseKey,uri,selected,1,"photo",undefined,photo?"feed":"stories");
   if(photo)onCreated(id);else {await baseReceipt.refetch();void qc.invalidateQueries({queryKey:["jobs"]});void qc.invalidateQueries({queryKey:["wallet"]});}
  }catch(e){setError(e instanceof Error?e.message:"Could not create this scene.");}
  finally{if(temporary)await FileSystem.deleteAsync(temporary,{idempotent:true}).catch(()=>{});setBusy(false);}
 }
 return <Modal visible transparent animationType="slide" onRequestClose={()=>{if(!busy)onClose();}}>
  <View style={{flex:1,backgroundColor:"#0009",justifyContent:"flex-end"}}>
   <ScrollView style={{maxHeight:"85%",backgroundColor:"#101619",borderTopLeftRadius:24,borderTopRightRadius:24}} contentContainerStyle={{padding:24,paddingBottom:40,gap:16}}>
    <Text variant="heading">{translate("Change scene")}</Text>
    <Text>{photo?translate("A new photo of this product. Your original stays unchanged."):translate("New video and sound, based on a frame from this product clip. Your original stays unchanged.")}</Text>
    {catalogue.isPending?<Text>{translate("Loading scene options…")}</Text>:!enabled?<Text>{translate("AI scene generation is not available in this preview.")}</Text>:<>
     <View style={{gap:8}}>{EDITOR_SCENES.map(scene=><Button key={scene.id} label={translate(scene.name)} variant={selected===scene.id?"selected":"secondary"} disabled={busy} onPress={()=>setSelected(scene.id)}/>)}</View>
     {!photo&&<Text>{translate("Scene photo: 1 credit. After reviewing it, video: 1 credit. Reopening a saved scene reuses its image.")}</Text>}
     {!photo&&baseExport&&baseMedia.source&&<Image source={baseMedia.source} accessibilityLabel={translate("Review scene photo")} resizeMode="contain" style={{width:"100%",height:240,borderRadius:12}}/>}
     {!photo&&baseReceipt.data&&!baseExport&&<Text>{baseJob.isError?translate("Could not load the scene photo. Close and reopen to retry."):baseJob.data&& !isJobPending(baseJob.data)?translate("This scene needs review in your library."):translate("Creating your scene photo…")}</Text>}
     {baseMedia.error&&<Text>{translate(baseMedia.error)}</Text>}
     {consent.isPending?<Text>{translate("Checking AI-sharing permission…")}</Text>:consent.data&&!consent.data.granted?<>
      <Text>{translate(consent.data.disclosure)}</Text>
      <Button label={translate("Allow AI processing")} disabled={busy} onPress={()=>{
       setBusy(true);setError("");void req("/v1/account/ai-consent",{method:"PUT",body:JSON.stringify({granted:true,disclosureVersion:consent.data!.disclosureVersion})}).then(()=>consent.refetch()).catch(()=>setError("Could not save your permission. Please retry.")).finally(()=>setBusy(false));
      }}/>
     </>:<Button label={photo?translate("Create scene · 1 credit"):baseExport?translate("Use this scene · Video · 1 credit"):translate("Create scene photo · 1 credit")} loading={busy} disabled={!consent.data?.granted||busy||(!photo&&(baseReceipt.isPending||baseReceipt.isError||!!baseReceipt.data&&(!baseExport||!baseMedia.source)))} onPress={()=>void generate()}/>}
    </>}
    {(error||catalogue.isError||consent.isError)&&<Text>{translate(error||"Could not load scene options. Close and reopen to retry.")}</Text>}
    <Button label={translate("Back to editing")} variant="ghost" disabled={busy} onPress={onClose}/>
   </ScrollView>
  </View>
 </Modal>;
}
