// Real browser, independent contexts: task selection, play, secrecy and reload.
import os from "os";
import fs from "fs";
import path from "path";
import assert from "node:assert/strict";
import { puppeteer, CHROME_PATH } from "./_resolve.mjs";

const BASE=process.argv[2]||"http://127.0.0.1:8196";
const OUT=process.argv[3]||path.join(os.tmpdir(),"expo-playtest");
const HUMANS=Number(process.env.EXPO_HUMANS||3);
const MISSION=Number(process.env.EXPO_MISSION||0); // optional: play this mission instead of the default
fs.mkdirSync(OUT,{recursive:true});
const errors=[];
const browser=await puppeteer.launch({executablePath:CHROME_PATH,headless:"new",
  userDataDir:path.join(OUT,"browser-profile"),args:["--no-sandbox","--disable-gpu"]});
const pages=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function state(pg){return pg.evaluate(()=>ST);}
async function waitRevision(pg,old){await pg.waitForFunction(r=>ST?.game?.revision>r,{},old);}
async function clickKey(pg,key){await pg.evaluate(k=>{const n=k==="end"?document.getElementById("end"):[...document.querySelectorAll("[data-key]")].find(x=>x.dataset.key===k);if(!n||n.disabled)throw Error("Unavailable "+k);n.click();},key);}
async function crewDecision(pg,key){const old=(await state(pg)).game.revision;await clickKey(pg,key);await waitRevision(pg,old);for(const p of pages){const s=await state(p);if(s.game.proposal&&!s.game.proposal.votes.includes(s.you.pid)){const rev=s.game.revision;await clickKey(p,"agree");await waitRevision(p,rev);}}}
try{
  for(let i=0;i<HUMANS;i++){
    const context=await browser.createBrowserContext(),pg=await context.newPage();
    await pg.setViewport({width:i===0?360:390,height:i===0?740:844,deviceScaleFactor:1});
    pg.on("pageerror",e=>errors.push(e.message));
    await pg.evaluateOnNewDocument(name=>{localStorage.setItem("wc-name",name);},["Ava","Milo","Noor","Iris","Sage"][i]);
    await pg.goto(BASE+"/games/expo/",{waitUntil:"networkidle2"});
    await pg.waitForFunction(()=>ST?.you&&ST.phase==="lobby");
    pages.push(pg);await pg.click("#ready");await pg.waitForFunction(()=>ST.you.ready);
  }
  await pages[0].screenshot({path:path.join(OUT,"lobby-phone.png"),fullPage:true});
  if(MISSION){await pages[0].select("#mission",String(MISSION));await pages[0].waitForFunction(m=>ST.settings.mission===m,{},MISSION);}
  await pages[0].click("#start");
  // A mission with an objective and no tasks opens on the assistance stage.
  await pages[0].waitForFunction(()=>["allocation","assistance"].includes(ST?.game?.stage),{timeout:12000});
  if(MISSION)assert.equal((await state(pages[0])).game.mission.id,MISSION);
  for(let i=0;i<25;i++){
    const s=await state(pages[0]);if(s.game.stage!=="allocation")break;
    let pg;
    for(const p of pages){if((await state(p)).you.pid===s.game.controller)pg=p;}
    assert.ok(pg,"task selector has a browser");
    const own=(await state(pg)).game;
    const task=own.tasks.find(t=>!t.owner&&t.eligible_owners.includes(own.selector));
    if(task){const rev=own.revision;await clickKey(pg,"task:"+task.id);await waitRevision(pg,rev);}
    else{const rev=own.revision;await clickKey(pg,"pass-task");await waitRevision(pg,rev);}
  }
  for(const pg of pages){const s=await state(pg);for(const t of s.game.tasks){if(t.prediction_required&&!t.prediction_committed&&(t.owner===s.you.pid||(t.owner==="tonoja"&&s.game.captain===s.you.pid))){const rev=(await state(pg)).game.revision;await clickKey(pg,"lock:"+t.id);await waitRevision(pg,rev);}}}
  await crewDecision(pages[0],"begin");
  // Select a non-default sonar card, commit it, then verify its public exposure.
  const sonar=await state(pages[0]),opts=sonar.game.me.communication_options;
  if(Object.keys(opts).length){
    const card=Object.keys(opts).at(-1),rev=sonar.game.revision;
    await pages[0].select('select[data-key="sonar-card"]',card);
    await clickKey(pages[0],"communicate");await waitRevision(pages[0],rev);
    assert.ok((await state(pages[0])).game.exposures.some(e=>e.card===card&&e.seat===sonar.you.pid));
    // A shared pool loses one token for everyone; an empty pool leaves nobody any option.
    if(sonar.game.shared_sonar!==null)for(const pg of pages){await waitRevision(pg,rev);const g=(await state(pg)).game;assert.equal(g.shared_sonar,sonar.game.shared_sonar-1);if(!g.shared_sonar)assert.deepEqual(g.me.communication_options,{});}
  }
  await pages[0].screenshot({path:path.join(OUT,"table-phone.png"),fullPage:true});
  for(const pg of pages){const s=await state(pg);assert.equal(s.game.me.hand.length,s.game.hand_counts[s.you.pid]);assert.equal(s.game.planned_tricks,HUMANS===2?13:Math.floor(40/HUMANS));assert.equal(Object.hasOwn(s.game,"hands"),false);}
  // Forged card request must be rejected without changing the domain revision.
  const s=await state(pages[0]);
  await pages[0].evaluate(()=>{const g=ST.game;conn.send({t:"play_card",card:"not-a-card",attempt:g.attempt,revision:g.revision,request:crypto.randomUUID()});});
  await pause(150);assert.equal((await state(pages[0])).game.revision,s.game.revision);
  let pg=pages[0],pre=(await state(pg)).game.me.hand;
  await pg.reload({waitUntil:"networkidle2"});await pg.waitForFunction(()=>ST?.game?.me&&!ST.game.away.length);
  assert.deepEqual((await state(pg)).game.me.hand,pre);
  for(const size of [{width:360,height:740},{width:390,height:844},{width:820,height:1100},{width:1440,height:1000}]){
    await pg.setViewport(size);
    assert.equal(await pg.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,"no horizontal overflow");
    await pg.screenshot({path:path.join(OUT,`table-${size.width}.png`),fullPage:true});
  }
  for(let i=0;i<70;i++){
    const s=await state(pages[0]);if(s.game.result)break;
    const actor=s.game.turn==="tonoja"?s.game.captain:s.game.turn;
    let player;for(const p of pages)if((await state(p)).you.pid===actor)player=p;
    assert.ok(player);const g=(await state(player)).game;assert.ok(g.me.legal_cards.length);
    await clickKey(player,"card:"+g.me.legal_cards[0]);await waitRevision(player,g.revision);
    if(i===0){
      const partial=(await state(player)).game;
      await player.reload({waitUntil:"networkidle2"});await player.waitForFunction(()=>ST?.game?.me&&!ST.game.away.length);
      assert.deepEqual((await state(player)).game.trick,partial.trick);
      assert.deepEqual((await state(player)).game.me.hand,partial.me.hand);
    }
    await pause(115); // Stay below the platform's per-socket action rate limit.
  }
  assert.ok((await state(pages[0])).game.result,"mission reaches a result");
  await pages[0].setViewport({width:390,height:844});
  await pages[0].screenshot({path:path.join(OUT,"result-phone.png"),fullPage:true});
  assert.deepEqual(errors,[]);
  await crewDecision(pages[0],"end");
  console.log(`PASS: live ${HUMANS}-player mission, hostile request, masked frames, reload and four viewports`,OUT);
}finally{await browser.close();}
