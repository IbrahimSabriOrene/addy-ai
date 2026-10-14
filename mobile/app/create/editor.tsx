import { useI18n, translate } from "@/i18n";
import { EditorDemoScenes } from "@/components/EditorDemoScenes";
import { EditorSavedScenes, type EditorSceneMedia } from "@/components/EditorSavedScenes";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {saveLocalEdit} from "@/lib/localEdits";
import React, { useState, useCallback } from "react";
import { EditorScenePicker } from "@/components/EditorScenePicker";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { req, USE_MOCK } from "@/api/client";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useJob } from "@/api/hooks";
import { usePrivateMedia } from "@/lib/usePrivateMedia";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { TopBar } from "@/components/TopBar";
import { Platform } from "react-native";
const MediaEditor = Platform.OS === "web" ? require("../../src/components/MediaEditor.web").MediaEditor : require("../../src/components/MediaEditor").MediaEditor;

export default function EditorScreen() {
  useI18n();
  const { id, exportPlatform } = useLocalSearchParams<{ id: string; exportPlatform: string }>();
  const [sceneSource,setSceneSource]=useState("");
  const [sceneRevision,setSceneRevision]=useState(0);
  const [sceneState,setSceneState]=useState<{scope:string;items:EditorSceneMedia[]}>({scope:"",items:[]});
  const job = useJob(id ?? "");
  const router = useRouter();
  const qc=useQueryClient();
  const account = useQuery({queryKey:["editor-account"],queryFn:()=>USE_MOCK ? Promise.resolve({email:"demo"}) : req<{email:string}>("/v1/account")});
  const sceneScope=JSON.stringify([id,exportPlatform,account.data?.email]);
  const scenes=sceneState.scope===sceneScope?sceneState.items:[];
  const sceneReady=useCallback((scene:EditorSceneMedia)=>setSceneState(current=>{
    const items=current.scope===sceneScope?current.items:[];
    const order=["editor_lifestyle","editor_studio","editor_minimal","editor_editorial"];
    return {scope:sceneScope,items:[...items.filter(item=>item.id!==scene.id),scene].sort((a,b)=>order.indexOf(a.id)-order.indexOf(b.id))};
  }),[sceneScope]);
  const result = job.data?.exports?.find(item => item.platform === exportPlatform) ?? job.data?.exports?.[0];
  const { source, error } = usePrivateMedia(result?.url ?? "");
  if (!source || !job.data || !account.data) return <Screen><TopBar title={translate("Customize")} /><Text>{translate(error || (account.isError ? "Could not open your private editing draft." : job.isError ? "Could not load this creation." : "Loading your creation…"))}</Text></Screen>;
  const draftKey = "addy:create:" + (process.env.EXPO_PUBLIC_API_URL ?? "demo") + ":" + account.data.email + ":editor:" + id + ":" + (job.data.resultVersion ?? job.data.version) + ":" + result?.platform;
  return <><EditorDemoScenes source={job.data.outputKind==="photo"?result?.url??"":""} onReady={sceneReady}/><EditorSavedScenes photo={job.data.outputKind==="photo"} draftKey={draftKey} revision={sceneRevision} onReady={sceneReady}/><MediaEditor scenes={scenes} onScenes={async(source:string)=>setSceneSource(source)} key={draftKey} draftKey={draftKey} source={source} mimeType={result?.mimeType}
    saveCreation={async(dataUri:string,thumbnail:string)=>{
      const captionKey="addy:create:"+(process.env.EXPO_PUBLIC_API_URL??"demo")+":"+account.data.email+":result-caption:"+id+":"+(job.data!.resultVersion??job.data!.version)+":"+result!.platform;
      const caption=await AsyncStorage.getItem(captionKey)??result!.caption;
      const edited=await saveLocalEdit(account.data.email,{dataUri,thumbnail,title:job.data!.title,platform:result!.platform,caption});
      await qc.invalidateQueries({queryKey:["jobs"]});
      return edited.id;
    }}
    openCreation={async(editedId:string)=>{router.replace({pathname:"/create/result",params:{id:editedId}});}}
    photo={job.data.outputKind === "photo"} onClose={() => router.canGoBack() ? router.back() : router.replace({pathname:"/create/result",params:{id:id!}})} />
    {!!sceneSource&&<EditorScenePicker photo={job.data.outputKind==="photo"} source={sceneSource} draftKey={draftKey} onClose={()=>setSceneSource("")} onCreated={sceneId=>{
      setSceneSource("");void qc.invalidateQueries({queryKey:["jobs"]});void qc.invalidateQueries({queryKey:["wallet"]});
      setSceneRevision(value=>value+1);
    }}/>}</>;
}
