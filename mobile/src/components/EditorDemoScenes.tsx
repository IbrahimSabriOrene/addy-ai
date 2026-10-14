import { useEffect } from "react";
import { Platform } from "react-native";
import { Asset } from "expo-asset";
import { USE_MOCK } from "../api/client";
import { loadEditorMedia } from "../lib/nativeEditorFiles";
import type { EditorSceneMedia } from "./EditorSavedScenes";

const originals=[require("../../public/previews/leather_editorial.png"),require("../../public/previews/leather_editorial.photo.jpg")];
const samples=[
 {id:"editor_lifestyle",name:"Lifestyle",file:"editor-leather-lifestyle.jpg",asset:require("../../public/previews/editor-leather-lifestyle.jpg")},
 {id:"editor_studio",name:"Studio",file:"editor-leather-studio.jpg",asset:require("../../public/previews/editor-leather-studio.jpg")},
 {id:"editor_minimal",name:"Minimal",file:"editor-leather-minimal.jpg",asset:require("../../public/previews/editor-leather-minimal.jpg")},
 {id:"editor_editorial",name:"Editorial",file:"editor-leather-editorial.jpg",asset:require("../../public/previews/editor-leather-editorial.jpg")},
];
export function EditorDemoScenes({source,onReady}:{source:string;onReady:(scene:EditorSceneMedia)=>void}){
 useEffect(()=>{
  if(!USE_MOCK)return;
  const match=Platform.OS==="web"?["/previews/leather_editorial.png","/previews/leather_editorial.photo.jpg"].includes(source):originals.some(item=>Asset.fromModule(item).uri===source);
  if(!match)return;
  let active=true;
  void Promise.all(samples.map(async sample=>{
   let uri="/previews/"+sample.file;
   if(Platform.OS!=="web"){
    const asset=await Asset.fromModule(sample.asset).downloadAsync();
    if(!asset.localUri)return;
    uri=await loadEditorMedia({uri:asset.localUri},true,"image/jpeg");
   }
   if(active)onReady({id:sample.id,name:sample.name,uri});
  })).catch(()=>{});
  return()=>{active=false;};
 },[source,onReady]);
 return null;
}
