"""Loopback-only generator dashboard: live ESPHome feed and durable team trials."""
import asyncio, contextlib, csv, io, json, math, os, time, uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlparse
import yaml
from aiohttp import web
from aioesphomeapi import APIClient, SensorState

ROOT = Path(__file__).resolve().parent

class Reader:
    def __init__(self, data_dir=None, clock=time.monotonic):
        self.data_dir = Path(data_dir or ROOT/'data')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.samples = deque(maxlen=1500)
        self.connected = False
        self.last = None
        self.active = None
        self.runs = []
        self.storage_error = None
        self.revision = 0
        for file in self.data_dir.glob('run-*.json'):
            try: self.runs.append(json.loads(file.read_text()))
            except (ValueError, OSError): self.storage_error = 'A saved attempt could not be loaded.'
        self.runs.sort(key=lambda r:r['started_at'], reverse=True)
        pending = self.data_dir/'active.json'
        if pending.exists():
            try:
                run = json.loads(pending.read_text())
                run.update(status='interrupted', elapsed=run['samples'][-1]['t'] if run['samples'] else 0)
                self._save(run)
                self.runs.insert(0, run)
                pending.unlink()
            except (ValueError, OSError): self.storage_error = 'An interrupted attempt could not be recovered.'

    def healthy(self):
        return self.connected and self.last is not None and self.clock()-self.last < 2

    @staticmethod
    def stats(run):
        points = run['samples']
        if not points: return dict(average=None, peak=None)
        elapsed = max(run.get('elapsed',0), points[-1]['t'])
        area = sum((b['t']-a['t'])*(a['v']+b['v'])/2 for a,b in zip(points,points[1:]))
        area += max(0,elapsed-points[-1]['t'])*points[-1]['v']
        return dict(average=area/elapsed if elapsed>0 else points[0]['v'], peak=max(p['v'] for p in points))

    def public_run(self, run, full=False):
        result = {k:v for k,v in run.items() if k not in ('samples','start_mono','checkpoint')}
        result.update(self.stats(run))
        result['sample_count'] = len(run['samples'])
        if full: result['samples'] = run['samples']
        return result

    def _atomic(self, path, data):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, allow_nan=False))
        temporary.replace(path)

    def _save(self, run):
        self._atomic(self.data_dir/f"run-{run['id']}.json", self.public_run(run, full=True))

    def start(self, team, duration):
        if self.active: raise ValueError('An attempt is already running.')
        if not self.healthy() or not self.samples: raise ValueError('Wait for a fresh generator reading before starting an attempt.')
        if not isinstance(team,str) or not 1<=len(team.strip())<=60: raise ValueError('Enter a team name (1–60 characters).')
        if type(duration) is not int or duration not in (15,30,60): raise ValueError('Choose a 15, 30, or 60 second attempt.')
        if self.storage_error: raise ValueError('Saved results need attention. Check the local server log.')
        now=self.clock()
        run=dict(id=uuid.uuid4().hex,team=team.strip(),duration=duration,started_at=time.time(),start_mono=now,checkpoint=now,elapsed=0,status='recording',clipped=self.samples[-1]['v']>=3.10,samples=[dict(t=0,v=self.samples[-1]['v'])])
        self._atomic(self.data_dir/'active.json',self.public_run(run,full=True))
        self.active=run
        self.revision+=1
        return self.public_run(run)

    def finish(self, status='stopped'):
        if not self.active: raise ValueError('No attempt is running.')
        run=self.active
        run['elapsed']=min(run['duration'],max(0,self.clock()-run['start_mono']))
        run['status']=status
        self._save(run)
        self.runs.insert(0,self.public_run(run,full=True))
        self.active=None
        (self.data_dir/'active.json').unlink(missing_ok=True)
        self.revision+=1
        return self.public_run(run)

    def ingest(self, voltage):
        if not math.isfinite(voltage): return
        now=self.clock()
        # A new packet must not conceal a gap in a recorded attempt.
        if self.active and self.last is not None and now-self.last>=2:
            self.finish('interrupted')
        self.connected=True;self.last=now
        self.samples.append(dict(t=time.time(),v=voltage))
        if self.active:
            run=self.active
            elapsed=max(0,now-run['start_mono'])
            if elapsed<=run['duration']:
                run['samples'].append(dict(t=elapsed,v=voltage))
                run['elapsed']=elapsed
                run['clipped'] |= voltage>=3.10
            if now-run['checkpoint']>=1:
                self._atomic(self.data_dir/'active.json',self.public_run(run,full=True));run['checkpoint']=now

    def tick(self):
        if not self.active: return
        self.active['elapsed']=min(self.active['duration'],self.clock()-self.active['start_mono'])
        if not self.healthy(): self.finish('interrupted')
        elif self.active['elapsed']>=self.active['duration']: self.finish('complete')

    def reset_live(self):
        if self.active: raise ValueError('Finish the current attempt before resetting the graph.')
        self.samples.clear()
        self.revision += 1
        return self.snapshot()

    def snapshot(self):
        healthy=self.healthy()
        now=time.time()
        return dict(connected=healthy,message='Generator connected' if healthy else 'Waiting for generator · reconnecting automatically',samples=[p for p in self.samples if p['t']>=now-60],now=now,active=self.public_run(self.active,full=True) if self.active else None,runs=[self.public_run(r) for r in self.runs],revision=self.revision,storage_error=self.storage_error)

    async def connect(self):
        secret_path=Path(os.environ.get('ESPHOME_SECRETS',str(ROOT/'esphome/secrets.yaml')))
        key=yaml.safe_load(secret_path.read_text())['api_encryption_key']
        while True:
            client=APIClient(os.environ.get('GENERATOR_HOST','voltage-reader.local'),6053,None,noise_psk=key)
            lost=asyncio.Event()
            async def disconnected(expected):
                self.connected=False;lost.set()
            try:
                await client.connect(on_stop=disconnected,login=True)
                entities,_=await client.list_entities_services()
                target=next(e.key for e in entities if e.object_id=='input_voltage')
                def receive(state):
                    if isinstance(state,SensorState) and state.key==target:
                        try: self.ingest(state.state)
                        except OSError:
                            self.storage_error='Could not save an attempt. Check available disk space.'
                            print(self.storage_error,flush=True)
                client.subscribe_states(receive)
                while not lost.is_set():
                    try: await asyncio.wait_for(lost.wait(),timeout=3)
                    except asyncio.TimeoutError:
                        if self.last is not None and not self.healthy(): break
            except asyncio.CancelledError: raise
            except Exception as exc: print('Reader reconnecting:',type(exc).__name__,flush=True)
            finally:
                self.connected=False
                with contextlib.suppress(Exception): await client.disconnect()
            await asyncio.sleep(2)

    async def monitor(self):
        while True:
            try: self.tick()
            except OSError:
                self.storage_error='Could not save an attempt. Check available disk space.'
                print(self.storage_error,flush=True)
            await asyncio.sleep(.1)

@web.middleware
async def local_only(request, handler):
    if request.host.split(':')[0] not in ('127.0.0.1','localhost'):
        raise web.HTTPForbidden(text='Local access only')
    if request.method=='POST':
        origin=request.headers.get('Origin')
        if origin and urlparse(origin).netloc not in ('127.0.0.1:5173','localhost:5173','127.0.0.1:8766'):
            raise web.HTTPForbidden(text='Local access only')
        if request.content_type!='application/json': raise web.HTTPUnsupportedMediaType()
    try: return await handler(request)
    except ValueError as exc: return web.json_response({'error':str(exc)},status=400)
    except OSError: return web.json_response({'error':'Could not save the attempt. Check available disk space.'},status=500)

async def state(request): return web.json_response(request.app['reader'].snapshot())
async def events(request):
    response=web.StreamResponse(headers={'Content-Type':'text/event-stream','Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    await response.prepare(request)
    try:
        while True:
            await response.write(('data: '+json.dumps(request.app['reader'].snapshot(),allow_nan=False)+'\n\n').encode())
            await asyncio.sleep(.2)
    except (ConnectionError,asyncio.CancelledError): pass
    return response
async def start(request):
    data=await request.json()
    if not isinstance(data,dict): raise ValueError('Expected team and duration.')
    return web.json_response(request.app['reader'].start(data.get('team'),data.get('duration')))
async def reset(request): return web.json_response(request.app['reader'].reset_live())
async def stop(request): return web.json_response(request.app['reader'].finish())
async def run_detail(request):
    reader=request.app['reader']
    run=next((r for r in reader.runs if r['id']==request.match_info['id']),None)
    if run is None: raise web.HTTPNotFound()
    return web.json_response(reader.public_run(run,full=True))
async def export(request):
    run=next((r for r in request.app['reader'].runs if r['id']==request.match_info['id']),None)
    if run is None: raise web.HTTPNotFound()
    out=io.StringIO();writer=csv.writer(out);writer.writerow(['elapsed_seconds','voltage_volts'])
    writer.writerows((f"{p['t']:.3f}",f"{p['v']:.5f}") for p in run['samples'])
    return web.Response(text=out.getvalue(),content_type='text/csv',headers={'Content-Disposition':f'attachment; filename="generator-{run["id"][:8]}.csv"'})
async def lifecycle(app):
    reader=app['reader'];tasks=[asyncio.create_task(reader.connect()),asyncio.create_task(reader.monitor())]
    yield
    if reader.active:
        with contextlib.suppress(OSError): reader.finish('interrupted')
    for task in tasks: task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError): await task

def create_app(reader=None, connect=True):
    app=web.Application(middlewares=[local_only],client_max_size=8192)
    app['reader']=reader or Reader()
    app.add_routes([web.get('/api/state',state),web.get('/api/events',events),web.post('/api/reset',reset),web.post('/api/runs/start',start),web.post('/api/runs/stop',stop),web.get('/api/runs/{id}/csv',export),web.get('/api/runs/{id}',run_detail)])
    if connect: app.cleanup_ctx.append(lifecycle)
    return app
if __name__=='__main__': web.run_app(create_app(),host='127.0.0.1',port=8766,print=lambda s:print(s,flush=True))
