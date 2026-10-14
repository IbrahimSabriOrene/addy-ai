import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const records=new Map();let release;
const pending=new Promise(resolve=>release=resolve);let pause=false;
const store={
 async list(owner){return [...records.values()].filter(x=>x.owner===owner).map(x=>x.job);},
 async save(owner,job){if(pause)await pending;records.set(job.id,{owner,job});},
 async read(owner,id){const item=records.get(id);if(!item||item.owner!==owner)throw Error("Not owned");return {uri:"blob:owned",mimeType:"image/png"};},
 async clear(owner){for(const [id,item] of records)if(item.owner===owner)records.delete(id);}
};
const context={exports:{},process:{env:{}},require(name){if(name==="react-native")return {Platform:{OS:"web"}};if(name==="./editedMediaStorage.web")return store;throw Error(name);}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/lib/localEdits.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
const {saveLocalEdit,listLocalEdits,readLocalEdit,clearLocalEdits}=context.exports;
const input={dataUri:"data:image/png;base64,AAAA",thumbnail:"data:image/jpeg;base64,AAAA",title:"Product",platform:"feed",caption:"Caption"};
const a=await saveLocalEdit("a",input),b=await saveLocalEdit("b",input);
assert.equal((await listLocalEdits("a")).length,1);
await assert.rejects(readLocalEdit("b",a.id),/Not owned/);
await assert.rejects(readLocalEdit("a","../outside"),/Invalid/);
await assert.rejects(saveLocalEdit("a",{...input,dataUri:"data:text/html;base64,AAAA"}),/invalid/);
pause=true;const saving=saveLocalEdit("a",input);await Promise.resolve();const clearing=clearLocalEdits("a");release();await Promise.allSettled([saving,clearing]);
assert.equal((await listLocalEdits("a")).length,0);
assert.equal((await listLocalEdits("b"))[0].id,b.id);
await assert.rejects(saveLocalEdit("a",input),/deletion/);
console.log("Local edits: separate copies, owner isolation, deletion serialization and invalid media checks passed.");
