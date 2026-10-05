// Real browser, independent contexts: task selection, play, secrecy and reload, at a standalone
// table (the crew decides everything). The one-viewport phone contract of AVR-275 is asserted
// throughout (_expo_phone.mjs); playtest_expo_party.mjs covers a Party round and its host.
// AVR-267: the five zones, the crew strip, the shared trick, the hand's card states, the helmet
// radio (Burst Transmission), the result's cause, and the presentation director: that it sends
// nothing, fits a trick's resolution inside the server's hold, and settles to the static state
// on a reload. Run it at every tier: EXPO_FX=high|medium|low|off, EXPO_MOTION=reduced.
import os from "os";
import fs from "fs";
import path from "path";
import assert from "node:assert/strict";
import { puppeteer, CHROME_PATH } from "./_resolve.mjs";
import { PHONES, oneViewport, onScreen, playCard, resultOwnsTheScreen, clickKey, withLongText, touchTargets, modalHolds, focused,
  FX, EXPECT_FX, presentation, directorSentNothing, crewLegible, trickShows, legalCardsLookAlike } from "./_expo_phone.mjs";

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
// Every page has drawn the newest revision any page has seen, and nobody is shown as away.
// The script reads whose turn it is from one page and acts on another, so it must never act on
// a page that is a revision behind or still shows a reloading player as away (AVR-254), nor
// while a completed trick is still resolving: nobody can play until the server settles it (AVR-246).
async function settle(){
  let rev=-1;
  for(const p of pages)rev=Math.max(rev,(await state(p)).game?.revision??-1);
  for(const p of pages)await p.waitForFunction(r=>ST?.game&&ST.game.revision>=r&&!ST.game.away.length&&!ST.game.resolving,{},rev);
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
// AVR-267: what the run saw of the presentation, reported at the end.
const pres={radio:false,marker:false,hold:0,heldReload:false,looks:0};
const DIRECTOR=FX!=="off";
// What the director has done on this page since it loaded: effects, and why it settled.
const directed=pg=>pg.evaluate(()=>director?{performed:director.stats.performed.map(p=>p.effect),settled:[...director.stats.settled],errors:director.stats.errors,lastTrick:director.stats.lastTrick}:null);
const running=(pg,tag)=>pg.evaluate(t=>document.getAnimations().filter(a=>String(a.id).startsWith("expo-fx:"+t)&&a.playState==="running").length,tag);
async function crewDecision(pg,key){
  await settle();const old=(await state(pg)).game.revision;await clickKey(pg,key);await waitRevision(pg,old);
  for(const p of pages){
    await settle();const s=await state(p);
    if(s.game.proposal&&!s.game.proposal.votes.includes(s.you.pid)){
      // AVR-266: whoever still has to answer sees the question and both answers without
      // scrolling, and the status line (the live region) says a decision is waiting.
      for(const k of ["agree","decline"])await onScreen(p,k,"a pending crew decision");
      assert.match(await p.evaluate(()=>document.getElementById("status").textContent),/^Your answer is needed/);
      assert.equal(await p.evaluate(()=>document.getElementById("status").getAttribute("aria-live")),"polite");
      if(!s.game.result)await oneViewport(p,"a pending crew decision");
      const rev=s.game.revision;await clickKey(p,"agree");await waitRevision(p,rev);
    }
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
// A card that completes a trick: the server holds the table (resolving) and the director has
// that long, and no longer, to show who won. Checked on the first tricks that are held.
async function holdCheck(player){
  const held=(await state(player)).game;
  if(!held.resolving||pres.hold>=3)return;
  const other=pages.find(p=>p!==player);
  await other.waitForFunction(r=>ST.game.revision>=r,{},held.revision);
  const snap=await other.evaluate(()=>ST);          // the view of a table that is resolving
  await trickShows(other,"a resolving trick");
  assert.equal(await other.evaluate(()=>document.getElementById("game").inert),false,"nothing but the server holds the table");
  if(!snap.game.resolving)return;                    // this page was told only after the settle
  if(!pres.hold)await other.screenshot({path:path.join(OUT,"trick-resolving.png")});
  assert.equal(await other.evaluate(()=>document.getElementById("hand-reason").textContent),snap.game.me.play_reason,"the hold is said in the words the server gives");
  assert.match(await other.evaluate(()=>document.getElementById("status").textContent),/Latest: \w+ won trick \d+ with \d \w+/,"the resolved trick is words in the live region");
  if(DIRECTOR&&EXPECT_FX!=="low"){
    const d=await directed(other),t=d.lastTrick;
    assert.ok(t&&t.until===snap.game.resolving.until,"the director timed the trick against the hold");
    assert.ok(t.budget>0&&d.performed.includes("trick-resolution"),"the resolution was presented");
    assert.ok(t.ends<=t.until*1000,`the resolution ends inside the hold (${Math.round(t.until*1000-t.ends)} ms to spare)`);
    assert.ok(t.budget<=await other.evaluate(()=>ExpoDirector.TIMING.trick)&&t.budget<1000,"an ordinary resolution is under a second");
  }
  // When the server lets go, the resolution is over: nothing of it is still running.
  await other.waitForFunction(()=>!ST.game.resolving);
  assert.equal(await running(other,"trick"),0,"the presentation of the trick ended with the hold");
  if(DIRECTOR&&!pres.heldReload){
    // Reconnect during a resolving hold, with the very view the server sent for it: the page
    // lands on the static state and replays nothing.
    const now=await other.evaluate(()=>ST);
    await other.evaluate(st=>{director.resync();render(st);},snap);
    assert.equal(await running(other,"trick"),0,"a view that arrives after a reconnect is not replayed");
    assert.equal((await directed(other)).settled.at(-1),"first-view");
    await trickShows(other,"a resolving trick after a reconnect");await oneViewport(other,"a resolving trick after a reconnect");
    await other.evaluate(st=>{director.resync();render(st);},now);
    pres.heldReload=true;
  }
  pres.hold++;
}
let finished=false;
try{
  for(let i=0;i<HUMANS;i++){
    const context=await browser.createBrowserContext(),pg=await context.newPage();
    await pg.setViewport({...PHONES[i%PHONES.length],deviceScaleFactor:1});
    pg.on("pageerror",e=>errors.push(e.message));
    await presentation(pg);
    await pg.evaluateOnNewDocument(name=>{localStorage.setItem("wc-name",name);},["Ava","Milo","Noor","Iris","Sage"][i]);
    await pg.goto(BASE+"/games/expo/",{waitUntil:"networkidle2"});
    await pg.waitForFunction(()=>ST?.you&&ST.phase==="lobby");
    pages.push(pg);await pg.click("#ready");await pg.waitForFunction(()=>ST.you.ready);
  }
  await pages[0].screenshot({path:path.join(OUT,"lobby-phone.png")});
  if(MISSION){await pages[0].select("#mission",String(MISSION));await pages[0].waitForFunction(m=>ST.settings.mission===m,{},MISSION);}
  await pages[0].click("#start");
  // A mission with an objective and no tasks opens on the assistance stage.
  await pages[0].waitForFunction(()=>["allocation","assistance"].includes(ST?.game?.stage),{timeout:12000});
  if(MISSION)assert.equal((await state(pages[0])).game.mission.id,MISSION);
  const opening=(await state(pages[0])).game;
  await pause(200);
  for(const p of pages)await oneViewport(p,"the opening stage");
  for(const p of pages)await crewLegible(p,"the opening stage");
  // A table that starts in front of this page is a mission start: at the high tier the director
  // briefs it, inside the mission stage, and nothing is covered or disabled meanwhile.
  if(EXPECT_FX==="high"){
    const brief=await directed(pages[0]);
    assert.ok(brief.performed.includes("briefing"),"the mission start is briefed at the high tier");
    assert.equal(await pages[0].evaluate(()=>getComputedStyle(document.getElementById("briefing")).pointerEvents),"none","the briefing takes no input");
    assert.equal(await pages[0].evaluate(()=>document.getElementById("game").inert),false,"the board stays live under the briefing");
    assert.ok(await pages[0].evaluate(()=>ExpoDirector.TIMING.briefing>=5000&&ExpoDirector.TIMING.briefing<=7000),"the briefing is 5 to 7 seconds");
    // A key (or a tap) ends it at once.
    await pages[0].keyboard.press("Shift");
    assert.equal(await running(pages[0],"cine"),0,"a key ends the briefing");
  }else if(DIRECTOR)assert.ok(!(await directed(pages[0])).performed.includes("briefing"),"no cinematic beat below the high tier");
  // EXPO sends nobody to the retired LAN Games hub: no link to "/" exists on the page.
  for(const p of pages)assert.deepEqual(await p.evaluate(()=>[...document.querySelectorAll("a[href]")].map(a=>new URL(a.href).pathname).filter(x=>x==="/"||x.startsWith("/shared/hub"))),[],"no link to the LAN Games hub");
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
    // The reason is words on the page, not only a title a phone never shows.
    assert.equal(await pages[0].evaluate(()=>document.getElementById("hand-reason").textContent),early.me.play_reason);
    for(const p of pages)await oneViewport(p,"before the mission begins");
    await refusal(pages[0],{t:"play_card",card});checked.early=true;
  }
  await crewDecision(pages[0],"begin");
  // The helmet radio (Burst Transmission). It opens in place: the rest of the board steps back,
  // only the cards the server offers are lit, only the meanings the server offers are shown, and
  // nothing is sent until Transmit. The card then keeps its public marker in the hand.
  const sonar=await settle(),opts=sonar.game.me.communication_options;
  {
    const pg=pages[0];
    assert.equal((await control(pg,"radio")).disabled,false,"the radio is always reachable from the hand");
    await clickKey(pg,"radio");
    assert.equal(await pg.evaluate(()=>document.getElementById("game").classList.contains("radio-mode")&&Boolean(document.querySelector(".radio-console"))),true,"the radio opens in place");
    await oneViewport(pg,"the radio open");await touchTargets(pg,"the radio open");
    const lit=await pg.evaluate(()=>({open:[...document.querySelectorAll("#hand button.card")].filter(n=>!n.disabled).map(n=>n.dataset.card).sort(),
      dim:parseFloat(getComputedStyle(document.getElementById("seats")).opacity),hand:parseFloat(getComputedStyle(document.getElementById("hand-panel")).opacity),
      rule:document.querySelector(".radio-console .why").textContent,state:document.getElementById("radio-chip").textContent,said:document.getElementById("hand-reason").textContent}));
    assert.deepEqual(lit.open,Object.keys(opts).sort(),"only the cards the server offers for transmission are lit");
    assert.ok(lit.dim<1&&lit.hand===1,"what is not needed steps back; the hand does not");
    // The fiction names the state; the rule is said in plain words beside it.
    const mode=sonar.game.communication;
    assert.match(lit.state,{normal:/Radio clear/,currents:/Radio degraded/,rapture:/Radio shared · \d+ left/,none:/Radio off/}[mode]);
    assert.match(lit.rule,{normal:/one Burst Transmission each/,currents:/its meaning .* stays hidden/,rapture:/one supply of transmissions/,none:/allows no communication/}[mode]);
    assert.equal((await control(pg,"transmit")).disabled,true,"nothing can be sent before a card is chosen");
    if(Object.keys(opts).length){
      const card=Object.keys(opts).at(-1),rev=sonar.game.revision;
      await clickKey(pg,"card:"+card);
      assert.equal((await state(pg)).game.revision,rev,"choosing a card transmits nothing");
      assert.deepEqual(await pg.evaluate(()=>[...document.querySelectorAll('[data-key^="radio-meaning:"]')].map(n=>n.dataset.key.slice(14))),opts[card],"only the meanings the server offers are shown");
      if(opts[card].length>1)await clickKey(pg,"radio-meaning:"+opts[card][0]);
      await oneViewport(pg,"the radio with a card chosen");
      await pg.screenshot({path:path.join(OUT,"radio-open.png")});
      await clickKey(pg,"transmit");await waitRevision(pg,rev);
      assert.equal(await pg.evaluate(()=>document.getElementById("game").classList.contains("radio-mode")),false,"the radio closes after transmitting");
      assert.equal(await focused(pg),"radio","focus goes back to the radio control");
      const sent=(await state(pg)).game;
      assert.ok(sent.exposures.some(e=>e.card===card&&e.seat===sonar.you.pid));
      // The marker: on the card in the sender's hand, on the sender's tile for everyone, in words.
      const mine=sent.exposures.find(e=>e.seat===sonar.you.pid);
      const mark=await pg.evaluate(c=>{const n=document.querySelector(`#hand [data-card="${c}"]`);return {mark:n.querySelector(".mark")?.textContent||"",said:n.getAttribute("aria-label")};},card);
      assert.match(mark.mark,{highest:/HIGH/,lowest:/LOW/,only:/ONLY/}[mine.assertion]||/SENT/,"the transmitted card keeps its marker in the hand");
      assert.match(mark.said,/transmitted/);pres.marker=true;
      await settle();
      for(const p of pages){
        const told=await p.evaluate(seat=>({tile:document.querySelector(`#seats [data-seat="${seat}"] .seat-radio`).textContent,news:document.getElementById("stage-news").textContent,live:document.getElementById("status").textContent}),sonar.you.pid);
        assert.match(told.tile,/^\d[○△□×]/,"the sender's tile shows the transmitted card to everyone");
        assert.match(told.news,/Ava radioed \d \w+/,"the transmission is words on the mission stage");
        assert.match(told.live,/Latest: Ava radioed/,"and in the live region");
      }
      if(DIRECTOR&&EXPECT_FX!=="low")assert.ok((await directed(pages[1])).performed.includes("radio-burst"),"the others get a radio pulse");
      // A shared pool loses one token for everyone; an empty pool leaves nobody any option.
      if(sonar.game.shared_sonar!==null)for(const p of pages){await waitRevision(p,rev);const g=(await state(p)).game;assert.equal(g.shared_sonar,sonar.game.shared_sonar-1);if(!g.shared_sonar)assert.deepEqual(g.me.communication_options,{});}
      // The transmission is used: the radio still opens, and says why nothing can be sent.
      await clickKey(pg,"radio");
      if(!Object.keys((await state(pg)).game.me.communication_options).length){
        assert.match(await pg.evaluate(()=>document.querySelector(".radio-console").innerText),/Nothing can be transmitted right now/,"an unavailable radio says why, in words");
        assert.equal(await pg.evaluate(()=>[...document.querySelectorAll("#hand button.card")].every(n=>n.disabled)),true);
      }
      await pg.keyboard.press("Escape");
      assert.equal(await pg.evaluate(()=>document.getElementById("game").classList.contains("radio-mode")),false,"Escape closes the radio");
      pres.radio=true;
    }else{
      assert.match(await pg.evaluate(()=>document.querySelector(".radio-console").innerText),/Nothing can be transmitted/,"an unavailable radio says why, in words");
      await clickKey(pg,"radio");
    }
  }
  await pages[0].screenshot({path:path.join(OUT,"table-phone.png")});
  await settle();
  for(const pg of pages){const s=await state(pg);assert.equal(s.game.me.hand.length,s.game.hand_counts[s.you.pid]);assert.equal(s.game.planned_tricks,HUMANS===2?13:Math.floor(40/HUMANS));assert.equal(Object.hasOwn(s.game,"hands"),false);}
  // Forged card request must be rejected without changing the domain revision.
  const s=await settle();
  await pages[0].evaluate(()=>{const g=ST.game;conn.send({t:"play_card",card:"not-a-card",attempt:g.attempt,revision:g.revision,request:crypto.randomUUID()});});
  await pause(150);assert.equal((await state(pages[0])).game.revision,s.game.revision);
  let pg=pages[0],pre=(await state(pg)).game.me.hand;
  await pg.reload({waitUntil:"networkidle2"});await pg.waitForFunction(()=>ST?.game?.me&&!ST.game.away.length);
  assert.deepEqual((await state(pg)).game.me.hand,pre);
  for(const size of [...PHONES,{width:820,height:1100},{width:1440,height:1000}]){
    await pg.setViewport(size);await pause(60);
    assert.equal(await pg.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,"no horizontal overflow");
    await oneViewport(pg,"the table");
    if(size.width<600){await touchTargets(pg,"the table");await withLongText(pg,async()=>{await oneViewport(pg,"the table at its fullest");await touchTargets(pg,"the table at its fullest");});}
    await pg.screenshot({path:path.join(OUT,`table-${size.width}x${size.height}.png`)});
  }
  {
    // On a short screen the status line shares the top bar and "Connected" is not spelled out;
    // a lost connection still is, in words and not only by the colour of the dot.
    await pg.setViewport(PHONES[4]);await pause(60);
    const words=()=>pg.evaluate(()=>{updateConnection();const n=document.getElementById("conn");return {text:n.textContent,shown:getComputedStyle(n).display!=="none"};});
    assert.deepEqual(await words(),{text:"Connected",shown:false});
    await pg.evaluate(()=>{window.__ws=conn.ws;conn.ws=null;});
    assert.deepEqual(await words(),{text:"Reconnecting…",shown:true},"a lost connection is said in words on a short screen");
    await oneViewport(pg,"while reconnecting");
    await pg.evaluate(()=>{conn.ws=window.__ws;});
    assert.deepEqual(await words(),{text:"Connected",shown:false});
  }
  await pg.setViewport(PHONES[0]);
  // Every secondary surface opens over the board and leaves it where it was.
  // (AVR-267: the crew strip opens the crew, the objectives open the tasks, the log is beside them.)
  const firstSeat=(await state(pg)).game.seats[0];
  const OPENERS={crew:`[data-key="seat:${firstSeat}"]`,tasks:'[data-key="objectives"]',history:'.tab[data-sheet="history"]'};
  for(const sheet of ["crew","tasks","history"]){
    await pg.click(OPENERS[sheet]);
    assert.equal(await pg.evaluate(()=>!document.getElementById("sheet").hidden&&document.getElementById("sheet-body").children.length>0),true,sheet+" sheet opens");
    await oneViewport(pg,"with the "+sheet+" sheet open");
    await touchTargets(pg,"the "+sheet+" sheet");
    await modalHolds(pg,"sheet","the "+sheet+" sheet");
    // Escape closes it and focus goes back to the tab that opened it.
    await pg.keyboard.press("Escape");
    assert.equal(await pg.evaluate(()=>document.getElementById("sheet").hidden&&!document.getElementById("game").inert),true,sheet+" sheet closes and the board is live again");
    assert.equal(await pg.evaluate(sel=>document.activeElement===document.querySelector(sel),OPENERS[sheet]),true,"focus returns to what opened the "+sheet+" sheet");
    await pg.click(OPENERS[sheet]);
    await pg.click("#sheet-close");
    assert.equal(await pg.evaluate(sel=>document.activeElement===document.querySelector(sel),OPENERS[sheet]),true,"focus returns to what opened the "+sheet+" sheet after Close");
  }
  if(DIRECTOR&&process.env.EXPO_MOTION!=="reduced"){
    // How much the board moves is this browser's own choice, in the table menu: it changes the
    // tier at once and nothing else. (With reduced motion on, the menu says so instead.)
    await pg.click("#menu-toggle");
    const before=(await state(pg)).game.revision;
    await touchTargets(pg,"the table menu");
    await clickKey(pg,"fx:low");
    assert.equal(await pg.evaluate(()=>document.documentElement.dataset.expoFx),"low","Still is the low tier");
    assert.equal(await pg.evaluate(()=>getComputedStyle(document.querySelector(".mstage-art .h1")).animationName),"none","no ambient motion at the low tier");
    await clickKey(pg,"fx:"+EXPECT_FX);
    assert.equal(await pg.evaluate(()=>document.documentElement.dataset.expoFx),EXPECT_FX);
    if(EXPECT_FX==="high")assert.notEqual(await pg.evaluate(()=>getComputedStyle(document.querySelector(".mstage-art .h1")).animationName),"none","the high tier has an ambient stage");
    assert.equal((await state(pg)).game.revision,before,"choosing a tier sends nothing");
    await pg.click("#sheet-close");
    // A hidden tab stops the ambient stage.
    if(EXPECT_FX==="high"){
      await pg.evaluate(()=>{Object.defineProperty(document,"hidden",{value:true,configurable:true});document.dispatchEvent(new Event("visibilitychange"));});
      assert.equal(await pg.evaluate(()=>getComputedStyle(document.querySelector(".mstage-art .h1")).animationName),"none","a hidden tab has no ambient motion");
      await pg.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event("visibilitychange"));});
      assert.notEqual(await pg.evaluate(()=>getComputedStyle(document.querySelector(".mstage-art .h1")).animationName),"none");
    }
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
    // Ordinary trick play: the trick, the hand and whose turn it is are on one screen.
    if(i<2*s.game.seats.length){
      const seen=await oneViewport(player,"my turn");
      assert.match(await player.evaluate(()=>document.getElementById("status").textContent),/^Your turn/);
      assert.ok(await player.evaluate(()=>Boolean(document.getElementById("trick"))),"the trick is the centre of the board");
      assert.ok(seen.cards.length>0);
      // AVR-267: the crew strip and the trick, for the player and for someone waiting; and the
      // hand's card states, where a legal card never differs from another legal card.
      for(const p of [player,pages.find(x=>x!==player)]){await crewLegible(p,"trick play");await trickShows(p,"trick play");}
      if(s.game.turn!=="tonoja"){await legalCardsLookAlike(player,"my turn");pres.looks++;}
      await legalCardsLookAlike(pages.find(x=>x!==player),"not my turn");
    }
    await playCard(player,g.me.legal_cards[0]);await waitRevision(player,g.revision);
    if(i===1)await pages[0].screenshot({path:path.join(OUT,"trick-mid.png")});
    await holdCheck(player);
    if(i===0){
      const partial=(await state(player)).game;
      await player.reload({waitUntil:"networkidle2"});await player.waitForFunction(()=>ST?.game?.me&&!ST.game.away.length);
      assert.deepEqual((await state(player)).game.trick,partial.trick);
      assert.deepEqual((await state(player)).game.me.hand,partial.me.hand);
      // Reconnect mid-trick: the board is the static state, and the director showed none of the
      // events that were already in the view.
      await trickShows(player,"a partly played trick after a reload");await crewLegible(player,"after a reload");
      if(DIRECTOR){const d=await directed(player);assert.equal(d.settled[0],"first-view");assert.deepEqual(d.performed.filter(e=>e!=="reconnect"),[],"nothing stale is replayed after a reload");}
    }
    await pause(115); // Stay below the platform's per-socket action rate limit.
  }
  assert.ok((await state(pages[0])).game.result,"mission reaches a result");
  await settle();
  // Success or failure takes over the screen for everyone, at every phone size.
  for(const p of pages)await resultOwnsTheScreen(p,"the mission result");
  for(const size of PHONES){await pages[0].setViewport(size);await pause(60);await resultOwnsTheScreen(pages[0],"the mission result");}
  await pages[0].setViewport({width:390,height:844});
  await pages[0].screenshot({path:path.join(OUT,"result-phone.png")});
  {
    // AVR-267: the result explains a failure from the cause the server sends and nothing else.
    const pg=pages[1],text=()=>pg.evaluate(()=>document.getElementById("result").innerText);
    let real=await state(pg),g=real.game;
    if(g.result.status==="failed"){
      assert.ok(g.cause,"a failed attempt carries a cause");
      const shown=await text();
      assert.match(shown,/What failed: /);assert.match(shown,/Deciding play: /);assert.match(shown,/Fell on: /);
      if(g.cause.trigger_seat)assert.match(shown,new RegExp(`Deciding play: ${real.players.find(p=>p.pid===g.cause.trigger_seat)?.name||"Tonoja"}`));
      else assert.match(shown,/No single play decided it\./);
    }else assert.doesNotMatch(await text(),/Deciding play|What failed/,"a success has no cause and none is invented");
    // Reconnect on a result: the result owns the screen again, statically.
    await pg.reload({waitUntil:"networkidle2"});await pg.waitForFunction(()=>ST?.game?.result&&!ST.game.away.length);
    await resultOwnsTheScreen(pg,"the result after a reload");
    assert.equal(await running(pg,"cine"),0,"a result met on a reload is not replayed as a cinematic");
    if(DIRECTOR)assert.deepEqual((await directed(pg)).performed.filter(e=>e!=="reconnect"),[]);
    for(const p of pages)await p.waitForFunction(()=>!ST.game.away.length);
    await settle();real=await state(pg);g=real.game;      // the reload moved the revision on
    // The three shapes of a cause, drawn from this table's own state with only the result and
    // the cause changed (the page has one way to draw a result): the trigger is not the
    // affected seat; the trigger is the affected seat; nobody triggered it.
    const humans=g.seats.filter(x=>x!=="tonoja"),nameOf=x=>real.players.find(p=>p.pid===x).name,last=g.last_trick;
    const task=g.tasks[0]||null,card=last?last.plays.find(p=>p.seat===humans[0])?.card||last.plays[0].card:"blue:9";
    const base={kind:task?"task":"mission_objective",objective:task?task.id:"balance9",failure:"unreachable",state:"IMPOSSIBLE",trigger_controller:humans[0],trigger_card:card,
      action:{t:"play_card",seat:humans[0],controller:humans[0],card},cards:[card],trick:last?last.index:1,mission:{}};
    const draw=cause=>pg.evaluate((st,cause)=>render({...st,game:{...st.game,attempt:st.game.attempt+2000,result:{status:"failed",reason:"A crew objective failed."},cause}}),real,cause);
    await draw({...base,trigger_seat:humans[0],affected_seat:humans[1]});
    let shown=await text();
    assert.match(shown,new RegExp(`Deciding play: ${nameOf(humans[0])} · ${card.split(":")[1]} ${card.split(":")[0]} · trick ${base.trick}`),"who triggered it, with the card and the trick");
    assert.match(shown,new RegExp(`Fell on: ${nameOf(humans[1])}${task?"’s task":""}`),"who it fell on, when that is someone else");
    if(task)assert.ok(shown.includes(`What failed: ${task.text} What it needs can no longer happen.`),"what failed, and how");
    assert.match(shown,/Every play was legal\. This names the card that decided it, not a fault\./,"the attribution explains and does not blame");
    assert.doesNotMatch(shown,/blame|mistake|should have|assist/i);
    await resultOwnsTheScreen(pg,"a failure with its cause");
    for(const size of PHONES){await pg.setViewport(size);await pause(60);await resultOwnsTheScreen(pg,"a failure with its cause");}
    await pg.setViewport({width:390,height:844});await pg.screenshot({path:path.join(OUT,"result-cause.png")});
    await draw({...base,failure:"violated",state:"FAILED",trigger_seat:humans[0],affected_seat:humans[0]});
    assert.match(await text(),new RegExp(`Fell on: ${nameOf(humans[0])}’s own ${task?"task":"objective"}`),"the same seat as trigger and affected");
    await draw({...base,kind:"deadline",objective:null,failure:"deadline",state:"FAILED",trigger_seat:null,trigger_controller:null,trigger_card:null,affected_seat:null,action:null,cards:[]});
    shown=await text();
    assert.match(shown,/What failed: The mission clock/);assert.match(shown,/Deciding play: No single play decided it\./);assert.match(shown,/Fell on: The whole crew/);
    assert.doesNotMatch(shown,/not a fault/,"nobody is named, so nobody needs excusing");
    await pg.evaluate(st=>render(st),real);
    await resultOwnsTheScreen(pg,"the real result again");
  }
  // Looking at the table does not lose the result: it holds the dock until it is shown again.
  await touchTargets(pages[0],"the mission result");
  await modalHolds(pages[0],"result","the mission result");
  // "Look at the table" puts it away, and the way back is the dock itself: one wide button that
  // says what happened, with the focus already on it.
  await clickKey(pages[0],"review");await onScreen(pages[0],"show-result","the result put away");
  assert.equal(await focused(pages[0]),"show-result","focus moves to the way back");
  assert.match(await pages[0].evaluate(()=>document.getElementById("dock").innerText),/Mission (complete|failed) · show result/);
  assert.equal(await pages[0].evaluate(()=>document.querySelectorAll("#dock button").length),1,"the dock holds nothing else");
  assert.equal(await pages[0].evaluate(()=>document.getElementById("game").inert),false);
  await oneViewport(pages[0],"the table after the result");await touchTargets(pages[0],"the table after the result");
  // Another seat's decision brings the result back by itself, where the answers are.
  await clickKey(pages[0],"show-result");
  assert.equal(await pages[0].evaluate(()=>!document.getElementById("result").hidden&&document.getElementById("result").contains(document.activeElement)),true,"the result is back, with the focus in it");
  assert.deepEqual(errors,[]);
  // AVR-267: a mission can be lost by its first trick, and a trick that ends the mission is not
  // held. The hold must still be seen: the crew retries until a trick has been held and checked.
  for(let attempt=0;attempt<6&&!pres.hold;attempt++){
    if(!(await settle()).game.result)break;
    await crewDecision(pages[0],(await state(pages[0])).game.result.status==="success"?"next":"retry-new");
    for(let i=0;i<40;i++){
      const s=await settle();if(s.game.stage!=="allocation")break;
      if(s.game.proposal){for(const p of pages){const v=await state(p);if(v.game.proposal&&!v.game.proposal.votes.includes(v.you.pid)&&(!v.game.proposal.recipient||v.game.proposal.recipient===v.you.pid)){const rev=v.game.revision;await clickKey(p,"agree");await waitRevision(p,rev);}}continue;}
      let pg;for(const p of pages)if((await state(p)).you.pid===(s.game.controller||s.game.captain))pg=p;
      const own=(await state(pg)).game,mode=own.mission.allocation,rev=own.revision;
      if(["one","captain_one"].includes(mode))await clickKey(pg,"all-tasks");
      else if(mode==="volunteer")await clickKey(pg,"volunteer-yes");
      else if(mode==="free"){const t=own.tasks.find(t=>!t.owner);await clickKey(pg,"assign:"+t.id);}
      else{const t=own.tasks.find(t=>!t.owner&&t.eligible_owners.includes(own.selector));await clickKey(pg,t?"task:"+t.id:"pass-task");}
      await waitRevision(pg,rev);
    }
    for(const pg of pages){const s=await state(pg);for(const t of s.game.tasks){if(t.prediction_required&&!t.prediction_committed&&(t.owner===s.you.pid||(t.owner==="tonoja"&&s.game.captain===s.you.pid))){const rev=(await state(pg)).game.revision;await clickKey(pg,"lock:"+t.id);await waitRevision(pg,rev);}}}
    if((await settle()).game.result)continue;
    await crewDecision(pages[0],"begin");
    for(let i=0;i<70&&!pres.hold;i++){
      const s=await settle();if(s.game.result)break;
      const actor=s.game.turn==="tonoja"?s.game.captain:s.game.turn;
      let player;for(const p of pages)if((await state(p)).you.pid===actor)player=p;
      const g=(await state(player)).game;
      // The lowest card of the hand rather than the first: a different line of play each time.
      await playCard(player,g.me.legal_cards[attempt%2?g.me.legal_cards.length-1:0]);await waitRevision(player,g.revision);
      await holdCheck(player);await pause(115);
    }
  }
  assert.ok(pres.hold>0,"a resolving hold was seen and checked");
  // AVR-267: the presentation never sent a frame, at whatever tier this run asked for.
  for(const p of pages)await directorSentNothing(p,"at the end of the mission");
  assert.ok(pres.looks>0,"legal cards were compared with each other on a player's own turn");
  assert.ok(checked.early&&checked.turn,"unavailable controls were checked against the server");
  // Clockwise selection always reaches another seat's task and a seat that may not pass. An
  // off-suit card is checked whenever the deal offers one before the mission ends.
  if(["normal","skip_captain"].includes(opening.mission.allocation)&&opening.tasks.length)assert.ok(checked.take&&checked.pass,"task selection refusals were checked");
  await crewDecision(pages[0],"end");
  await pages[0].waitForFunction(()=>ST.phase==="game_end"||ST.phase==="lobby");
  finished=true;
  console.log(`PASS: live ${HUMANS}-player mission, one-viewport play on ${PHONES.length} phone sizes, result takeover, hostile request, masked frames and reload; refusals checked: ${Object.keys(checked).filter(k=>checked[k]).join(", ")}; `+
    `presentation ${EXPECT_FX||"off"}${process.env.EXPO_MOTION==="reduced"?" (reduced motion)":""}: five zones, crew strip, trick, card states, radio ${pres.radio?"transmitted":"unavailable"}${pres.marker?" with marker":""}, `+
    `${pres.hold} resolving hold(s) checked${pres.heldReload?", reconnect during a hold":""}, cause shown, director sent nothing`,OUT);
}finally{
  try{if(!finished)await endTable();}
  finally{await browser.close();}
}
