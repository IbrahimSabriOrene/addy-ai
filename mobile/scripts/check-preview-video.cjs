const { chromium } = require('playwright');
(async()=>{const b=await chromium.launch({headless:true});const p=await b.newPage();await p.goto('http://localhost:8081',{waitUntil:'domcontentloaded'});
for(const name of ['pedestal_spin','skincare_glow','bakery_morning']){
 const result=await p.evaluate(async name=>{const video=document.createElement('video');video.src='/previews/'+name+'.mp4';video.muted=true;document.body.append(video);await new Promise((resolve,reject)=>{video.onloadeddata=resolve;video.onerror=reject;});await video.play();await new Promise(resolve=>setTimeout(resolve,1200));video.pause();const r={name,width:video.videoWidth,height:video.videoHeight,duration:video.duration,audioBytes:video.webkitAudioDecodedByteCount};video.remove();return r;},name);console.log(JSON.stringify(result));}
await b.close();})().catch(e=>{console.error(e);process.exit(1)});
