import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const calls=[];
let size=1024, shareFails=false;
const fs={
 cacheDirectory:"file:///cache/",EncodingType:{Base64:"base64"},
 async downloadAsync(url,dest,options){calls.push(["download",url,dest,options]);return {status:200};},
 async getInfoAsync(){return {exists:true,size};},
 async readAsStringAsync(){return "AAAA";},
 async writeAsStringAsync(uri,value){calls.push(["write",uri,value]);},
 async deleteAsync(uri){calls.push(["delete",uri]);}
};
const sandbox={exports:{},require(name){
 if(name==="expo-file-system/legacy")return fs;
 if(name==="expo-sharing")return {isAvailableAsync:async()=>true,shareAsync:async(uri,options)=>{calls.push(["share",uri,options]);if(shareFails)throw Error("share failed");}};
 throw Error(name);
}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/lib/nativeEditorFiles.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,sandbox);
const {loadEditorMedia,shareEditorMedia}=sandbox.exports;
assert.equal(await loadEditorMedia({uri:"https://account.test/media",headers:{Authorization:"Bearer fixture"}},false),"data:video/mp4;base64,AAAA");
assert.equal(calls.find(x=>x[0]==="download")[3].headers.Authorization,"Bearer fixture");
assert.ok(calls.some(x=>x[0]==="delete"));
calls.length=0;
await loadEditorMedia({uri:"file:///original.mp4"},false);
assert.equal(calls.length,0,"original media must not be deleted");
size=25*1024*1024;
await assert.rejects(loadEditorMedia({uri:"file:///original.mp4"},false),/24 MB/);
await assert.rejects(shareEditorMedia("data:text/html;base64,AAAA"),/invalid/);
size=1024;
await shareEditorMedia("data:video/mp4;base64,AAAA");
assert.ok(calls.find(x=>x[0]==="share")[2].mimeType==="video/mp4");
assert.equal(calls.at(-1)[0],"delete");
calls.length=0;
await shareEditorMedia("data:video/webm;codecs=vp9,opus;base64,AAAA");
assert.equal(calls.find(x=>x[0]==="share")[2].mimeType,"video/webm");
calls.length=0;shareFails=true;
await assert.rejects(shareEditorMedia("data:image/png;base64,AAAA"),/share failed/);
assert.equal(calls.at(-1)[0],"delete");
console.log("Native editor adapter checks passed: account headers, size bounds, original preservation, export sharing and temporary-file cleanup.");
