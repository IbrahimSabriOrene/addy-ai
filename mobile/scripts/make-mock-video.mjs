import { writeFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

const out = new URL("../public/mock/sample-ad.webm", import.meta.url);
const browser = await chromium.launch();
const page = await browser.newPage();

const video = await page.evaluate(async () => {
  const canvas = document.createElement("canvas");
  canvas.width = 540;
  canvas.height = 960;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("No canvas context");

  const stream = canvas.captureStream(30);
  const recorder = new MediaRecorder(stream, {
    mimeType: "video/webm;codecs=vp9",
    videoBitsPerSecond: 2_500_000,
  });
  const chunks = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size) chunks.push(event.data);
  };

  const ease = (x) => 0.5 - Math.cos(Math.PI * x) / 2;
  const roundRect = (x, y, w, h, r) => {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  };

  const drawText = (text, x, y, size, weight = 700, color = "#fff", align = "center") => {
    ctx.font = `${weight} ${size}px Arial`;
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.textBaseline = "middle";
    ctx.fillText(text, x, y);
  };

  const drawMug = (cx, cy, scale, rot) => {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(scale, scale);
    ctx.rotate(rot * 0.04);
    ctx.shadowColor = "rgba(0, 224, 207, 0.5)";
    ctx.shadowBlur = 35;

    const glaze = ctx.createLinearGradient(-80, -130, 95, 120);
    glaze.addColorStop(0, "#f5f0e8");
    glaze.addColorStop(0.5, "#9fcfc2");
    glaze.addColorStop(1, "#23433f");
    ctx.fillStyle = glaze;
    roundRect(-82, -120, 164, 240, 34);
    ctx.fill();

    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.ellipse(0, -118, 78, 21, 0, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = "#d7eee8";
    ctx.lineWidth = 22;
    ctx.beginPath();
    ctx.ellipse(93, -12, 42, 66, 0, -Math.PI / 2, Math.PI / 2);
    ctx.stroke();
    ctx.strokeStyle = "#21413d";
    ctx.lineWidth = 10;
    ctx.stroke();

    ctx.globalAlpha = 0.38;
    ctx.fillStyle = "#fff";
    roundRect(-55, -94, 30, 170, 15);
    ctx.fill();

    ctx.restore();
  };

  const draw = (ms) => {
    const t = (ms % 6000) / 6000;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const bg = ctx.createLinearGradient(0, 0, 0, 960);
    bg.addColorStop(0, "#050506");
    bg.addColorStop(0.55, "#0e0e11");
    bg.addColorStop(1, "#020203");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, 540, 960);

    for (let i = 0; i < 18; i++) {
      const a = (i / 18) * Math.PI * 2 + t * Math.PI * 2;
      const x = 270 + Math.cos(a) * (130 + i * 3);
      const y = 410 + Math.sin(a * 1.3) * 170;
      ctx.globalAlpha = 0.06;
      ctx.fillStyle = i % 2 ? "#00e0cf" : "#e6ac3d";
      ctx.beginPath();
      ctx.arc(x, y, 34 + (i % 4) * 10, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    drawText("MAYA'S CERAMICS", 270, 88, 24, 800, "#00e0cf");
    drawText("NEW DROP", 270, 134, 58, 900);
    drawText("HAND-THROWN GLAZE", 270, 190, 24, 700, "rgba(255,255,255,0.72)");

    ctx.save();
    ctx.translate(270, 585);
    ctx.scale(1 + ease(t) * 0.045, 1);
    const podium = ctx.createLinearGradient(-160, -38, 160, 55);
    podium.addColorStop(0, "#102521");
    podium.addColorStop(0.5, "#00c2a8");
    podium.addColorStop(1, "#071310");
    ctx.fillStyle = podium;
    ctx.shadowColor = "rgba(0, 194, 168, 0.45)";
    ctx.shadowBlur = 35;
    ctx.beginPath();
    ctx.ellipse(0, 0, 160, 48, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    drawMug(270, 430, 1.14 + Math.sin(t * Math.PI * 2) * 0.02, Math.sin(t * Math.PI * 2));

    drawText("Kiln-fresh color.", 270, 710, 38, 900);
    drawText("Ready for every morning ritual.", 270, 760, 24, 600, "rgba(255,255,255,0.72)");

    ctx.fillStyle = "#00c2a8";
    roundRect(143, 825, 254, 64, 22);
    ctx.fill();
    drawText("Shop the drop", 270, 858, 25, 800, "#04201c");

    requestAnimationFrame(draw);
  };

  recorder.start();
  requestAnimationFrame(draw);
  await new Promise((resolve) => setTimeout(resolve, 6200));
  recorder.stop();
  await new Promise((resolve) => (recorder.onstop = resolve));
  const blob = new Blob(chunks, { type: "video/webm" });
  return Array.from(new Uint8Array(await blob.arrayBuffer()));
});

await browser.close();
await writeFile(out, Buffer.from(video));
console.log(out.pathname);
