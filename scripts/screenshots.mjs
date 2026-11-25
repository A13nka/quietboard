// Screenshots der Demo-Oberfläche fürs README (Chrome DevTools Protocol, keine npm-Pakete, Node 22+).
// Vorher: make dev (Demo-Modus).  Aufruf: make screenshots  bzw.  node scripts/screenshots.mjs [url] [ordner]
// Chrome-Pfad über CHROME=… (Standard: macOS-Pfad bzw. google-chrome).
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const url = process.argv[2] || "http://127.0.0.1:8088/";
const out = process.argv[3] || "docs/assets/screens";
const bin = process.env.CHROME || (process.platform === "darwin" ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : "google-chrome");
const chrome = spawn(bin, [
  "--headless=new", "--remote-debugging-port=9333", "--no-first-run", "--hide-scrollbars",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "qbshots-"))}`, "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let targets;
for (let i = 0; i < 50; i++) {
  try { targets = await (await fetch("http://127.0.0.1:9333/json")).json(); break; } catch { await sleep(200); }
}
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJs = (expression) => send("Runtime.evaluate", { expression, awaitPromise: true });

async function shot(name, { w, h, dpr, scheme, tab, js }) {
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: dpr, mobile: w < 700 });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
  await send("Page.navigate", { url });
  await sleep(2500);
  if (tab) { await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(tab)})?.click()`); await sleep(800); }
  if (js) { await evalJs(js); await sleep(800); }
  const r = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(out, name + ".png"), Buffer.from(r.result.data, "base64"));
  console.log("ok", name);
}

const phone = { w: 390, h: 844, dpr: 2 };
await send("Page.enable");
for (const scheme of ["dark", "light"]) {
  await shot(`overview-${scheme}`, { ...phone, scheme });
  await shot(`jobs-${scheme}`, { ...phone, scheme, tab: "Jobs" });
  await shot(`updates-${scheme}`, { ...phone, scheme, tab: "Updates" });
}
ws.close(); chrome.kill();
