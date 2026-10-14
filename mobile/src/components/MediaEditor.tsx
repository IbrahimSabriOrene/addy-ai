import { useI18n, translate } from "@/i18n";
import React, { useEffect, useState } from "react";
import { View, useWindowDimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { writeAccountDraft } from "@/lib/accountDrafts";
import { loadEditorMedia, shareEditorMedia } from "@/lib/nativeEditorFiles";
import EditorSurface from "./EditorSurface";
import { Screen } from "./Screen";
import { Text } from "./Text";
import { Button } from "./Button";
export type MediaEditorProps = { draftKey: string; scenes?:{id:string;name:string;uri:string}[]; onScenes?:(source:string)=>Promise<void>; saveCreation:(dataUri:string,thumbnail:string)=>Promise<string>; openCreation:(id:string)=>Promise<void>; mimeType?:string; source: { uri: string; headers?: Record<string,string> }; photo:boolean; onClose:()=>void };
export function MediaEditor({source,photo,onClose,draftKey,saveCreation,openCreation,mimeType,onScenes,scenes}:MediaEditorProps) {
 const { locale } = useI18n();
 const insets=useSafeAreaInsets();
 const {fontScale}=useWindowDimensions();
 const [dataUri,setDataUri]=useState(""),[error,setError]=useState("");
 useEffect(()=>{
  let alive=true;setDataUri("");setError("");
  void loadEditorMedia(source,photo,mimeType).then(uri=>{if(alive)setDataUri(uri);}).catch(e=>{if(alive)setError(e instanceof Error?e.message:"Could not load media.");});
  return()=>{alive=false;};
 },[source.uri,photo,mimeType]);
 if(!dataUri)return <Screen><Text variant="heading">{translate("Customize")}</Text><Text>{translate(error||"Opening your creation…")}</Text><Button label={translate("Back to result")} onPress={onClose}/></Screen>;
 return <View style={{flex:1,paddingTop:insets.top,paddingBottom:insets.bottom,paddingLeft:insets.left,paddingRight:insets.right,backgroundColor:"#0b1012"}}>
  <EditorSurface locale={locale} fontScale={fontScale} source={{uri:dataUri}} photo={photo} draftKey={draftKey} saveCreation={saveCreation} openCreation={openCreation} onScenes={onScenes} scenes={scenes}
   onClose={async()=>onClose()} loadDraft={()=>AsyncStorage.getItem(draftKey)}
   saveDraft={value=>writeAccountDraft(draftKey,value)} saveFile={shareEditorMedia}
   dom={{style:{flex:1,backgroundColor:"#0b1012"},scrollEnabled:false,allowsInlineMediaPlayback:true,mediaPlaybackRequiresUserAction:false}} />
 </View>;
}
