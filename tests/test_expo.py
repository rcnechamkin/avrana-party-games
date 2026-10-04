"""Deterministic domain, catalog, privacy, lifecycle and hostile-command checks."""
import json
import random
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from games.expo.content import BLOCKED, TASKS, catalog
from games.expo.engine import Engine, Invalid
from games.expo.game import ExpoSession
from games.expo.rules import DECK, assertions, legal_cards, winner
from games.expo.storage import SnapshotStore
from games.expo.tasks import evaluate


def command(e, actor, t, **kwargs):
    return {'t': t, 'attempt': e.s['attempt'], 'revision': e.s['revision'],
            'request': str(e.s['revision']) + '-' + actor, **kwargs}


def act(e, actor, t, now=100, **kwargs):
    e.apply(actor, command(e, actor, t, **kwargs), now)


def decide(e, actor, kind, **kwargs):
    act(e, actor, 'propose', proposal={'kind': kind, **kwargs})
    for q in e.s['humans']:
        if q != actor:
            act(e, q, 'confirm', yes=True)


def place(e):
    """After a test lays tasks out by hand: the same cards are no longer in the deck or used."""
    for pile in ('deck', 'used'):
        e.s[pile] = [k for k in e.s[pile] if k not in e.s['selected']]


def allocated(e):
    while e.s['pool']:
        seat = e.selector()
        k = next(k for k in e.s['pool'] if e.eligible(k, seat))
        act(e, e.controller(seat), 'choose_task', task=k)
    for k, q in list(e.s['assignments'].items()):
        if TASKS[k]['params'].get('predict'):
            act(e, e.controller(q), 'predict', task=k, count=0)
    return e


def playing(n=3, seed=4, mid=1):
    e = allocated(Engine([f'p{i}' for i in range(n)], random.Random(seed), mid))
    decide(e, e.s['humans'][0], 'begin')
    return e


@pytest.mark.parametrize('n,sizes,planned', [(2,[13,13],13),(3,[13,13,14],13),(4,[10]*4,10),(5,[8]*5,8)])
def test_deals_conserve_and_captain(n, sizes, planned):
    for seed in range(12):
        e = Engine([f'p{i}' for i in range(n)], random.Random(seed))
        assert sorted(map(len,e.s['hands'].values())) == sizes
        assert e.s['planned'] == planned
        assert 'submarine:4' in e.s['hands'][e.s['captain']]
        assert len(e.s['columns']) == (7 if n == 2 else 0)
        if n == 2:
            assert all(c['top'] and c['covered'] for c in e.s['columns'])
        e.check()
        assert e.snapshot() == Engine([f'p{i}' for i in range(n)], random.Random(seed)).snapshot()


def test_immutable_suit_rules_and_trumps():
    blue = [{'seat':'a','card':'blue:4'}]
    assert legal_cards(['blue:1','blue:9','submarine:4','yellow:9'], blue) == ['blue:1','blue:9']
    assert legal_cards(['yellow:1','submarine:2'], blue) == ['yellow:1','submarine:2']
    assert legal_cards(['submarine:1','yellow:9'], [{'seat':'a','card':'submarine:2'}]) == ['submarine:1']
    assert winner(blue+[{'seat':'b','card':'yellow:9'},{'seat':'c','card':'blue:5'}]) == 'c'
    assert winner(blue+[{'seat':'b','card':'submarine:2'},{'seat':'c','card':'submarine:1'}]) == 'b'


def test_winner_matches_independent_oracle():
    r = random.Random(11)
    for _ in range(3000):
        cs=r.sample(DECK, r.choice([3,4,5]))
        plays=[{'seat':str(i),'card':c} for i,c in enumerate(cs)]
        eligible=[i for i,c in enumerate(cs) if c.startswith('submarine:')]
        if not eligible: eligible=[i for i,c in enumerate(cs) if c.split(':')[0]==cs[0].split(':')[0]]
        expected=str(max(eligible,key=lambda i:int(cs[i].split(':')[1])))
        assert winner(plays)==expected


def test_rejected_actions_are_transactional_and_duplicates_idempotent():
    e = playing()
    before=e.snapshot()
    turn=e.s['turn']; wrong=next(p for p in e.s['humans'] if p!=turn)
    with pytest.raises(Invalid):act(e,wrong,'play_card',card=e.playable(wrong)[0])
    assert e.snapshot()==before
    c=e.playable(turn)[0];msg=command(e,turn,'play_card',card=c)
    assert e.apply(turn,msg,100)
    after=e.snapshot()
    assert not e.apply(turn,msg,100)
    assert e.snapshot()==after
    msg['card']='pink:9' if c!='pink:9' else 'pink:8'
    with pytest.raises(Invalid):e.apply(turn,msg,100)
    assert e.snapshot()==after


@pytest.mark.parametrize('payload', [None, [], 'play', {}, {'t':[]}, {'t':'complete_task'}, {'t':'set_captain'}, {'t':'play_card','card':[]}])
def test_hostile_payloads_do_not_mutate(payload):
    e=playing();before=e.snapshot()
    with pytest.raises(Invalid): e.apply('p0',payload,100)
    assert e.snapshot()==before


def test_follow_suit_rejection_and_current_trick_order():
    for seed in range(100):
        e=playing(seed=seed)
        q=e.s['turn'];c=e.playable(q)[0];act(e,q,'play_card',card=c)
        q=e.s['turn'];hand=e.playable(q)
        legal=legal_cards(hand,e.s['trick'])
        bad=next((c for c in hand if c not in legal),None)
        if bad:
            before=e.snapshot()
            with pytest.raises(Invalid,match='follow'):act(e,q,'play_card',card=bad)
            assert e.snapshot()==before
            act(e,q,'play_card',card=legal[0])
            assert [p['seat'] for p in e.s['trick']] == [e.s['leader'],q]
            return
    pytest.fail('fixture must contain a follow-suit violation')


def test_communication_conditions_resource_and_immutable_meaning():
    assert assertions(['blue:2','blue:5','blue:8','yellow:4','submarine:4'],'blue:5')==[]
    assert assertions(['yellow:4'],'yellow:4')==['only']  # a single card is "only" and nothing else (AVR-248)
    assert assertions(['blue:2','blue:8'],'blue:2')==['lowest'] and assertions(['blue:2','blue:8'],'blue:8')==['highest']
    assert assertions(['submarine:4'],'submarine:4')==[]
    e=playing();actor='p0'
    card,opts=next(iter(e.communication_options(actor).items()))
    act(e,actor,'communicate',card=card,assertion=opts[0])
    assert card in e.playable(actor)
    assert not e.communication_options(actor)
    before=e.snapshot()
    with pytest.raises(Invalid):act(e,actor,'communicate',card=card,assertion=opts[0])
    assert e.snapshot()==before
    e.s['hands'][actor].remove(card)
    e.s['hands'][actor].append(card)  # exposure is separate from ordering
    assert e.s['exposures'][0]['assertion']==opts[0]
    turn=e.s['turn'];act(e,turn,'play_card',card=e.playable(turn)[0])
    with pytest.raises(Invalid):act(e,'p1','communicate',card=e.playable('p1')[0],assertion='highest')


def test_currents_masks_assertion_and_shared_pool_is_atomic():
    e=playing();e.s['communication']='currents'
    c,opts=next(iter(e.communication_options('p0').items()))
    act(e,'p0','communicate',card=c,assertion=opts[0])
    assert 'assertion' not in e.view('p1')['exposures'][0]
    e=playing();e.s['communication']='rapture';e.s['shared']=2
    for _ in range(2):
        c,opts=next(iter(e.communication_options('p0').items()))
        act(e,'p0','communicate',card=c,assertion=opts[0])
    assert e.s['shared']==0 and len(e.s['exposures'])==2
    assert e.communication_options('p1')=={}


def test_difficulty_generation_and_no_pass_in_second_circuit():
    for n in (2,3,4,5):
        for mid in (1,2,5,7,9,18,24,28,31,33,50):
            if n==2 and 20<=mid<=27: continue
            e=Engine([f'p{i}' for i in range(n)],random.Random(mid),mid)
            assert sum(TASKS[k]['difficulty'][str(len(e.s['seats']))] for k in e.s['pool']) == e.s['mission']['target']
    e=Engine(['a','b','c'],random.Random(4))
    e.s['pool']=['green6','yellow1','red3','blue4'];e.s['selected']=list(e.s['pool']);e.s['initial_count']=4
    place(e)
    for _ in range(3):act(e,e.controller(e.selector()),'choose_task',task=e.s['pool'][0])
    before=e.snapshot()
    with pytest.raises(Invalid):act(e,e.controller(e.selector()),'pass_task')
    assert e.snapshot()==before


def test_pass_capacity_and_captain_comparison():
    e=Engine(['a','b','c'],random.Random(4))
    act(e,e.controller(e.selector()),'pass_task')
    act(e,e.controller(e.selector()),'pass_task')
    with pytest.raises(Invalid):act(e,e.controller(e.selector()),'pass_task')
    e=Engine(['a','b','c'],random.Random(4));e.s['pool']=['moreTricksThanCaptain'];e.s['selected']=list(e.s['pool'])
    place(e)
    with pytest.raises(Invalid):act(e,e.s['captain'],'choose_task',task='moreTricksThanCaptain')


def test_distress_sealed_exchange_and_persistence():
    e=allocated(Engine(['a','b','c'],random.Random(4)))
    original=deepcopy(e.s['hands'])
    decide(e,'a','distress',direction='left')
    choices={q:next(c for c in e.playable(q) if not c.startswith('submarine')) for q in e.s['humans']}
    captain=e.s['captain']
    act(e,'a','pass_card',card=choices['a'])
    assert e.s['hands']==original
    assert 'pass_choices' not in json.dumps(e.view('b'))
    for q in ['b','c']:act(e,q,'pass_card',card=choices[q])
    assert e.s['phase']=='before_trick' and e.s['captain']==captain
    for q,c in choices.items():
        target=e.s['seats'][(e.s['seats'].index(q)+1)%3]
        assert c in e.s['hands'][target] and c not in e.s['hands'][q]
    e._finish('failed','fixture');decide(e,'a','retry',keep=True)
    assert e.s['distress'] and e.s['attempts']==1


def test_prediction_zero_is_locked_and_secret_is_private():
    e=Engine(['a','b','c'],random.Random(4))
    k='exactlyXtrickSecret';q=e.s['captain']
    e.s.update(pool=[],selected=[k],assignments={k:q},progress={k:'pending'},phase='prediction')
    place(e)
    act(e,q,'predict',task=k,count=0)
    assert e.s['phase']=='assistance'
    other=next(p for p in e.s['humans'] if p!=q)
    assert e.view(q)['tasks'][0]['prediction']==0
    assert 'prediction' not in e.view(other)['tasks'][0]
    with pytest.raises(Invalid):act(e,q,'predict',task=k,count=1)


def test_privacy_differential_and_snapshot_json_replay():
    e=playing();before=e.view('p0');s=deepcopy(e.snapshot())
    e.s['hands']['p1'][0],e.s['hands']['p2'][0]=e.s['hands']['p2'][0],e.s['hands']['p1'][0]
    assert e.view('p0')==before
    e=Engine.restore(json.loads(json.dumps(s)))
    assert e.snapshot()==s
    assert e.view(None)['me'] is None
    assert 'hands' not in e.view(None) and 'history' not in e.view(None) and 'deck' not in e.view(None)
    a=Engine.restore(json.loads(json.dumps(s)));b=Engine.restore(json.loads(json.dumps(s)))
    q=a.s['turn'];c=a.playable(q)[0]
    act(a,q,'play_card',card=c);act(b,q,'play_card',card=c)
    assert a.snapshot()==b.snapshot()
    s['state']['hands']['p0'].pop()
    with pytest.raises(Invalid):Engine.restore(s)


def test_tonoja_control_visibility_and_delayed_reveal():
    e=playing(n=2);q='tonoja';e.s['leader']=e.s['turn']=q
    c=e.s['columns'][0]['top'];hidden=e.s['columns'][0]['covered'];cap=e.s['captain']
    with pytest.raises(Invalid):act(e,next(p for p in e.s['humans'] if p!=cap),'play_card',card=c)
    act(e,cap,'play_card',card=c)
    assert e.s['columns'][0]['top'] is None and e.s['columns'][0]['covered']==hidden
    assert hidden not in e.view(cap)['tonoja']
    for _ in range(2):
        q=e.s['turn'];act(e,e.controller(q),'play_card',card=legal_cards(e.playable(q),e.s['trick'])[0])
    assert e.s['columns'][0]['top']==hidden and e.s['columns'][0]['covered'] is None


@pytest.mark.parametrize('n', [2,3,4,5])
def test_full_seeded_games_only_use_legal_actions(n):
    for seed in range(15):
        e=playing(n,seed)
        for _ in range(70):
            if e.s['result']:break
            q=e.s['turn'];act(e,e.controller(q),'play_card',card=legal_cards(e.playable(q),e.s['trick'])[0])
            e.check()
        assert e.s['result']['status'] in ('success','failed')
        if not e.s['trick'] and e.s['history'] and not e.s['result']:
            assert e.s['turn']==e.s['history'][-1]['winner']


def test_modifiers_balance_first_winner_final_card_and_timer():
    e=playing(mid=8)
    e.s['history']=[{'index':1,'leader':'p0','winner':'p0','plays':[{'seat':'p0','card':'blue:9'},{'seat':'p1','card':'green:9'},{'seat':'p2','card':'pink:1'}]}]
    e._outcome();assert e.s['result']['status']=='failed'
    e=Engine(['p0','p1','p2'],random.Random(4),23);decide(e,'p0','begin')
    assert not e.communication_options('p0')
    e.s['history']=[{'index':1,'winner':'p0','plays':[]},{'index':2,'winner':'p1','plays':[]}]
    e._outcome();assert e.s['result']['status']=='failed'
    e=Engine(['p0','p1','p2'],random.Random(4),27);decide(e,'p0','begin')
    e.s['trick']=[{'seat':'p0','card':'yellow:5'}];e._outcome();assert e.s['result']['status']=='failed'
    e=playing();e.s['expiry']=101
    assert not e.observe_time(100.999)
    assert e.observe_time(101) and e.s['result']['status']=='failed'


def test_final_yellow5_cannot_succeed_as_surplus_card():
    e=Engine(['p0','p1','p2'],random.Random(4),27)
    e.s['history']=[{'index':i+1,'winner':'p0','plays':[{'seat':'p0','card':'blue:1'}]} for i in range(13)]
    e._outcome()
    assert e.s['result']['status']=='failed'


@pytest.mark.parametrize('crew,low,high',[(3,8,23),(4,12,28),(5,16,31)])
def test_sum_threshold_boundaries_and_submarine_exclusion(crew,low,high):
    from games.expo.rules import rank
    from itertools import combinations
    colors=[c for c in DECK if not c.startswith('submarine')]
    for key,threshold in [('sumBelow',low),('sumAbove',high)]:
        for delta,expected in [(0,'failed'),(-1 if key=='sumBelow' else 1,'satisfied')]:
            cs=next(cs for cs in combinations(colors,crew) if sum(rank(c) for c in cs)==threshold+delta)
            s=task_state(['a'],{1:list(cs)},planned=1);s['seats']=[chr(97+i) for i in range(crew)]
            assert evaluate(TASKS[key],'a',s)==expected
    s=task_state(['a'],{1:['submarine:1','blue:1','green:1']},planned=1)
    assert evaluate(TASKS['sumBelow'],'a',s)=='failed'
    assert evaluate(TASKS['onlyOddTrick'],'a',s)=='failed'


def test_skip_captain_and_terrain_draws_are_frozen_on_restore():
    e=Engine(['a','b','c','d'],random.Random(10),25)
    assert e.s['captain'] not in e.s['allocation_ring']
    for _ in range(3):
        seat=e.selector();assert seat!=e.s['captain']
        act(e,seat,'choose_task',task=next(k for k in e.s['pool'] if e.eligible(k,seat)))
    restored=Engine.restore(json.loads(json.dumps(e.snapshot())))
    assert restored.s['terrain']==e.s['terrain'] and restored.s['communication']==e.s['communication']


def test_explicit_feasibility_and_used_deck_replenishment():
    e=Engine(['a','b','c'],random.Random(4))
    repaired=e._repair_tasks(['firstTrick','firstTwoTrick'],e.s['mission'])
    assert repaired[0]=='firstTrick' and repaired[1]!='firstTwoTrick'
    assert TASKS[repaired[1]]['difficulty']['3']==1
    pool=['firstTrick','firstTwoTrick','blue4','yellow1']
    assert e._repair_tasks(pool,e.s['mission'])==pool
    e=playing();selected=list(e.s['selected']);e._finish('failed','fixture')
    assert all(k in e.s['used'] for k in selected)
    decide(e,'p0','retry',keep=True)
    assert all(k not in e.s['used'] for k in selected)
    # A too-small unused pool replenishes from used cards rather than hanging.
    e.s['deck']=['sumAbove'];e.s['used']=['green6','yellow1']
    assert e._generate({'target':1}) in [['green6'],['yellow1']]


def test_timed_start_barrier_and_volunteer_eligibility_failure():
    e=Engine(['a','b','c'],random.Random(4),16,timed=True)
    e.s['pool']=['blue4'];e.s['selected']=list(e.s['pool'])
    place(e)
    assert e.s['expiry'] is None
    act(e,e.selector(),'volunteer',yes=True)
    assert e.s['expiry'] is None
    decide(e,'a','begin')
    assert e.s['expiry']==250
    q=e.s['turn'];rev=e.s['revision']
    with pytest.raises(Invalid):act(e,q,'play_card',now=250,card=e.playable(q)[0])
    assert e.s['result']['status']=='failed' and e.s['revision']==rev+1
    e=Engine(['a','b','c'],random.Random(4),16)
    e.s['pool']=['moreTricksThanCaptain'];e.s['selected']=list(e.s['pool'])
    place(e)
    for _ in range(2):act(e,e.selector(),'volunteer',yes=False)
    assert e.selector()==e.s['captain']
    act(e,e.selector(),'volunteer',yes=True)
    assert e.s['result']['status']=='failed' and e.s['attempts']==1


def test_single_owner_delegation_free_allocation_and_volunteers():
    e=Engine(['a','b','c'],random.Random(9),10)
    cap=e.s['captain'];target=next(q for q in e.s['humans'] if q!=cap)
    # Select a non-comparison fixture so every task is eligible for the delegate.
    e.s['pool']=['blue4'];e.s['selected']=list(e.s['pool'])
    place(e)
    act(e,cap,'propose',proposal={'kind':'assign','owner':target,'task':'all'})
    act(e,target,'confirm',yes=True)  # only the recipient consents (AVR-251)
    assert e.s['before_first_only'] and set(e.s['assignments'].values())=={target}
    e=Engine(['a','b','c'],random.Random(9),17)
    while e.s['pool']:
        k=e.s['pool'][0];owner=next(q for q in e.s['humans'] if e.eligible(k,q))
        decide(e,'a','assign',owner=owner,task=k)
    assert e.s['phase'] in ('prediction','assistance')
    e=Engine(['a','b','c'],random.Random(9),16)
    e.s['pool']=['blue4'];e.s['selected']=list(e.s['pool'])
    place(e)
    for _ in range(2):act(e,e.controller(e.selector()),'volunteer',yes=False)
    with pytest.raises(Invalid):act(e,e.controller(e.selector()),'volunteer',yes=False)
    act(e,e.controller(e.selector()),'volunteer',yes=True)
    assert len(e.s['assignments'])==1 and e.s['communication']=='none'


def test_blocked_content_and_types():
    for mid in BLOCKED:
        with pytest.raises(ValueError):Engine(['a','b','c'],random.Random(1),mid)
    assert len(TASKS)==96 and sum(d['enabled'] for d in TASKS.values())==92
    assert sorted(k for k,d in TASKS.items() if not d['enabled'])==['4with8','6with6','moreRedThanGreen','moreYellowThanBlue']
    assert next(m for m in catalog(2) if m['id']==11)['enabled']  # one shared token for two (AVR-250)
    assert not next(m for m in catalog(2) if m['id']==16)['enabled']
    e=playing();msg=command(e,'p0','predict',task='exactlyXtrick',count=True)
    with pytest.raises(Invalid):e.apply('p0',msg,100)


def session(n=3, path=None):
    s=ExpoSession(random.Random(4),snapshot_path=path)
    tokens=[f'human-{i}' for i in range(n)]
    for t in tokens:s.join(t,t);s.set_ready(t,True)
    s.start(tokens[0]);s.tick(s.gen)
    return s,tokens


def test_session_reconnect_all_away_and_again_cannot_erase():
    s,tokens=session();snap=s.engine.snapshot()
    for t in tokens:s.leave(t)
    assert s.phase=='allocation' and s.engine.s['away']==s.engine.s['humans']
    assert s.engine.s['hands']==snap['state']['hands']
    assert s.to_lobby()==[]
    for t in tokens:s.join(t,t)
    assert s.engine.s['away']==[] and s.engine.s['hands']==snap['state']['hands']
    assert s.game_state(None)['me'] is None
    assert 'human-' not in json.dumps(s.game_state(None))


def test_atomic_store_session_restart_and_fail_closed(tmp_path):
    path=tmp_path/'crew.json';s,tokens=session(path=path)
    original=s.engine.snapshot()
    restored=ExpoSession(random.Random(99),snapshot_path=path)
    assert restored.engine.s['hands']==original['state']['hands']
    assert restored.participants==tokens and restored.engine.s['away']==restored.engine.s['humans']
    for t in tokens:restored.join(t,t)
    assert restored.engine.s['away']==[]
    path.write_text('{}')
    bad=ExpoSession(random.Random(99),snapshot_path=path)
    assert bad.recovery_error and bad.engine is None
    store=SnapshotStore(tmp_path/'atomic.json');store.write({'value':1});store.write({'value':2})
    assert store.read()=={'value':2}
    assert not list(tmp_path.glob('.crew-*'))


def task_state(wins, cards=None, planned=13):
    # Evaluator input is resolved public history; winner correctness is covered
    # separately by the exhaustive card-rule oracle above.
    cards=cards or {}
    hist=[{'index':i+1,'leader':q,'winner':q,'plays':[{'seat':'a','card':c} for c in cards.get(i+1,['blue:2','green:4','yellow:6'])]} for i,q in enumerate(wins)]
    return {'seats':['a','b','c'],'captain':'b','history':hist,'planned':planned,'trick':[]}


def test_storage_failure_rejects_action_without_losing_table(tmp_path,monkeypatch):
    s,tokens=session(path=tmp_path/'crew.json')
    before=s.engine.snapshot()
    seat=s.engine.selector();actor=s.engine.controller(seat)
    token=next(t for t in tokens if s.players[t].pid==actor)
    def broken(snapshot):raise OSError('disk unavailable')
    monkeypatch.setattr(s.store,'write',broken)
    effects=s.game_action(token,command(s.engine,actor,'choose_task',task=s.engine.s['pool'][0]))
    assert effects[0]['code']=='storage'
    assert s.engine.snapshot()==before
    # Presence never requires a disk write and cannot destroy the table.
    s.leave(token);s.join(token,token)
    assert not s.engine.s['away']


def test_five_human_table_accepts_public_watcher_without_seating():
    s,tokens=session(n=5)
    s.join('watcher','Observer')
    assert 'watcher' in s.players and 'watcher' not in s.participants
    assert s.game_state('watcher')['me'] is None
    assert len(s.engine.s['humans'])==5


def test_closed_snapshot_restores_shared_lobby_reset_and_rejects_corrupt_phase(tmp_path):
    path=tmp_path/'crew.json';s,tokens=session(path=path)
    decide(s.engine,s.engine.s['humans'][0],'end')
    s._save()
    restored=ExpoSession(random.Random(4),snapshot_path=path)
    assert restored.phase=='game_end' and restored.deadline is not None
    restored.tick(restored.gen)
    assert restored.phase=='lobby' and restored.engine is None and not path.exists()
    bad=s.engine.snapshot();bad['state']['phase']='forged-phase'
    with pytest.raises(Invalid):Engine.restore(bad)


@pytest.mark.parametrize('choice',[3,999,True,'1'])
def test_forged_next_mission_is_a_transactional_rejection(choice):
    e=playing();e._finish('success','fixture');before=e.snapshot()
    with pytest.raises(Invalid):act(e,'p0','propose',proposal={'kind':'next','mission':choice})
    assert e.snapshot()==before


def test_exact_atleast_exclusions_and_final_semantics():
    s=task_state(['a'],{1:['blue:9','green:9','yellow:1']})
    assert evaluate(TASKS['2x9'],'a',s)=='pending'
    assert evaluate(TASKS['2orMore7'],'a',task_state(['a'],{1:['blue:7','green:7','yellow:1']}))=='satisfied'
    s['history'].append({'index':2,'leader':'a','winner':'a','plays':[{'seat':'a','card':'pink:9'}]})
    assert evaluate(TASKS['2x9'],'a',s)=='failed'
    assert evaluate(TASKS['no9'],'a',s)=='failed'
    assert evaluate(TASKS['onlyFirstTrick'],'a',task_state(['a']))=='pending'
    assert evaluate(TASKS['onlyFirstTrick'],'a',task_state(['a','a']))=='failed'
    assert evaluate(TASKS['green2lastTrick'],'a',task_state(['a'],{1:['green:2']}))=='failed'


@pytest.mark.parametrize('key', [k for k,d in TASKS.items() if d['enabled']])
def test_every_enabled_task_has_deterministic_success_fixture(key):
    d=TASKS[key];p=d['params'];family=d['family'];wins=['b']*13;cards={};prediction=None
    def own(values):
        for i in range(0,len(values),3):
            index=i//3+1;wins[index-1]='a';cards[index]=values[i:i+3]
    if family=='capture':own(p['cards'])
    elif family=='capture_final':wins[-1]='a';cards[13]=[p['card']]
    elif family in ('count','forbidden'):
        if p.get('per_suit'):own(['pink:1','green:1'])
        elif family=='count':
            from games.expo.rules import matches
            cs=[c for c in DECK if matches(c,p['selector'])]
            selected=cs[:p['count']]
            if p.get('required'):selected=[p['required']]
            own(selected)
    elif family=='tricks':
        prediction=2 if p.get('predict') else None
        wins[:prediction if prediction is not None else p['count']]=['a']*(prediction if prediction is not None else p['count'])
    elif family in ('streak','exact_streak'):wins[:p['count']]=['a']*p['count']
    elif family=='never_streak':wins[::2]=['a']*len(wins[::2])
    elif family=='indices':
        for i in p.get('required',[]):wins[12 if i=='last' else i-1]='a'
    elif family=='compare':
        if p['op']=='gt':wins=['a']*7+['b']*3+['c']*3
        elif p['op']=='eq':wins=['a']*4+['b']*4+['c']*5
        else:wins=['a']+['b']*6+['c']*6
    elif family=='majority':wins[:7]=['a']*7
    elif family=='value':
        values={'lt':['blue:1','green:2','yellow:3'],'gt':['blue:9','green:9','pink:8'],'in':['blue:9','green:8','pink:5'],'all_lt':['blue:1','green:2','yellow:3'],'all_gt':['blue:6','green:7','yellow:8']}
        own(values[p['op']])
    elif family=='parity':own(['blue:1','green:3','yellow:5'] if p['parity'] else ['blue:2','green:4','yellow:6'])
    elif family=='win_with':
        from games.expo.rules import matches
        ins=p['instrument'];instrument=ins.get('card') or ins.get('suits',['blue'])[0]+':'+str(ins.get('ranks',[4])[0])
        # A target may name one card or a rank (5with7): take the first matching card that is not the instrument.
        target=[next(c for c in DECK if matches(c,p['target']) and c!=instrument)] if p.get('target') else []
        own([instrument]+target)
    elif family in ('equal','equal_trick'):own([p['suits'][0]+':1',p['suits'][1]+':2'])
    elif family=='each_color':own(['blue:1','green:1','pink:1','yellow:1'])
    elif family=='all_color':own([f'blue:{r}' for r in range(1,10)])
    elif family=='no_lead':pass
    else:pytest.fail('Uncovered task family '+family)
    s=task_state(wins,cards)
    assert evaluate(d,'a',s,prediction)=='satisfied',key
    # Terminal mismatch/violation fixture uses the same committed definition.
    bad=task_state(['b']*13)
    if family in ('forbidden','no_lead','never_streak') or (family=='tricks' and p.get('count')==0) or (family=='indices' and not p.get('required')):
        bad=task_state(['a']*13)
        if family=='forbidden':
            from games.expo.rules import matches
            bad['history'][0]['plays']=[{'seat':'a','card':next(c for c in DECK if matches(c,p['selector']))}]
        if family=='no_lead':bad['history'][0]['plays']=[{'seat':'a','card':p['suits'][0]+':1'}]
    if family=='compare' and p['op'] in ('lt','eq'):bad=task_state(['a']*13)
    assert evaluate(d,'a',bad,prediction)=='failed',key
