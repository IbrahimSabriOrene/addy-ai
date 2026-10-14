import AsyncStorage from "@react-native-async-storage/async-storage";
import * as FileSystem from "expo-file-system/legacy";
import type {Job} from "@/api/types";
const key=(owner:string)=>"addy:edited-media:"+owner;
function file(id:string):string{
 if(!/^edit_[a-z0-9_]+$/.test(id)||!FileSystem.documentDirectory)throw Error("Invalid edited media location.");
 return FileSystem.documentDirectory+"addy-edits/"+id;
}
export async function list(owner:string):Promise<Job[]>{
 return JSON.parse(await AsyncStorage.getItem(key(owner))??"[]");
}
export async function save(owner:string,job:Job,dataUri:string,mimeType:string):Promise<void>{
 const uri=file(job.id);
 await FileSystem.makeDirectoryAsync(FileSystem.documentDirectory+"addy-edits/",{intermediates:true});
 try{
  await FileSystem.writeAsStringAsync(uri,dataUri.slice(dataUri.indexOf(",")+1),{encoding:FileSystem.EncodingType.Base64});
  await AsyncStorage.setItem(key(owner),JSON.stringify([job,...await list(owner)]));
 }catch(error){await FileSystem.deleteAsync(uri,{idempotent:true});throw error;}
}
export async function read(owner:string,id:string):Promise<{uri:string;mimeType:string}>{
 const job=(await list(owner)).find(item=>item.id===id);
 if(!job)throw Error("This edited creation is not saved for this account.");
 const uri=file(id),info=await FileSystem.getInfoAsync(uri);
 if(!info.exists)throw Error("This edited file is no longer on this device.");
 return {uri,mimeType:job.exports?.[0]?.mimeType??"video/mp4"};
}
export async function clear(owner:string):Promise<void>{
 for(const job of await list(owner))await FileSystem.deleteAsync(file(job.id),{idempotent:true});
 await AsyncStorage.removeItem(key(owner));
}
