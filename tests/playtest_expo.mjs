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
const OFFER=process.env.EXPO_OFFER==="offer"; // missions 10 and 13: the captain offers the tasks instead of keeping them
fs.mkdirSync(OUT,{recursive:true});
const errors=[];
const browser=await puppeteer.launch({executablePath:CHROME_PATH,headless:"new",
  userDataDir:path.join(OUT,"browser-profile"),args:["--no-sandbox","--disable-gpu"]});
const pages=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function state(pg){return pg.evaluate(()=>ST);}
async function waitRevision(pg,old){await pg.waitForFunction(r=>ST?.game?.revision>r,{},old);}
async function clickKey(pg,key){await pg.evaluate(k=>{const n=k==="end"?document.getElementById("end"):[...document.querySelectorAll("[data-key]")].find(x=>x.dataset.key===k);if(!n||n.disabled)throw Error("Unavailable "+k);n.click();},key);}
// Every page has drawn the newest revision any page has seen, and nobody is shown as away.
// The script reads whose turn it is from one page and acts on another, so it must never act on
// a page that is a revision behind or still shows a reloading player as away (AVR-254).
async function settle(){
  let rev=-1;
  for(const p of pages)rev=Math.max(rev,(await state(p)).game?.revision??-1);
  for(const p of pages)await p.waitForFunction(r=>ST?.game&&ST.game.revision>=r&&!ST.game.away.length,{},rev);
  return state(pages[0]);
}
// Matrix T43: a control the page shows as unavailable is refused by the server when the very
// request is sent anyway. Returns the server's sentence; the table must not have moved.
async function control(pg,key){return pg.evaluate(k=>{const n=[...document.querySelectorAll("[data-key]")].find(x=>x.dataset.key===k);return n?{disabled:n.disabled,title:n.title}:null;},key);}
async function refusal(pg,msg){
  const before=(await state(pg)).game.revision;
  const said=await pg.evaluate(m=>new Promise((resolve,reject)=>{
    const toast=Hub.toast,timer=setTimeout(()=>{Hub.toast=toast;reject(Error("the server did not refuse "+m.t));},5000);
    Hub.toast=(text,kind)=>{clearTimeout(timer);Hub.toast=toast;toast.call(Hub,text,kind);resolve({text,kind});};
    const g=ST.game;conn.send({...m,attempt:g.attempt,revision:g.revision,request:crypto.randomUUID()});}),msg);
  assert.equal(said.kind,"err");assert.equal((await state(pg)).game.revision,before,"a refused request changes nothing");
  await pause(150);return said.text;
}
const checked={take:false,pass:false,early:false,turn:false,suit:false};
async function crewDecision(pg,key){
  await settle();const old=(await state(pg)).game.revision;await clickKey(pg,key);await waitRevision(pg,old);
  for(const p of pages){
    await settle();const s=await state(p);
    if(s.game.proposal&&!s.game.proposal.votes.includes(s.you.pid)){const rev=s.game.revision;await clickKey(p,"agree");await waitRevision(p,rev);}
  }
  assert.equal((await settle()).game.proposal,null,"the crew decision took effect");
}
// A failed run must not leave its table behind: with every player gone the table could not be
// ended (E-D2) and each later run against this server would wait in the lobby for ever.
async function endTable(){
  const seated=[];
  for(const p of pages){const s=await state(p).catch(()=>null);if(s?.game?.me&&s.phase!=="game_end")seated.push(p);}
  const answer=(p,msg)=>p.evaluate(m=>{const g=ST.game;conn.send({...m,attempt:g.attempt,revision:g.revision,request:crypto.randomUUID()});},msg).catch(()=>{});
  for(let i=0;i<40&&seated.length;i++){
    const s=await state(seated[0]).catch(()=>null);
    if(!s?.game||s.phase==="game_end"||s.phase==="lobby")return;
    const proposal=s.game.proposal;
    if(!proposal)await answer(seated[0],{t:"propose",proposal:{kind:"end"}});
    else for(const p of seated){
      const me=(await state(p).catch(()=>null))?.you?.pid;
      if(me&&!proposal.votes.includes(me)&&(!proposal.recipient||proposal.recipient===me))await answer(p,{t:"confirm",yes:proposal.payload.kind==="end"});
    }
    await pause(250);
  }
  throw new Error("the failed run could not end its table; restart the server before the next run");
}
let finished=false;
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
  const opening=(await state(pages[0])).game;
  if(opening.mission.allocation==="captain_one"){
    // The captain keeps the tasks at once, or offers them and only the recipient answers.
    let cap;const others=[];
    for(const p of pages){if((await state(p)).you.pid===opening.captain)cap=p;else others.push(p);}
    const keep=!OFFER&&opening.tasks.every(t=>t.eligible_owners.includes(opening.captain));
    const target=keep?opening.captain:(await state(others[0])).you.pid;
    await cap.select('select[data-key="all-owner"]',target);
    await clickKey(cap,"all-tasks");
    for(const p of pages)await waitRevision(p,opening.revision);
    if(!keep){
      const asked=(await state(cap)).game.proposal;
      assert.equal(asked.recipient,target);
      for(const p of [cap,...others.slice(1)])assert.equal(await p.evaluate(()=>Boolean(document.querySelector('[data-key="agree"],[data-key="decline"]'))),false,"only the recipient may answer an offer");
      const rev=(await state(others[0])).game.revision;await clickKey(others[0],"agree");
      for(const p of pages)await waitRevision(p,rev);
    }
    const after=(await state(pages[0])).game;
    assert.equal(after.proposal,null);assert.ok(after.tasks.every(t=>t.owner===target));
  }
  for(let i=0;i<25;i++){
    const s=await settle();if(s.game.stage!=="allocation")break;
    let pg;
    for(const p of pages){if((await state(p)).you.pid===s.game.controller)pg=p;}
    assert.ok(pg,"task selector has a browser");
    const own=(await state(pg)).game;
    const idle=pages.find(p=>p!==pg),open=own.tasks.find(t=>!t.owner);
    if(!checked.take&&open&&(await control(idle,"task:"+open.id))){
      // Another seat's selection: the button is disabled and the request is refused (the two
      // sentences differ, AVR-263, so only the refusal is asserted).
      assert.equal((await control(idle,"task:"+open.id)).disabled,true);
      await refusal(idle,{t:"choose_task",task:open.id});checked.take=true;
    }
    // Pass while passing is allowed, so the run reaches a seat that may not pass.
    const pass=await control(pg,"pass-task");
    if(pass&&!pass.disabled){const rev=own.revision;await clickKey(pg,"pass-task");await waitRevision(pg,rev);continue;}
    if(pass&&!checked.pass){assert.equal(pass.title,await refusal(pg,{t:"pass_task"}));checked.pass=true;}
    const task=own.tasks.find(t=>!t.owner&&t.eligible_owners.includes(own.selector));
    if(task){const rev=own.revision;await clickKey(pg,"task:"+task.id);await waitRevision(pg,rev);}
    else{const rev=own.revision;await clickKey(pg,"pass-task");await waitRevision(pg,rev);}
  }
  await settle();
  for(const pg of pages){const s=await state(pg);for(const t of s.game.tasks){if(t.prediction_required&&!t.prediction_committed&&(t.owner===s.you.pid||(t.owner==="tonoja"&&s.game.captain===s.you.pid))){const rev=(await state(pg)).game.revision;await clickKey(pg,"lock:"+t.id);await waitRevision(pg,rev);}}}
  {
    // Before the crew begins, every hand card is disabled with the view's reason and the server
    // refuses a play (the two sentences differ: E-D8, AVR-263).
    const early=(await settle()).game,card=early.me.hand[0],shown=await control(pages[0],"card:"+card);
    assert.equal(early.stage,"assistance");assert.equal(shown.disabled,true);assert.equal(shown.title,early.me.play_reason);
    await refusal(pages[0],{t:"play_card",card});checked.early=true;
  }
  await crewDecision(pages[0],"begin");
  // Select a non-default sonar card, commit it, then verify its public exposure.
  const sonar=await settle(),opts=sonar.game.me.communication_options;
  if(Object.keys(opts).length){
    const card=Object.keys(opts).at(-1),rev=sonar.game.revision;
    await pages[0].select('select[data-key="sonar-card"]',card);
    await clickKey(pages[0],"communicate");await waitRevision(pages[0],rev);
    assert.ok((await state(pages[0])).game.exposures.some(e=>e.card===card&&e.seat===sonar.you.pid));
    // A shared pool loses one token for everyone; an empty pool leaves nobody any option.
    if(sonar.game.shared_sonar!==null)for(const pg of pages){await waitRevision(pg,rev);const g=(await state(pg)).game;assert.equal(g.shared_sonar,sonar.game.shared_sonar-1);if(!g.shared_sonar)assert.deepEqual(g.me.communication_options,{});}
  }
  await pages[0].screenshot({path:path.join(OUT,"table-phone.png"),fullPage:true});
  await settle();
  for(const pg of pages){const s=await state(pg);assert.equal(s.game.me.hand.length,s.game.hand_counts[s.you.pid]);assert.equal(s.game.planned_tricks,HUMANS===2?13:Math.floor(40/HUMANS));assert.equal(Object.hasOwn(s.game,"hands"),false);}
  // Forged card request must be rejected without changing the domain revision.
  const s=await settle();
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
    const s=await settle();if(s.game.result)break;
    if(i===2&&process.env.EXPO_FORCE_FAIL)throw new Error("forced failure mid-round (EXPO_FORCE_FAIL)");
    const actor=s.game.turn==="tonoja"?s.game.captain:s.game.turn;
    let player;for(const p of pages)if((await state(p)).you.pid===actor)player=p;
    assert.ok(player);const g=(await state(player)).game;assert.ok(g.me.legal_cards.length);
    if(!checked.turn){
      // A card that cannot be played says why in the server's own words (matrix T43): the
      // disabled card's reason equals the rejection the server sends for that very request.
      const idle=pages.find(p=>p!==player),seen=(await state(idle)).game,card=seen.me.hand[0];
      const shown=await control(idle,"card:"+card);
      assert.equal(shown.disabled,true);assert.equal(shown.title,seen.me.play_reason);
      assert.equal(shown.title,await refusal(idle,{t:"play_card",card}));checked.turn=true;
    }
    const offSuit=s.game.turn==="tonoja"?null:g.me.hand.find(c=>!g.me.legal_cards.includes(c));
    if(offSuit&&!checked.suit){
      const shown=await control(player,"card:"+offSuit);
      assert.equal(shown.disabled,true);
      assert.equal(shown.title,await refusal(player,{t:"play_card",card:offSuit}));checked.suit=true;
    }
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
  assert.ok(checked.early&&checked.turn,"unavailable controls were checked against the server");
  // Clockwise selection always reaches another seat's task and a seat that may not pass. An
  // off-suit card is checked whenever the deal offers one before the mission ends.
  if(["normal","skip_captain"].includes(opening.mission.allocation)&&opening.tasks.length)assert.ok(checked.take&&checked.pass,"task selection refusals were checked");
  await crewDecision(pages[0],"end");
  await pages[0].waitForFunction(()=>ST.phase==="game_end"||ST.phase==="lobby");
  finished=true;
  console.log(`PASS: live ${HUMANS}-player mission, hostile request, masked frames, reload and four viewports; refusals checked: ${Object.keys(checked).filter(k=>checked[k]).join(", ")}`,OUT);
}finally{
  try{if(!finished)await endTable();}
  finally{await browser.close();}
}
