"use dom";
import { translate as translateText, type Locale } from "../i18n/runtime";
import { createEditorColorRenderer } from "../lib/editorColorRenderer";
import { useFonts } from "expo-font";
import React, { useEffect, useRef, useState } from "react";
type SurfaceProps = {
 locale?:Locale;
 fontScale?:number;
 scenes?:{id:string;name:string;uri:string}[];
 onScenes?: (source:string)=>Promise<void>;
 source: { uri: string }; photo: boolean; draftKey: string;
 onClose: () => Promise<void>;
 loadDraft: () => Promise<string | null>;
 saveDraft: (value: string) => Promise<void>;
 saveCreation: (dataUri:string,thumbnail:string) => Promise<string>;
 openCreation: (id:string) => Promise<void>;
 saveFile?: (value: string) => Promise<void>;
 dom?: import("expo/dom").DOMProps;
};
const looks = [{name:"Original",filter:"none"},{name:"Warm",filter:"sepia(.18) saturate(1.08)"},{name:"Studio",filter:"brightness(1.06) contrast(1.05)"},{name:"Soft",filter:"contrast(.9) saturate(.85)"},{name:"Editorial",filter:"contrast(1.18) saturate(.72)"}];
const icons: Record<string,string> = {
 Background:"M3 5h18v14H3z M3 16l5-5 4 4 3-3 6 5 M8 8h.01",
 Style:"m4 18 10-10 4 4L8 22Z M14 2v4 M12 4h4 M21 16v4 M19 18h4",
 Text:"M4 5h16 M12 5v15 M8 20h8 M4 5v3 M20 5v3",
 Resize:"M6 2v16h16 M2 6h16v16",
 Filters:"M12 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10 M7 10a5 5 0 1 0 0 10 5 5 0 0 0 0-10 M17 10a5 5 0 1 0 0 10 5 5 0 0 0 0-10"
};
type Settings = {fit?:"contain"|"cover";cropX?:number;cropY?:number;sceneId?:string;look:number;background:string;inset:number;text:string;textY:number;textSize:number;color:string;ratio:number;brightness:number};
function validEditorSettings(value: unknown): value is Settings {
 if(!value||typeof value!=="object")return false;
 const s=value as Settings;
 return (s.fit===undefined||s.fit==="contain"||s.fit==="cover")&&[s.cropX,s.cropY].every(v=>v===undefined||(typeof v==="number"&&Number.isFinite(v)&&v>=0&&v<=100))&&(s.sceneId===undefined||["","editor_lifestyle","editor_studio","editor_minimal","editor_editorial"].includes(s.sceneId))&&Number.isInteger(s.look)&&s.look>=0&&s.look<looks.length
  && typeof s.text==="string"&&s.text.length<=120
  && typeof s.background==="string"&&/^#[0-9a-f]{6}$/i.test(s.background)
  && typeof s.color==="string"&&/^#[0-9a-f]{6}$/i.test(s.color)
  && [9/16,1,4/5].includes(s.ratio)
  && [[s.inset,0,20],[s.textY,15,85],[s.textSize,3,12],[s.brightness,70,130]].every(([v,min,max])=>typeof v==="number"&&Number.isFinite(v)&&v>=min&&v<=max);
}
const initial:Settings={look:0,background:"#101213",inset:0,text:"",textY:82,textSize:6,color:"#ffffff",ratio:9/16,brightness:100};
export default function MediaEditor({source,photo,onClose,draftKey,loadDraft,saveDraft,saveFile,saveCreation,openCreation,onScenes,scenes=[],fontScale=1,locale="en"}:SurfaceProps){
  const translate = (source:string, params?:Record<string,string|number>) => translateText(source, params, locale);
 useFonts({Manrope_400Regular:require("@expo-google-fonts/manrope/Manrope_400Regular.ttf"),SpaceGrotesk_700Bold:require("@expo-google-fonts/space-grotesk/SpaceGrotesk_700Bold.ttf")});
 const [settings,setSettings]=useState<Settings>(()=>photo?{...initial,ratio:4/5}:initial), [history,setHistory]=useState<Settings[]>([]);
 const [tool,setTool]=useState<string|null>(null), [ready,setReady]=useState(false), [poster,setPoster]=useState("");
 const [busy,setBusy]=useState(false),[error,setError]=useState(""),[output,setOutput]=useState<{url:string;extension:string;dataUri:string;thumbnail:string}|null>(null);
 const [savedId,setSavedId]=useState("");
 const [draftReady,setDraftReady]=useState(false);
 const [draftFailed,setDraftFailed]=useState(false);
 const colorRenderer=useRef<ReturnType<typeof createEditorColorRenderer>|null>(null);
 const canvas=useRef<HTMLCanvasElement>(null), media=useRef<HTMLVideoElement|HTMLImageElement|null>(null);
 const latest=useRef(settings), recording=useRef(false), alive=useRef(true), outputUrl=useRef("");
 const recorder=useRef<MediaRecorder|null>(null);
 function change(update:Partial<Settings>){if(!draftReady)return;setHistory(items=>[...items.slice(-29),settings]);setSettings({...settings,...update});setOutput(null);setSavedId("");}
 function draw(target:HTMLCanvasElement,s:Settings){
  const element=media.current;if(!element)return;
  const w=element instanceof HTMLVideoElement?element.videoWidth:element.naturalWidth;
  const h=element instanceof HTMLVideoElement?element.videoHeight:element.naturalHeight;if(!w||!h)return;
  const ctx=target.getContext("2d");if(!ctx)return;
  let drawable:CanvasImageSource=element;
  const nativeFilters="filter" in CanvasRenderingContext2D.prototype;
  if(!nativeFilters&&(s.look!==0||s.brightness!==100)){
   colorRenderer.current??=createEditorColorRenderer();drawable=colorRenderer.current.render(element,w,h,s.look,s.brightness);
  }
  ctx.filter="none";ctx.fillStyle=s.background;ctx.fillRect(0,0,target.width,target.height);
  const p=target.width*s.inset/100,innerW=target.width-p*2,innerH=target.height-p*2,scale=(s.fit==="cover"?Math.max:Math.min)(innerW/w,innerH/h);
  ctx.save();ctx.beginPath();ctx.rect(p,p,innerW,innerH);ctx.clip();
  if(nativeFilters)ctx.filter=(looks[s.look].filter==="none"?"":looks[s.look].filter)+" brightness("+(s.brightness/100)+")";
  ctx.drawImage(drawable,p+(innerW-w*scale)*(s.fit==="cover"?(s.cropX??50)/100:.5),p+(innerH-h*scale)*(s.fit==="cover"?(s.cropY??50)/100:.5),w*scale,h*scale);ctx.restore();ctx.filter="none";
  if(s.text){ctx.font="600 "+(target.width*s.textSize/100)+"px Arial";ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillStyle=s.color;ctx.shadowColor="rgba(0,0,0,.7)";ctx.shadowBlur=target.width*.012;
   const lines=s.text.split("\n");lines.forEach((line,i)=>ctx.fillText(line,target.width/2,target.height*s.textY/100+(i-(lines.length-1)/2)*target.width*s.textSize/85,target.width*.9));ctx.shadowBlur=0;}
 }
 useEffect(()=>{
  let active=true;
  void loadDraft().then(value=>{
   if(!active)return;
   if(value){
    const parsed=JSON.parse(value);
    if(!validEditorSettings(parsed))throw Error("Saved editing draft is invalid.");
    setSettings(parsed);
   }
   setDraftReady(true);
  }).catch(()=>{if(active){setDraftFailed(true);setError("Could not load your editing draft. Reopen to retry, or start fresh edits. Your original stays unchanged.");}});
  return()=>{active=false;};
 },[draftKey]);
 useEffect(()=>{
  if(!draftReady)return;
  void saveDraft(JSON.stringify(settings)).catch(()=>setError("Could not save your edits on this device."));
 },[draftKey,draftReady,settings]);
 useEffect(()=>{latest.current=settings;},[settings]);
 const selectedUri=settings.sceneId?scenes.find(scene=>scene.id===settings.sceneId)?.uri:source.uri;
 useEffect(()=>{
  if(!selectedUri){setReady(false);return;}
  alive.current=true;setReady(false);const element=photo?new Image():document.createElement("video");media.current=element;let frame=0;
  const loaded=()=>{if(!alive.current)return;const thumb=document.createElement("canvas");thumb.width=108;thumb.height=144;const ctx=thumb.getContext("2d");if(ctx){ctx.drawImage(element,0,0,108,144);setPoster(thumb.toDataURL("image/jpeg",.8));}setReady(true);if(element instanceof HTMLVideoElement)void element.play().catch(()=>{});};
  element.onerror=()=>setError("Could not open this media. Return to the result and try again.");
  if(element instanceof HTMLVideoElement){element.muted=true;element.playsInline=true;element.loop=true;element.preload="auto";element.onloadeddata=loaded;}else element.onload=loaded;
  element.src=selectedUri;
  const tick=()=>{try{if(canvas.current&&!recording.current)draw(canvas.current,latest.current);frame=requestAnimationFrame(tick);}catch(e){setError(e instanceof Error?e.message:"Could not render edits.");setReady(false);}};frame=requestAnimationFrame(tick);
  return()=>{alive.current=false;cancelAnimationFrame(frame);colorRenderer.current?.dispose();colorRenderer.current=null;if(recorder.current?.state==="recording")recorder.current.stop();const current=media.current;if(current instanceof HTMLVideoElement){current.pause();current.removeAttribute("src");current.load();}if(outputUrl.current)URL.revokeObjectURL(outputUrl.current);};
 },[selectedUri,photo]);
 async function exportMedia(){
  if(busy||!ready||!draftReady)return;setBusy(true);setError("");setOutput(null);
  const out=document.createElement("canvas");out.width=720;out.height=Math.round(720/settings.ratio/2)*2;
  try{
   let blob:Blob,extension="png";
   if(photo){draw(out,settings);blob=await new Promise<Blob>((resolve,reject)=>out.toBlob(value=>value?resolve(value):reject(Error("Could not export the image.")),"image/png"));}
   else{
    const video=media.current as HTMLVideoElement;
    if(typeof MediaRecorder==="undefined"||!out.captureStream)throw Error("Video export is unavailable in this browser. Your original is unchanged.");
    const mime=["video/mp4;codecs=avc1.42E01E,mp4a.40.2","video/mp4;codecs=avc1,mp4a.40.2","video/webm;codecs=vp9,opus","video/webm"].find(type=>MediaRecorder.isTypeSupported(type));if(!mime)throw Error("No supported video encoder.");
    if(!Number.isFinite(video.duration)||video.duration>30)throw Error("Local video export supports clips up to 30 seconds.");
    extension=mime.startsWith("video/mp4")?"mp4":"webm";
    const audio=new AudioContext(), audioSource=audio.createMediaElementSource(video), audioOut=audio.createMediaStreamDestination();
    audioSource.connect(audioOut);await audio.resume();video.muted=false;video.pause();video.loop=false;video.currentTime=0;
    await new Promise<void>(resolve=>{if(!video.seeking)resolve();else video.addEventListener("seeked",()=>resolve(),{once:true});});
    const stream=out.captureStream(30);audioOut.stream.getAudioTracks().forEach(track=>stream.addTrack(track));
    const encoder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:5000000});recorder.current=encoder;recording.current=true;
    let animation=0,timer:ReturnType<typeof setTimeout>|undefined;
    try{blob=await new Promise<Blob>((resolve,reject)=>{
     const parts:BlobPart[]=[];encoder.ondataavailable=event=>{if(event.data.size)parts.push(event.data);};encoder.onerror=()=>reject(Error("Video export failed."));encoder.onstop=()=>resolve(new Blob(parts,{type:mime}));
     const render=()=>{try{draw(out,settings);if(canvas.current)draw(canvas.current,settings);animation=requestAnimationFrame(render);}catch(e){reject(e);if(encoder.state==="recording")encoder.stop();}};
     video.onended=()=>{if(encoder.state==="recording")encoder.stop();};
     draw(out,settings);encoder.start(100);render();void video.play().catch(()=>reject(Error("Could not play for export.")));
     timer=setTimeout(()=>{reject(Error("Export timed out. Keep the page open and retry."));if(encoder.state==="recording")encoder.stop();},(video.duration+15)*1000);
    });}finally{
     if(timer)clearTimeout(timer);cancelAnimationFrame(animation);if(encoder.state==="recording")encoder.stop();stream.getTracks().forEach(track=>track.stop());audioSource.disconnect();await audio.close();
     const replacement=video.cloneNode(true) as HTMLVideoElement;replacement.muted=true;replacement.loop=true;replacement.playsInline=true;media.current=replacement;video.pause();video.onended=null;if(alive.current)void replacement.play().catch(()=>{});recording.current=false;
    }
   }
   if(!blob.size)throw Error("The export was empty.");
   const dataUri=await new Promise<string>((resolve,reject)=>{
    const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(Error("Could not save the edited file."));reader.readAsDataURL(blob);
   });
   const thumb=document.createElement("canvas");thumb.width=180;thumb.height=Math.round(180/settings.ratio);
   thumb.getContext("2d")?.drawImage(out,0,0,thumb.width,thumb.height);
   const thumbnail=thumb.toDataURL("image/jpeg",.75);
   if(alive.current){if(outputUrl.current)URL.revokeObjectURL(outputUrl.current);outputUrl.current=URL.createObjectURL(blob);setOutput({url:outputUrl.current,extension,dataUri,thumbnail});setTool(null);}
   try {
    const editedId=await saveCreation(dataUri,thumbnail);
    if(alive.current)setSavedId(editedId);
   } catch { if(alive.current)setError("Your export is ready, but the library could not save it. Download it or retry saving."); }
  }catch(e){if(alive.current)setError(e instanceof Error?e.message:"Could not export.");}finally{if(alive.current)setBusy(false);}
 }
 return <div className="addy-editor" data-large-text={fontScale>1.3} style={{"--ae-font-scale":fontScale} as React.CSSProperties}>
 <style>{[
 "html,body,#root{height:100%;margin:0;background:#0b1012}.addy-editor{height:100%;overflow:auto;box-sizing:border-box;background:#0b1012;color:#f4f5f5;padding:16px 22px 24px;font-size:calc(16px * var(--ae-font-scale));font-family:Manrope_400Regular,Arial,sans-serif;scrollbar-width:none}",
 ".addy-editor *{box-sizing:border-box}.addy-editor button,.addy-editor a{font:inherit;color:inherit;cursor:pointer;-webkit-tap-highlight-color:transparent}.addy-editor button:disabled{opacity:.4;cursor:default}.addy-editor button:focus-visible,.addy-editor a:focus-visible{outline:2px solid #00d4c6;outline-offset:3px}",
 ".ae-top{display:flex;align-items:center;gap:12px;margin-bottom:16px}.ae-top h1{font:700 calc(21px * var(--ae-font-scale)) SpaceGrotesk_700Bold,Arial;margin:0;flex:1;min-width:0;overflow-wrap:anywhere}.ae-back{flex-shrink:0;border:0;background:transparent;min-width:44px;min-height:44px;font-size:calc(28px * var(--ae-font-scale))!important;margin-left:-10px}.ae-next{flex-shrink:0;border:1px solid #00c9ba;color:#00d9c9!important;border-radius:22px;background:#00302f;min-height:44px;padding:0 21px;font-size:calc(13px * var(--ae-font-scale))!important}",
 ".ae-preview{margin:auto;max-height:44vh;max-width:100%;border-radius:18px;overflow:hidden;background:#101213;display:flex;justify-content:center}.ae-preview canvas{display:block;max-width:100%;max-height:44vh;object-fit:contain}",
 ".ae-strip{display:flex;gap:9px;margin:16px 0 22px;overflow-x:auto;scrollbar-width:none}.ae-look{overflow-wrap:anywhere;padding:0;min-width:0;flex:1;background:none;border:0;font-size:calc(12px * var(--ae-font-scale))!important;text-align:center}.ae-look img,.ae-look video{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:9px;border:2px solid transparent;display:block;margin-bottom:7px}.ae-look[aria-pressed=true]{color:#00e0cf}.ae-look[aria-pressed=true] img,.ae-look[aria-pressed=true] video{border-color:#00d5c5}",
 ".ae-tools{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.ae-tool{overflow-wrap:anywhere;padding:12px 6px;grid-column:span 2;min-height:88px;border:1px solid transparent;border-radius:13px;background:linear-gradient(135deg,#161c1f,#101619);display:flex;flex-direction:column;gap:12px;align-items:center;justify-content:center;font-size:calc(12px * var(--ae-font-scale))!important}.ae-tool:nth-child(4){grid-column:1/span 2}.ae-tool[aria-pressed=true]{border-color:#00c9b8;color:#00daca;background:#0c2827}",
 ".ae-bottom{display:flex;justify-content:space-between;margin-top:16px}.ae-bottom button{background:none;border:0;color:#9ba7ac;min-width:44px;min-height:44px;font-size:calc(12px * var(--ae-font-scale))}",
 ".ae-panel{margin-top:14px;padding:16px;background:#151d20;border-radius:16px;display:grid;gap:14px}.ae-panel label{font-size:calc(13px * var(--ae-font-scale));display:grid;gap:8px}.ae-panel input[type=range]{width:100%;accent-color:#00c9b8}.ae-panel textarea{width:100%;background:#0a1012;color:white;border:1px solid #394347;border-radius:10px;padding:12px;font:calc(16px * var(--ae-font-scale)) Arial;min-height:80px}.ae-options{display:flex;gap:8px;flex-wrap:wrap}.ae-options button{min-height:44px;border:1px solid #394347;border-radius:10px;background:#101619;padding:8px 12px}.ae-options button[aria-pressed=true]{border-color:#00d9c8;color:#00d9c8}",
 ".ae-note{font-size:calc(12px * var(--ae-font-scale));line-height:1.5;color:#a8b2b6;margin:0}.ae-export{display:block;text-align:center;text-decoration:none;padding:15px;border-radius:14px;background:#00c5ad;color:#002722!important;font-weight:bold}.ae-error{color:#ffb5b5;font-size:calc(13px * var(--ae-font-scale))}",
 ".addy-editor[data-large-text=true] .ae-top{display:grid;grid-template-columns:44px 1fr}.addy-editor[data-large-text=true] .ae-top h1{grid-row:2;grid-column:1/-1}.addy-editor[data-large-text=true] .ae-next{grid-row:1;grid-column:2;justify-self:end}.addy-editor[data-large-text=true] .ae-look{flex:0 0 calc(70px * var(--ae-font-scale));overflow-wrap:normal}.addy-editor[data-large-text=true] .ae-tools{grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr))}.addy-editor[data-large-text=true] .ae-tool{grid-column:auto}",
 "@media(max-width:350px){.addy-editor{padding:12px 16px}.ae-tool{min-height:76px}.ae-strip{gap:6px}.ae-look{overflow-wrap:anywhere;font-size:calc(11px * var(--ae-font-scale))!important}}@media(prefers-reduced-motion:no-preference){.ae-tool,.ae-look img,.ae-look video{transition:background .16s,border-color .16s}}"
 ].join("\n")}</style>
 <header className="ae-top"><button className="ae-back" aria-label={translate("Back to result")} disabled={busy} onClick={()=>void onClose()}>‹</button><h1>{translate("Customize")}</h1><button className="ae-next" disabled={!ready||!draftReady||busy} onClick={()=>void exportMedia()}>{translate(busy?"Exporting…":"Next")}</button></header>
 <div className="ae-preview" style={{maxWidth:(44*settings.ratio)+"vh"}}><canvas aria-label={translate("Edited media preview")} ref={canvas} width={720} height={Math.round(720/settings.ratio/2)*2}/></div>
 {!ready&&!error&&<p className="ae-note">{translate("Loading your media…")}</p>}
 {scenes.length>0?<div className="ae-strip" aria-label={translate("Product scenes")}>{[{id:"",name:"Original",uri:source.uri},...scenes].map(scene=><button key={scene.id} className="ae-look" disabled={busy||!draftReady} aria-label={translate("Scene: {name}", { name: translate(scene.name) })} aria-pressed={(settings.sceneId??"")===scene.id} onClick={()=>change({sceneId:scene.id})}>{photo?<img src={scene.uri} alt=""/>:<video src={scene.uri} muted autoPlay loop playsInline aria-hidden="true"/>}{translate(scene.name)}</button>)}</div>:<div className="ae-strip" aria-label={translate("Color styles")}>{looks.map((look,i)=><button key={look.name} className="ae-look" disabled={busy||!draftReady} aria-label={translate("Style: {name}", { name: translate(look.name) })} aria-pressed={settings.look===i} onClick={()=>change({look:i})}>{poster&&<img src={poster} alt="" style={{filter:look.filter}}/>}{translate(look.name)}</button>)}</div>}
 <div className="ae-tools">{Object.entries(icons).map(([name,path])=><button className="ae-tool" key={name} disabled={busy||!draftReady} aria-pressed={tool===name} onClick={()=>setTool(tool===name?null:name)}><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path}/></svg>{translate(String(name))}</button>)}</div>
 {tool&&<section className="ae-panel" aria-label={translate("Settings: {name}", { name: translate(tool) })}>
 {onScenes&&(tool==="Background"||tool==="Style")&&<button className="ae-export" disabled={busy||!ready} onClick={()=>{
 const original=photo?new Image():document.createElement("video");const capture=()=>{
 const w=original instanceof HTMLVideoElement?original.videoWidth:original.naturalWidth,h=original instanceof HTMLVideoElement?original.videoHeight:original.naturalHeight;
 const image=document.createElement("canvas"),scale=Math.min(1,1024/Math.max(w,h));
 image.width=Math.round(w*scale);image.height=Math.round(h*scale);
 image.getContext("2d")?.drawImage(original,0,0,image.width,image.height);
 void onScenes(image.toDataURL("image/png")).catch(()=>setError("Could not open scene options."));
 };if(original instanceof HTMLVideoElement){original.muted=true;original.playsInline=true;original.onloadeddata=capture;}else original.onload=capture;original.onerror=()=>setError("Could not load the original product image.");original.src=source.uri;
}}>{translate("Change product scene")}</button>}
 {tool==="Background"&&<><label>{translate("Canvas color")}<input aria-label={translate("Canvas color")} type="color" value={settings.background} disabled={busy||!draftReady} onChange={e=>change({background:e.target.value,inset:settings.inset||6})}/></label><label>{translate("Frame spacing")}<input type="range" min="0" max="20" value={settings.inset} disabled={busy||!draftReady} onChange={e=>change({inset:Number(e.target.value)})}/></label><p className="ae-note">{translate("Adds a frame around your media. The product’s original background stays intact.")}</p></>}
 {tool==="Style"&&<><div className="ae-options">{looks.map((look,i)=><button key={look.name} disabled={busy||!draftReady} aria-pressed={settings.look===i} onClick={()=>change({look:i})}>{translate(look.name)}</button>)}</div><p className="ae-note">{translate("Color treatments for this creation.")}</p></>}
 {tool==="Text"&&<><label>{translate("Your text")}<textarea aria-label={translate("Overlay text")} maxLength={120} value={settings.text} disabled={busy||!draftReady} placeholder={translate("Your brand. Your message.")} onChange={e=>change({text:e.target.value})}/></label><label>{translate("Text color")}<input type="color" value={settings.color} disabled={busy||!draftReady} onChange={e=>change({color:e.target.value})}/></label><label>{translate("Size")}<input type="range" min="3" max="12" value={settings.textSize} disabled={busy||!draftReady} onChange={e=>change({textSize:Number(e.target.value)})}/></label><label>{translate("Vertical position")}<input type="range" min="15" max="85" value={settings.textY} disabled={busy||!draftReady} onChange={e=>change({textY:Number(e.target.value)})}/></label></>}
 {tool==="Resize"&&<><div className="ae-options">{[["Portrait",9/16],["Square",1],["Feed",4/5]].map(([name,ratio])=><button key={String(name)} disabled={busy||!draftReady} aria-pressed={settings.ratio===ratio} onClick={()=>change({ratio:Number(ratio)})}>{translate(String(name))}</button>)}</div><div className="ae-options">{[["Fit","contain"],["Fill","cover"]].map(([name,fit])=><button key={fit} disabled={busy||!draftReady} aria-pressed={(settings.fit??"contain")===fit} onClick={()=>change({fit:fit as "contain"|"cover"})}>{translate(String(name))}</button>)}</div>
 {settings.fit==="cover"&&<><p className="ae-note">{translate("Fill crops the edges. Position your product inside the frame.")}</p><label>{translate("Horizontal crop position")}<input aria-label={translate("Horizontal crop position")} type="range" min="0" max="100" value={settings.cropX??50} disabled={busy||!draftReady} onChange={e=>change({cropX:Number(e.target.value)})}/></label><label>{translate("Vertical crop position")}<input aria-label={translate("Vertical crop position")} type="range" min="0" max="100" value={settings.cropY??50} disabled={busy||!draftReady} onChange={e=>change({cropY:Number(e.target.value)})}/></label></>}
 </>}
 {tool==="Filters"&&<><label>{translate("Brightness")}<input type="range" min="70" max="130" value={settings.brightness} disabled={busy||!draftReady} onChange={e=>change({brightness:Number(e.target.value)})}/></label><p className="ae-note">{translate("Combined with your selected color style.")}</p></>}
 </section>}
 <div className="ae-bottom"><button disabled={busy||!draftReady||!history.length} onClick={()=>{setSettings(history[history.length-1]);setHistory(history.slice(0,-1));setOutput(null);}}>{translate("Undo")}</button><button disabled={busy||!draftReady} onClick={()=>change(photo?{...initial,ratio:4/5}:initial)}>{translate("Reset edits")}</button></div>
 {error&&<p role="alert" className="ae-error">{translate(error)}</p>}
 {draftFailed&&<button className="ae-next" disabled={busy} onClick={async()=>{
  setBusy(true);
  try{const fresh=photo?{...initial,ratio:4/5}:initial;await saveDraft(JSON.stringify(fresh));setSettings(fresh);setHistory([]);setDraftFailed(false);setDraftReady(true);setError("");}
  catch{setError("Could not start fresh edits. Free up device storage and try again.");}
  finally{setBusy(false);}
 }}>{translate("Start fresh edits")}</button>}
 {output&&<section className="ae-panel">{!!savedId?<button className="ae-export" onClick={()=>void openCreation(savedId)}>{translate("View saved creation")}</button>:<button className="ae-export" disabled={busy} onClick={()=>{
 setBusy(true);setError("");
 void saveCreation(output.dataUri,output.thumbnail).then(id=>{if(alive.current)setSavedId(id);}).catch(()=>{if(alive.current)setError("Could not save to your library. You can still download this export.");}).finally(()=>{if(alive.current)setBusy(false);});
}}>{translate("Retry library save")}</button>}{saveFile ? <button className="ae-export" disabled={busy} onClick={() => {
 setBusy(true);setError("");
 void fetch(output.url).then(response=>response.blob()).then(blob=>new Promise<string>((resolve,reject)=>{
  const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(Error("Could not prepare sharing."));reader.readAsDataURL(blob);
 })).then(saveFile).catch(e=>setError(e instanceof Error?e.message:"Could not share.")).finally(()=>setBusy(false));
}}>{translate(photo ? "Save or share edited photo" : "Save or share edited video")}</button> : <a className="ae-export" href={output.url} download={"addy-edited."+output.extension}>{translate(photo ? "Save edited photo" : "Save edited video")}</a>}<p className="ae-note">{translate(savedId?"Saved in your library on this device.":"Download before leaving this page to keep your export.")}{" "} {translate("Your original is unchanged")}{output.extension==="webm"?translate(" (WebM format)"):""}.</p></section>}
 </div>;
}
