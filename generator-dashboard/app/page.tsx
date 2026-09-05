'use client';
import { useEffect, useState } from 'react';
import Image from 'next/image';
import { Maximize, Minimize, RotateCcw, Activity, Play, Square, Trophy, Download, Timer, ArrowUpRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
import { Progress } from '@/components/ui/progress';
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from '@/components/ui/empty';

type Sample = { t: number; v: number };
type Run = { id: string; team: string; duration: number; started_at: number; elapsed: number; status: string; clipped: boolean; average: number|null; peak: number|null; samples?: Sample[]; sample_count: number };
type State = { connected: boolean; message: string; samples: Sample[]; now: number; active: Run|null; runs: Run[]; storage_error: string|null };
type Series = { name: string; color: string; samples: Sample[] };
const COLORS = ['#75eed0','#ffcc7d','#aab4ff','#fc91c8','#7dcaff','#d9e785'];
const fmt = (v: number|null|undefined) => v==null?'—':v.toFixed(2);
const initial: State = { connected: false, message: 'Connecting to generator…', samples: [], now: 0, active: null, runs: [], storage_error: null };
async function request<T=Run>(path:string, body?:unknown) {
  const response=await fetch(path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw new Error((data as {error?:string}).error||'The request could not be completed.');
  return data as T;
}
function Chart({series, duration, live=false, waiting=false}:{series:Series[];duration:number;live?:boolean;waiting?:boolean}) {
  const x=(t:number)=>66+t/duration*1080, y=(v:number)=>326-Math.min(1.2,Math.max(0,v))/1.2*288;
  return <div className="chart-wrap"><svg className="graph" viewBox="0 0 1200 390" aria-label={live?'Voltage over the last 60 seconds, from 0 to 1.2 volts':'Team voltage traces aligned at the start, from 0 to 1.2 volts'}>
    {[0,0.3,0.6,0.9,1.2].map(v=><g key={v}><line x1="66" x2="1146" y1={y(v)} y2={y(v)}/><text x="45" y={y(v)+6} textAnchor="end">{v.toFixed(1)} V</text></g>)}
    {[0,1,2,3,4].map(n=><g key={n}><line className="vertical" x1={x(n*duration/4)} x2={x(n*duration/4)} y1="38" y2="326"/><text x={x(n*duration/4)} y="365" textAnchor="middle">{live?(n===4?'Now':`${duration-n*duration/4}s ago`):`${n*duration/4}s`}</text></g>)}
    {series.flatMap((s,i)=>{
      const segments:Sample[][]=[];
      for(const p of s.samples){const last=segments.at(-1);if(!last||p.t-last[last.length-1].t>1)segments.push([p]);else last.push(p);}
      return segments.map((pts,j)=><polyline key={`${i}-${j}`} className="trace" style={{stroke:s.color}} points={pts.map(p=>`${x(p.t)},${y(p.v)}`).join(' ')}/>);
    })}
  </svg>{waiting&&<div className="chart-message">Waiting for the first reading…</div>}</div>;
}
export default function Home() {
  const [state,setState]=useState<State>(initial),[team,setTeam]=useState(''),[duration,setDuration]=useState('30');
  const [mode,setMode]=useState('live'),[selected,setSelected]=useState<Run[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[full,setFull]=useState(false);
  useEffect(()=>{
    const es=new EventSource('/api/events');
    es.onmessage=e=>{try{setState(JSON.parse(e.data));}catch{setError('The live feed could not be read.');}};
    es.onerror=()=>setState(s=>({...s,connected:false,message:'Reconnecting to the local reader…'}));
    const fullscreen=()=>setFull(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange',fullscreen);
    return ()=>{es.close();document.removeEventListener('fullscreenchange',fullscreen);};
  },[]);
  useEffect(()=>{
    type Tool={name:string;description:string;inputSchema:object;annotations:{readOnlyHint:boolean};execute:(input:unknown)=>Promise<unknown>};
    const context=(document as Document & {modelContext?:{registerTool:(tool:Tool,options:{signal:AbortSignal})=>unknown}}).modelContext;
    if(!context?.registerTool)return;
    const lifecycle=new AbortController();
    const tools:Tool[]=[
      {name:'read_generator_challenge',description:'Read live voltage, the active attempt, and saved team results.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true},execute:async()=>{const s=await request<State>('/api/state');return {connected:s.connected,voltage:s.samples.at(-1)?.v,active:s.active,runs:s.runs};}},
      {name:'start_generator_attempt',description:'Start and record a timed team attempt using the real connected generator.',inputSchema:{type:'object',properties:{team:{type:'string',minLength:1,maxLength:60},duration:{type:'integer',enum:[15,30,60]}},required:['team','duration'],additionalProperties:false},annotations:{readOnlyHint:false},execute:async(input)=>{const run=await request('/api/runs/start',input);setState(await request<State>('/api/state'));setMode('live');return run;}},
      {name:'stop_generator_attempt',description:'Stop the current attempt early and save its peak for ranking.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:false},execute:async()=>{const run=await request('/api/runs/stop',{});setState(await request<State>('/api/state'));return run;}},
    ];
    for(const tool of tools){try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{/* Optional browser capability. */}}
    return ()=>lifecycle.abort();
  },[]);
  async function act(path:string, body:unknown){setBusy(true);setError('');try{await request(path,body);setState(await request<State>('/api/state'));setMode('live');}catch(e){setError(e instanceof Error?e.message:'Could not complete the request.');}finally{setBusy(false);}}
  async function compare(run:Run,checked:boolean){setError('');if(!checked){setSelected(s=>s.filter(r=>r.id!==run.id));return;}if(selected.length>=6){setError('Compare up to six attempts at a time.');return;}try{const fullRun=await request(`/api/runs/${run.id}`);setSelected(s=>s.some(r=>r.id===run.id)?s:[...s,fullRun].slice(0,6));setMode('compare');}catch{setError('Could not load that saved trace.');}}
  const active=state.active,current=state.samples.at(-1)?.v;
  const liveSeries:Series[]=[{name:active?.team||'Live voltage',color:COLORS[0],samples:active?.samples||state.samples.map(p=>({...p,t:p.t-state.now+60})).filter(p=>p.t>=0)}];
  const sortedRuns=[...state.runs].sort((a,b)=>(b.peak??-1)-(a.peak??-1));
  const rankings=sortedRuns.filter(r=>(r.status==='complete'||r.status==='stopped')&&!r.clipped&&r.duration===Number(duration)&&r.peak!=null);
  const peakSamples=state.samples.filter(p=>p.t>=state.now-30);
  const peak=peakSamples.length?Math.max(...peakSamples.map(p=>p.v)):null;
  const best=rankings[0];
  return <main>
    <header><div className="brand"><Image className="league-logo" src="/build-league-logo.png" alt="Build League" width={2172} height={724} unoptimized/><div className="brand-project"><h1>Blade Lab</h1><p>Generator challenge · East Bay Makers Club</p></div></div><Button variant="outline" onClick={async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{setError('Use your browser’s full-screen option to expand the graph.');}}}>{full?<Minimize/>:<Maximize/>}{full?'Exit full screen':'Full screen'}</Button></header>
    <div className="status"><span className={state.connected?'dot live':'dot'}/>{state.message}<span className="status-note">DC voltage · ~5 updates / second</span></div>
    {(error||state.storage_error)&&<div className="error" role="alert">{error||state.storage_error}</div>}
    {state.connected&&current!==undefined&&current>=3.10&&<div className="error">Near the measuring limit. Readings may be clipped; keep the input at or below 3.3 V.</div>}
    <section className="dashboard"><div className="graph-panel"><Tabs value={mode} onValueChange={v=>setMode(String(v))}>
      <div className="panel-heading"><div><span className="eyebrow">{active?'ATTEMPT IN PROGRESS':'THE LIVE FEED'}</span><h2>{active?active.team:mode==='compare'?'Put your designs head to head.':'Give your blades a spin.'}</h2></div><TabsList><TabsTrigger value="live">Live</TabsTrigger><TabsTrigger value="compare">Compare{selected.length?` (${selected.length})`:''}</TabsTrigger></TabsList></div>
      <TabsContent value="live"><Chart series={liveSeries} duration={active?.duration||60} live={!active} waiting={!state.samples.length}/></TabsContent>
      <TabsContent value="compare">{selected.length?<><div className="trace-legend">{selected.map((r,i)=><span key={r.id}><i style={{background:COLORS[i]}}/>{r.team} · {new Date(r.started_at*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}</span>)}</div><Chart series={selected.map((r,i)=>({name:r.team,color:COLORS[i],samples:r.samples||[]}))} duration={Math.max(...selected.map(r=>r.duration))}/></>:<Empty className="compare-empty"><EmptyHeader><EmptyTitle>Which blades work best?</EmptyTitle><EmptyDescription>Select saved attempts below to compare their voltage curves.</EmptyDescription></EmptyHeader></Empty>}</TabsContent>
    </Tabs></div><aside className="readout"><span className="eyebrow">VOLTAGE RIGHT NOW</span><div className="voltage">{state.connected?fmt(current):'—'}<span>V</span></div><div className="readout-stat"><span>Peak · last 30 seconds</span><strong>{fmt(peak)} <small>V</small></strong>{active&&<p className="attempt-average">Attempt average <b>{fmt(active.average)} V</b></p>}</div><Button className="reset-live" variant="outline" disabled={busy||!!active} title={active?'Finish the current attempt before resetting':'Clear the live graph and 30-second peak; keep saved attempts'} onClick={()=>act('/api/reset',{})}><RotateCcw/>Reset graph &amp; peak</Button><div className="readout-bottom"><Activity size={20}/><p>More lift. More spin.<br/><strong>Watch the voltage climb.</strong></p></div></aside></section>
    <section className="attempt-panel">{active?<><div className="attempt-label"><span className="record-dot"/><div><h3>Recording {active.team}</h3><p>{active.sample_count} readings captured · stops automatically</p></div></div><div className="countdown"><strong>{Math.max(0,Math.ceil(active.duration-active.elapsed))}<span>s left</span></strong><Progress value={active.elapsed/active.duration*100} aria-label="Attempt progress"/></div><Button variant="outline" disabled={busy} onClick={()=>act('/api/runs/stop',{})}><Square/> Stop early</Button></>:<><div className="attempt-label"><span className="attempt-icon"><Timer size={22}/></span><div><h3>Ready for your team?</h3><p>Start the fan, then record your attempt.</p></div></div><form onSubmit={e=>{e.preventDefault();void act('/api/runs/start',{team,duration:Number(duration)});}}><label className="team-field" htmlFor="team-name">Team / blade design<Input id="team-name" placeholder="e.g. Turbo Turtles · 3 blades" value={team} onChange={e=>setTeam(e.target.value)} maxLength={60} required/></label><label className="duration-field" htmlFor="attempt-duration">Attempt length<Select value={duration} onValueChange={v=>setDuration(String(v))}><SelectTrigger id="attempt-duration" aria-label="Attempt length"><SelectValue/></SelectTrigger><SelectContent>{['15','30','60'].map(v=><SelectItem key={v} value={v}>{v} seconds</SelectItem>)}</SelectContent></Select></label><Button type="submit" disabled={!state.connected||!team.trim()||busy||!!state.storage_error}><Play/>Start attempt</Button></form></>}</section>
    <section className="results"><div className="results-heading"><div><span className="eyebrow">THE TEAM BENCH</span><h2>Every design has a story.</h2></div><span>{state.runs.length} saved {state.runs.length===1?'attempt':'attempts'}</span></div>
      {best&&<div className="best"><Trophy size={21}/><strong>{best.team}</strong><span>Best {duration}s peak</span><b>{fmt(best.peak)} V</b><ArrowUpRight size={19}/></div>}
      {state.runs.length?<Table><TableHeader><TableRow><TableHead>Compare</TableHead><TableHead>Team / blade design</TableHead><TableHead>Peak</TableHead><TableHead>Average</TableHead><TableHead>Time</TableHead><TableHead>Result</TableHead><TableHead><span className="sr-only">Download</span></TableHead></TableRow></TableHeader><TableBody>{sortedRuns.map(r=>{const rank=rankings.findIndex(a=>a.id===r.id);return <TableRow key={r.id}><TableCell><Checkbox aria-label={`Compare ${r.team}`} checked={selected.some(a=>a.id===r.id)} onCheckedChange={checked=>void compare(r,checked===true)}/></TableCell><TableCell><strong className="team-name">{r.team}</strong><span className="run-date">{new Date(r.started_at*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})} · {r.duration}s attempt</span></TableCell><TableCell className="numeric">{fmt(r.peak)} <small>V</small></TableCell><TableCell className="numeric">{fmt(r.average)} <small>V</small></TableCell><TableCell>{r.elapsed.toFixed(1)}s</TableCell><TableCell><span className={`badge ${rank===0?'winner':''}`}>{r.clipped?'Range limit':(r.status==='complete'||r.status==='stopped')?(rank>=0?`#${rank+1} · ${r.duration}s`:r.status==='stopped'?'Stopped early':'Complete'):r.status==='interrupted'?'Connection lost':'Stopped early'}</span></TableCell><TableCell><a className="download" href={`/api/runs/${r.id}/csv`} title={`Download ${r.team} readings as CSV`} aria-label={`Download ${r.team} readings as CSV`}><Download size={19}/><span>CSV</span></a></TableCell></TableRow>;})}</TableBody></Table>:<Empty className="results-empty"><EmptyHeader><EmptyTitle>The first spot is yours.</EmptyTitle><EmptyDescription>Record a team attempt to save its graph, average, and peak voltage here.</EmptyDescription></EmptyHeader></Empty>}
      <p className="scoring-note">Ranking uses peak voltage for {duration}-second attempts, including attempts stopped early. Only interrupted or range-limited attempts are unranked.</p>
    </section>
    <footer><span>Keep the fan position and electrical load the same for every team. This measures voltage, not power.</span><span>Saved on this computer · A2 → signal · GND → ground · max 3.3 V</span></footer>
  </main>;
}
