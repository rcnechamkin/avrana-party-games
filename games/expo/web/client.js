"use strict";
const $ = id => document.getElementById(id);
let ST = null, pending = false;
const symbols = {blue:"○",green:"△",pink:"□",yellow:"×",submarine:"◆"};
if (!Hub.identity.name) Hub.identity.name = "PLAYER";
$("name").value = Hub.identity.name;
Hub.buildAvatarGrid($("avatars"), Hub.identity.avatar, avatar => {
  Hub.identity.avatar = avatar;
  conn.send({t:"profile",avatar});
});
const conn = Hub.connect("/games/expo/ws", {
  onWelcome: () => {},
  onState: render,
  onFx: fx => {
    if (fx.kind === "invalid") { pending = false; Hub.toast(fx.msg, "err"); }
    if (fx.kind === "toast") Hub.toast(fx.msg);
  },
});
Hub.wirePfpButton($("photo"), () => conn);
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, action, key, disabled=false, reason="") {
  const b = el("button", text, "btn"); b.type="button"; b.disabled=disabled;
  b.dataset.key=key; b.title=reason; b.onclick=action; return b;
}
function send(t, payload={}) {
  if (!ST?.game || pending) return;
  pending = true;
  conn.send({t,...payload,attempt:ST.game.attempt,revision:ST.game.revision,request:crypto.randomUUID()});
}
function propose(kind, payload={}) { send("propose", {proposal:{kind,...payload}}); }
function name(seat) {
  if (seat === "tonoja") return "Tonoja";
  return ST.players.find(p => p.pid === seat)?.name || seat || "Unassigned";
}
function cardNode(card, action, enabled=false, reason="") {
  const [s,r] = card.split(":");
  const n = el(action ? "button" : "div", undefined, "card " + s);
  n.append(el("span",r,"rank"),el("span",symbols[s],"symbol"),el("span",s,"suit"));
  n.setAttribute("aria-label", `${s} ${r}`); n.dataset.key = "card:" + card;
  if (action) { n.type="button"; n.disabled=!enabled; n.title=reason; n.onclick=action; }
  return n;
}
$("name").onchange = () => {
  Hub.identity.name = $("name").value;
  conn.send({t:"profile",name:Hub.identity.name});
};
$("ready").onclick = () => conn.send({t:"ready",ready:!ST?.you?.ready});
$("start").onclick = () => conn.send({t:"start"});
$("mission").onchange = () => conn.send({t:"settings",patch:{mission:Number($("mission").value)}});
$("timed").onchange = () => conn.send({t:"settings",patch:{timed:$("timed").checked}});
$("tonoja-position").onchange = () => conn.send({t:"settings",patch:{tonoja_position:Number($("tonoja-position").value)}});
$("end").onclick = () => propose("end");
$("help-toggle").onclick = () => { $("help").hidden = !$("help").hidden; $("help-toggle").setAttribute("aria-expanded", String(!$("help").hidden)); };
function choices(select, entries, value) {
  select.replaceChildren();
  for (const entry of entries) {
    const o=el("option",entry.text); o.value=entry.value; o.disabled=Boolean(entry.disabled); select.append(o);
  }
  if (value !== undefined) select.value=String(value);
}
function ownerSelect(key, seats) {
  const select=el("select");select.dataset.key=key;select.setAttribute("aria-label","Task owner");
  choices(select,seats.map(s=>({value:s,text:name(s)}))); return select;
}
function render(st) {
  const focusKey=document.activeElement?.dataset?.key;
  const values=new Map([...document.querySelectorAll("[data-key]")].filter(n=>["INPUT","SELECT"].includes(n.tagName)).map(n=>[n.dataset.key,n.value]));
  ST=st;pending=false;
  const lobby=["lobby","countdown"].includes(st.phase);
  $("lobby").hidden=!lobby; $("game").hidden=lobby;
  $("countdown-overlay").hidden=st.phase!=="countdown";
  if (lobby) {
    const ready=st.players.filter(p=>p.ready&&p.connected).length;
    $("status").textContent=st.recovery_error || `${ready} crew members ready · ${st.players.length} at the table`;
    choices($("mission"), (st.missions||[]).map(m=>({value:m.id,text:`${m.id>32?"Deep dive":"Mission"} ${m.id}${m.enabled?"":" · unavailable"}`,disabled:!m.enabled})),st.settings.mission);
    $("timed").checked=st.settings.timed;$("tonoja-position").value=String(st.settings.tonoja_position);
    $("roster").replaceChildren();
    for (const p of st.players) {
      const row=el("div",undefined,"person");const avatar=el("span",p.avatar,"avatar");
      Hub.fillAvatar(avatar,p);row.append(avatar,el("strong",p.name,"name"),el("span",p.ready?"Ready":"Not ready","muted"));$("roster").append(row);
    }
    $("ready").textContent=st.you?.ready?"Ready ✓ · unready":"Ready up";
    $("start").disabled=!st.you?.ready||ready<2||st.phase==="countdown"||Boolean(st.recovery_error);
    $("lobby-reason").textContent=ready<2?"Ready at least two players to begin. With two, Tonoja joins your crew.":"Crew order follows joining order, clockwise.";
    return;
  }
  const g=st.game;if(!g)return;
  const spectator=!g.me;
  const acting=g.turn==="tonoja"?`${name(g.captain)} controls Tonoja`:name(g.turn);
  let status=g.stage==="allocation"?`${name(g.selector)} selects a task`:g.stage==="prediction"?"Commit the required trick predictions":g.stage==="assistance"?"Tasks assigned · agree to begin or use distress":g.stage==="passing"?"Choose a color card to pass · choices stay sealed":g.stage==="mission_result"?g.result.reason:`${acting} to play`;
  if(g.away.length)status=`Waiting for ${g.away.map(name).join(", ")} to reconnect. Your table is preserved.`;
  if(spectator)status="Watching · "+status;
  $("status").textContent=status;
  $("depth").textContent=`EXPEDITION ${g.mission.id} · ATTEMPT ${g.attempts||1}`;
  $("mission-title").textContent=`Mission ${g.mission.id}`;
  const objectives={balance9:"Never capture two more 9s than another crew member.",balance1:"Never capture two more color 1s than another crew member.",first_winner:"The first trick winner must always have strictly more tricks than everyone else. Sonar opens before trick 2.",final_yellow5:"Play yellow 5 as the final card in the final trick."};
  $("objective").textContent=objectives[g.mission.objective] || "Complete every assigned task together. Keep your hand secret.";
  $("challenge").textContent=g.mission.fixed?"4 fixed tasks":`Difficulty ${g.mission.target}`;
  $("trick-count").textContent=`Trick ${g.trick_number} / ${g.planned_tricks}`;
  $("seats").replaceChildren();
  for (const seat of g.seats) {
    const row=el("div",undefined,"seat"+(seat===g.turn?" active":""));
    row.append(el("strong",name(seat)+(seat===g.captain?" · Captain":"")),el("span",`${g.hand_counts[seat]} cards · ${g.trick_counts[seat]} tricks`,"muted"));$("seats").append(row);
  }
  $("trick").replaceChildren();
  if(!g.trick.length)$("trick").append(el("div","Awaiting the opening card", "muted"));
  for(const p of g.trick){const n=el("div",undefined,"played");n.append(cardNode(p.card),el("span",name(p.seat)));$("trick").append(n);}
  $("exposures").replaceChildren();
  for(const e of g.exposures)$("exposures").append(el("div",`${name(e.seat)} · ${e.card.replace(":"," ")} · ${e.assertion||"sonar meaning hidden"}`,"exposure"));
  $("last").hidden=!g.last_trick;$("last-content").replaceChildren();
  if(g.last_trick){$("last-content").append(el("p",`${name(g.last_trick.winner)} won trick ${g.last_trick.index}.`));const row=el("div",undefined,"last-cards");for(const p of g.last_trick.plays)row.append(cardNode(p.card));$("last-content").append(row);}
  $("tasks").replaceChildren();
  for(const task of g.tasks){
    const n=el("article",undefined,"task "+task.status),meta=el("div",undefined,"meta");
    meta.append(el("span",`${name(task.owner)} · ${task.difficulty} difficulty`),el("span",task.status==="satisfied"?"✓ Complete":task.status==="failed"?"× Failed":task.status));n.append(meta,el("div",task.text));
    if(task.prediction_committed)n.append(el("div",`Prediction: ${task.prediction??"sealed"}`,"muted"));
    if(g.stage==="allocation"&&!task.owner&&!spectator&&!g.proposal&&!g.away.length){
      if(["normal","skip_captain"].includes(g.mission.allocation))n.append(button("Take this task",()=>send("choose_task",{task:task.id}),"task:"+task.id,g.controller!==g.me.seat||!task.eligible_owners.includes(g.selector),"Another crew member must select this task."));
      else if(g.mission.allocation==="free"){
        const sel=ownerSelect("owner:"+task.id,task.eligible_owners);
        n.append(sel,button("Propose owner",()=>propose("assign",{task:task.id,owner:sel.value}),"assign:"+task.id));
      }
    }
    if(g.stage==="prediction"&&task.prediction_required&&!task.prediction_committed&&g.me&&(task.owner===g.me.seat||(task.owner==="tonoja"&&g.captain===g.me.seat))){
      const form=el("div",undefined,"prediction"),input=el("input");input.type="number";input.min="0";input.max=String(g.planned_tricks);input.step="1";input.value="0";input.dataset.key="predict:"+task.id;input.setAttribute("aria-label","Predicted tricks");
      form.append(input,button("Lock prediction",()=>send("predict",{task:task.id,count:Number(input.value)}),"lock:"+task.id));n.append(form);
    }
    $("tasks").append(n);
  }
  if(!g.tasks.length)$("tasks").append(el("p","This mission uses the shared objective instead of task cards.","muted"));
  const actions=$("phase-actions");actions.replaceChildren();
  if(!spectator&&!g.proposal&&!g.away.length){
    if(g.stage==="allocation"){
      if(["normal","skip_captain"].includes(g.mission.allocation)&&g.controller===g.me.seat)actions.append(button("Pass selection",()=>send("pass_task"),"pass-task",!g.me.may_pass_task,"The remaining tasks must be assigned this round."));
      if(["one","captain_one"].includes(g.mission.allocation)){
        const owner=ownerSelect("all-owner",g.seats);actions.append(owner,button("Offer all tasks",()=>propose("assign",{owner:owner.value,task:"all"}),"all-tasks",g.mission.allocation==="captain_one"&&g.me.seat!==g.captain));
      }
      if(g.mission.allocation==="volunteer"&&g.controller===g.me.seat)actions.append(button("Yes · take the tasks",()=>send("volunteer",{yes:true}),"volunteer-yes"),button("No",()=>send("volunteer",{yes:false}),"volunteer-no",!g.me.may_decline_volunteer,"The remaining crew must take the tasks."));
    }
    if(g.stage==="assistance"){
      actions.append(button("Begin without passing",()=>propose("begin"),"begin"));
      if(g.seats.every(s=>s!=="tonoja"))actions.append(button("Distress · pass left",()=>propose("distress",{direction:"left"}),"distress-left"),button("Distress · pass right",()=>propose("distress",{direction:"right"}),"distress-right"));
    }
  }
  $("decision").hidden=!g.proposal;$("decision").replaceChildren();
  if(g.proposal){const p=g.proposal.payload;const descriptions={begin:"Begin the mission without passing cards?",distress:`Activate distress and pass one color card ${p.direction}? This adds one recorded attempt to the mission.`,assign:p.task==="all"?`Give all tasks to ${name(p.owner)}?`:`Give this task to ${name(p.owner)}?`,retry:p.keep?"Retry with the same tasks?":"Retry with fresh tasks?",next:`Begin mission ${p.mission}?`,end:"End this table?"};$("decision").append(el("h2","Crew decision"),el("p",descriptions[p.kind]),el("p",`${g.proposal.votes.length} / ${g.seats.filter(s=>s!=="tonoja").length} confirmed`,"muted"));if(g.me&&!g.proposal.votes.includes(g.me.seat)&&!g.away.length)$("decision").append(button("Agree",()=>send("confirm",{yes:true}),"agree"),button("Decline",()=>send("confirm",{yes:false}),"decline"));}
  $("hand-panel").hidden=spectator;$("hand").replaceChildren();$("tonoja").replaceChildren();
  if(g.me){
    $("hand-reason").textContent=g.stage==="passing"?g.me.pass_locked?"Your pass is sealed":"Choose one color card":g.me.play_reason||"Follow the opening suit when possible";
    for(const c of g.me.hand){const passing=g.stage==="passing";const enabled=!g.away.length&&!g.proposal&&(passing?(!g.me.pass_locked&&!c.startsWith("submarine")):g.turn===g.me.seat&&g.me.legal_cards.includes(c));$("hand").append(cardNode(c,()=>send(passing?"pass_card":"play_card",{card:c}),enabled,passing?"Submarines cannot be passed":g.me.play_reason||"You must follow the opening suit."));}
  }
  $("tonoja-panel").hidden=!g.tonoja.length;
  for(const c of g.tonoja.filter(Boolean))$("tonoja").append(cardNode(c,()=>send("play_card",{card:c}),Boolean(g.me&&g.turn==="tonoja"&&g.captain===g.me.seat&&g.me.legal_cards.includes(c)&&!g.proposal),g.me?.play_reason||"Only the captain plays for Tonoja."));
  renderSonar(g,values);
  $("result").hidden=!g.result;$("result").replaceChildren();
  if(g.result){$("result").append(el("div",g.result.status==="success"?"MISSION COMPLETE":"MISSION ENDED","eyebrow"),el("h2",g.result.status==="success"?"Together, you did it.":"Dive again."),el("p",g.result.reason));const controls=el("div",undefined,"actions");if(g.me&&!g.proposal&&!g.away.length){if(g.result.status==="failed")controls.append(button("Retry · same tasks",()=>propose("retry",{keep:true}),"retry-same"),button("Retry · new tasks",()=>propose("retry",{keep:false}),"retry-new"));if(g.result.status==="success"){const next=ownerSelect("next-mission",[]);choices(next,(st.missions||[]).filter(m=>m.enabled).map(m=>({value:m.id,text:`Mission ${m.id}`})),(st.missions||[]).find(m=>m.enabled&&m.id>g.mission.id)?.id||g.mission.id);controls.append(next,button("Next expedition",()=>propose("next",{mission:Number(next.value)}),"next"));if(window.Brag)controls.append(Brag.button(()=>({title:"EXPO",icon:"🌊",winner:{name:"The crew",avatar:"🌊"},headline:`Mission ${g.mission.id} completed together`,beaten:[]})));}}$("result").append(controls);}
  $("end").disabled=spectator||Boolean(g.proposal)||g.away.length>0;
  for(const n of document.querySelectorAll("[data-key]")){if(!n.dataset.key.startsWith("sonar-")&&values.has(n.dataset.key)&&["INPUT","SELECT"].includes(n.tagName))n.value=values.get(n.dataset.key);if(n.dataset.key===focusKey&&!n.disabled)n.focus({preventScroll:true});}
  updateTimer();
}
function renderSonar(g,values){
  const area=$("sonar");area.replaceChildren();if(!g.me)return;
  const opts=g.me.communication_options, keys=Object.keys(opts);
  area.append(el("h3",`Sonar · ${g.communication}${g.shared_sonar!==null?` · ${g.shared_sonar} tokens left`:g.sonar_spent.includes(g.me.seat)?" · spent":""}`));
  if(!keys.length||g.proposal){area.append(el("p","Sonar is available only before a trick, after task allocation, with an unused token and an eligible color card.","muted"));return;}
  const row=el("div",undefined,"sonar-controls"),cards=el("select"),assertion=el("select");cards.dataset.key="sonar-card";assertion.dataset.key="sonar-meaning";cards.setAttribute("aria-label","Card to communicate");assertion.setAttribute("aria-label","Communication meaning");choices(cards,keys.map(c=>({value:c,text:c.replace(":"," ")})),keys.includes(values.get("sonar-card"))?values.get("sonar-card"):keys[0]);const update=()=>choices(assertion,opts[cards.value].map(a=>({value:a,text:a})));cards.onchange=update;update();if(opts[cards.value].includes(values.get("sonar-meaning")))assertion.value=values.get("sonar-meaning");row.append(cards,assertion,button("Communicate",()=>send("communicate",{card:cards.value,assertion:assertion.value}),"communicate"));area.append(row);if(g.communication==="currents")area.append(el("p","Your card is revealed, but the token’s meaning stays hidden.","muted"));
}
function updateTimer(){const expiry=ST?.game?.expiry;$("timer").hidden=!expiry;if(expiry){const remaining=Math.max(0,Math.ceil(expiry-conn.now()/1000));$("timer").textContent=`${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,"0")}`;}}
setInterval(()=>{updateTimer();if(ST?.phase==="countdown")$("cd").textContent=String(Math.max(1,Math.ceil((ST.deadline-conn.now())/1000)));},250);
