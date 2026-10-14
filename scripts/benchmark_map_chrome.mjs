// Real browser driver without adding a Playwright dependency to the application.
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import assert from "node:assert/strict";

const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const chrome = spawn(spec.chrome, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-extensions", "--remote-debugging-port=0", "--window-size=1280,900",
  `--user-data-dir=${join(spec.work,"chrome")}`, "about:blank"], { windowsHide: true, stdio: ["ignore","ignore","pipe"] });
let socket;
try {
  const endpoint = await new Promise((resolve,reject) => {
    let output = "";
    const timeout = setTimeout(()=>reject(new Error("Chrome did not start: "+output)),30000);
    chrome.stderr.on("data", chunk => { output+=chunk; const match=output.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timeout); resolve(match[1]); } });
    chrome.on("error",reject);
    chrome.on("exit",code=>{ clearTimeout(timeout); reject(new Error("Chrome exited: "+code)); });
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  let sequence=0;
  const pending=new Map();
  socket.addEventListener("close",()=>{
    for(const task of pending.values()) { clearTimeout(task.timer); task.reject(new Error("Chrome debugging connection closed")); }
    pending.clear();
  });
  socket.addEventListener("message", event=>{
    const message=JSON.parse(event.data), task=pending.get(message.id);
    if (task) { pending.delete(message.id); clearTimeout(task.timer); message.error?task.reject(new Error(JSON.stringify(message.error))):task.resolve(message.result); }
  });
  const call=(method,params={},sessionId)=>new Promise((resolve,reject)=>{
    const id=++sequence, timer=setTimeout(()=>{pending.delete(id);reject(new Error("CDP timeout: "+method));},180000);
    pending.set(id,{resolve,reject,timer}); socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
  });
  const all=[];
  const browser=await call("Browser.getVersion");
  for (let iteration=0;iteration<=spec.repeats;iteration++) {
    const pair={};
    for (const variant of iteration%2===0?["before","after"]:["after","before"]) {
      await fetch(`${spec.base}/benchmark/reset/${variant}`,{method:"POST"});
      const {targetId}=await call("Target.createTarget",{url:"about:blank"});
      const {sessionId}=await call("Target.attachToTarget",{targetId,flatten:true});
      await call("Page.enable",{},sessionId);
      await call("Network.enable",{},sessionId);
      await call("Network.setCacheDisabled",{cacheDisabled:true},sessionId);
      await call("Page.navigate",{url:spec.base+"/benchmark"},sessionId);
      const result=await call("Runtime.evaluate",{expression:`(async()=>{
        const deadline=Date.now()+30000; while(!window.runBenchmark) { if(Date.now()>deadline) throw new Error('Map page did not load'); await new Promise(r=>setTimeout(r,20)); }
        return await window.runBenchmark('${variant}'); })()`,awaitPromise:true,returnByValue:true},sessionId);
      await call("Target.closeTarget",{targetId});
      if(result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      pair[variant]=result.result.value;
    }
    for(let i=0;i<pair.before.length;i++) {
      assert.deepEqual(pair.after[i].cells,pair.before[i].cells,pair.before[i].name+": displayed chargers changed");
      assert.ok(pair.after[i].dom_markers>0,"No visible charger bubbles");
    }
    assert.equal(pair.after.find(row=>row.name==="Repeat unchanged viewport").requests,0);
    assert.equal(pair.after.find(row=>row.name==="Repeat unchanged viewport").created,0);
    if(iteration) all.push(pair);
  }
  process.stdout.write(JSON.stringify({browser,runs:all}));
} finally {
  socket?.close(); chrome.kill();
  await new Promise(resolve=>{
    if(chrome.exitCode!==null || chrome.signalCode!==null) return resolve();
    const timeout=setTimeout(resolve,5000);
    chrome.once("exit",()=>{clearTimeout(timeout);resolve();});
  });
}
