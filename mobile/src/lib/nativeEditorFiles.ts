import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";

// The DOM bridge uses JSON; cap short creative media before base64 transfer.
const MAX_MEDIA_BYTES = 24 * 1024 * 1024;
export async function loadEditorMedia(source:{uri:string;headers?:Record<string,string>},photo:boolean,mimeType?:string):Promise<string>{
 if(!FileSystem.cacheDirectory)throw Error("Device storage is unavailable.");
 const mime=mimeType??(photo?"image/png":"video/mp4");
 let uri=source.uri,temporary="";
 try{
  if(/^https?:\/\//.test(uri)){
   temporary=FileSystem.cacheDirectory+"addy-editor-input-"+Date.now()+"-"+Math.random().toString(36).slice(2);
   const result=await FileSystem.downloadAsync(uri,temporary,{headers:source.headers});
   if(result.status!==200)throw Error("Could not download this creation.");
   uri=temporary;
  }else if(!uri.startsWith("file://"))throw Error("This media source cannot be opened on this device.");
  const info=await FileSystem.getInfoAsync(uri);
  if(!info.exists||!("size" in info)||!info.size||info.size>MAX_MEDIA_BYTES)throw Error("This local editor supports media up to 24 MB.");
  const base64=await FileSystem.readAsStringAsync(uri,{encoding:FileSystem.EncodingType.Base64});
  return "data:"+mime+";base64,"+base64;
 }finally{if(temporary)await FileSystem.deleteAsync(temporary,{idempotent:true});}
}
export async function shareEditorMedia(dataUri:string):Promise<void>{
 const match=/^data:(image\/png|video\/mp4|video\/webm)(?:;codecs=[a-zA-Z0-9., "'-]{1,80})?;base64,([A-Za-z0-9+/=]+)$/.exec(dataUri);
 if(!match||match[2].length>Math.ceil(MAX_MEDIA_BYTES*4/3))throw Error("The edited export is invalid or exceeds 24 MB.");
 if(!FileSystem.cacheDirectory||!await Sharing.isAvailableAsync())throw Error("File sharing is unavailable on this device.");
 const mime=match[1],extension=mime==="image/png"?"png":mime==="video/mp4"?"mp4":"webm";
 const uri=FileSystem.cacheDirectory+"addy-edited-"+Date.now()+"-"+Math.random().toString(36).slice(2)+"."+extension;
 try{
  await FileSystem.writeAsStringAsync(uri,match[2],{encoding:FileSystem.EncodingType.Base64});
  await Sharing.shareAsync(uri,{mimeType:mime,dialogTitle:"Save or share your creation",UTI:mime==="video/mp4"?"public.mpeg-4":mime==="image/png"?"public.png":"org.webmproject.webm"});
 }finally{await FileSystem.deleteAsync(uri,{idempotent:true});}
}
