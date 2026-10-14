/** GPU fallback for browsers without CanvasRenderingContext2D.filter. */
export function createEditorColorRenderer(){
 const canvas=document.createElement("canvas");
 const gl=canvas.getContext("webgl",{premultipliedAlpha:false,preserveDrawingBuffer:true});
 if(!gl)throw Error("Color rendering is unavailable on this device.");
 const shader=(type:number,source:string)=>{
  const value=gl.createShader(type)!;gl.shaderSource(value,source);gl.compileShader(value);
  if(!gl.getShaderParameter(value,gl.COMPILE_STATUS)){gl.deleteShader(value);throw Error("Could not prepare color rendering.");}return value;
 };
 const vertex=shader(gl.VERTEX_SHADER,"attribute vec2 position; varying vec2 uv; void main(){uv=vec2((position.x+1.0)/2.0,(1.0-position.y)/2.0);gl_Position=vec4(position,0.0,1.0);}");
 const fragment=shader(gl.FRAGMENT_SHADER,`precision mediump float;
 varying vec2 uv; uniform sampler2D image; uniform vec4 treatment; uniform float brightness;
 void main(){vec4 pixel=texture2D(image,uv);vec3 c=pixel.rgb;
 vec3 sepia=vec3(dot(c,vec3(.393,.769,.189)),dot(c,vec3(.349,.686,.168)),dot(c,vec3(.272,.534,.131)));
 c=clamp(mix(c,sepia,treatment.x),0.0,1.0);
 c=clamp((c*treatment.w-.5)*treatment.z+.5,0.0,1.0);
 c=clamp(mix(vec3(dot(c,vec3(.213,.715,.072))),c,treatment.y),0.0,1.0);
 gl_FragColor=vec4(clamp(c*brightness,0.0,1.0),pixel.a);}`);
 const program=gl.createProgram()!;gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error("Could not prepare color rendering.");
 gl.useProgram(program);
 const buffer=gl.createBuffer()!;gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
 const position=gl.getAttribLocation(program,"position");gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
 const texture=gl.createTexture()!;gl.bindTexture(gl.TEXTURE_2D,texture);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
 const treatment=gl.getUniformLocation(program,"treatment"),brightness=gl.getUniformLocation(program,"brightness");
 const input=document.createElement("canvas"),ctx=input.getContext("2d")!;
 let previousSource:CanvasImageSource|undefined,previousKey="";
 const presets=[[0,1,1,1],[.18,1.08,1,1],[0,1,1.05,1.06],[0,.85,.9,1],[0,.72,1.18,1]];
 return {
  render(source:CanvasImageSource,width:number,height:number,look:number,light:number){
   if(gl.isContextLost())throw Error("Color rendering was interrupted. Reopen the editor.");
   const key=[width,height,look,light,source instanceof HTMLVideoElement?Math.floor(source.currentTime*30):0].join(":");
   if(source===previousSource&&key===previousKey&&(source instanceof HTMLImageElement||source instanceof HTMLVideoElement))return canvas;
   const scale=Math.min(1,1280/Math.max(width,height)),w=Math.max(1,Math.round(width*scale)),h=Math.max(1,Math.round(height*scale));
   if(canvas.width!==w||canvas.height!==h){canvas.width=input.width=w;canvas.height=input.height=h;gl.viewport(0,0,w,h);}
   ctx.clearRect(0,0,w,h);ctx.drawImage(source,0,0,w,h);
   gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,input);
   gl.uniform4fv(treatment,presets[look]);gl.uniform1f(brightness,light/100);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
   previousSource=source;previousKey=key;
   return canvas;
  },
  dispose(){gl.deleteTexture(texture);gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);gl.getExtension("WEBGL_lose_context")?.loseContext();},
 };
}
