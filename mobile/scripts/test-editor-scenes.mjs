import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const drafts=new Map(), calls=[];
let uploads=0, granted=true, available=true, unknown=false, failWrite=false;
const context={exports:{}, require(name){
 if(name==="@react-native-async-storage/async-storage")return {getItem:async key=>drafts.get(key)??null};
 if(name==="../lib/accountDrafts")return {writeAccountDraft:async(key,value)=>{if(failWrite)throw Error("storage unavailable");drafts.set(key,value);}};
 if(name==="./client")return {USE_MOCK:false,req:async()=>({granted}),uploadImage:async()=>{uploads++;return "asset-original";}};
 if(name==="./creation")return {
  getCatalogue:async()=>({generationEnabled:available,executionMode:"google",prices:{photo:1,video:1},items:["editor_lifestyle","editor_studio","editor_minimal","editor_editorial","editor_studio_video"].map(id=>({id,version:1,outputKinds:[id.endsWith("_video")?"video":"photo"]}))}),
  createFromDraft:async command=>{calls.push(JSON.parse(JSON.stringify(command)));if(unknown){unknown=false;throw Error("connection lost");}return {id:"job-"+command.key};},
 };
 throw Error(name);
}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/api/editorScenes.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
const {generateEditorScene:generate}=context.exports;
const key="addy:create:api:owner:editor:original";
granted=false;
await assert.rejects(generate(key,"source","editor_studio",1),/permission/);
assert.equal(uploads,0);assert.equal(calls.length,0);
granted=true;
await assert.rejects(generate(key,"source","editor_studio",2),/price/);
assert.equal(uploads,0);
const [first,duplicate,other]=await Promise.all([generate(key,"source","editor_studio",1),generate(key,"source","editor_studio",1),generate(key,"source","editor_minimal",1)]);
assert.equal(first,duplicate);assert.notEqual(first,other);
assert.equal(uploads,1);assert.equal(calls.length,2);
assert.equal(calls[0].body.assetKey,calls[1].body.assetKey);
unknown=true;
await assert.rejects(generate(key,"source","editor_editorial",1),/connection lost/);
const uncertain=calls.at(-1);
available=false;
await generate(key,"source","editor_editorial",1);
assert.deepEqual(calls.at(-1),uncertain);
await assert.rejects(generate(key,"source","editor_lifestyle",1),/unavailable/);
available=true;failWrite=true;
const before=calls.length;
await assert.rejects(generate(key+"-other","source","editor_studio",1),/storage unavailable/);
assert.equal(calls.length,before);
console.log("Editor scenes: consent/price gates, shared source, duplicate taps, uncertain retry and durable-before-submit checks passed.");

failWrite=false;
await assert.rejects(generate(key+"-video","source","editor_studio",1,"video"),/Review a generated scene/);
const previousUploads=uploads;
await generate(key+"-video","source","editor_studio",1,"video","verified-scene-photo");
assert.equal(uploads,previousUploads);
assert.equal(calls.at(-1).body.assetKey,"verified-scene-photo");
assert.equal(calls.at(-1).body.templateId,"editor_studio_video");
assert.equal(calls.at(-1).body.outputKind,"video");
assert.deepEqual(calls.at(-1).body.platforms,["reels"]);
await assert.rejects(generate(key+"-video","source","editor_studio",1,"photo"),/different media type/);
console.log("Video scenes use independent video templates and reject media-type mismatches.");

await generate(key+"-portrait-base","source","editor_studio",1,"photo",undefined,"stories");
assert.deepEqual(calls.at(-1).body.platforms,["stories"]);
console.log("Video base photos request the portrait platform.");
