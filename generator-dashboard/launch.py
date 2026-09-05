"""Start the local dashboard and open it; keep this process alive to supervise it."""
import contextlib, fcntl, json, os, shutil, signal, socket, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:5173/'
os.chdir(ROOT)
(ROOT/'logs').mkdir(exist_ok=True)
lock=(ROOT/'logs/launcher.lock').open('w')
try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    webbrowser.open(URL)
    print('Blade Lab is already running.');sys.exit(0)

def node_binary():
    node=shutil.which('node')
    if node: return node
    choices=list((Path.home()/'.nvm/versions/node').glob('*/bin/node'))
    choices.sort(key=lambda p:tuple(int(n) for n in p.parent.parent.name.lstrip('v').split('.')),reverse=True)
    if choices:return str(choices[0])
    raise RuntimeError('Node.js was not found. Install Node.js 22 or newer.')

children=[];handles=[]
def cleanup(*_):
    for child in children:
        if child.poll() is None: child.terminate()
    for child in children:
        with contextlib.suppress(subprocess.TimeoutExpired):child.wait(timeout=5)
        if child.poll() is None: child.kill()
    for handle in handles:handle.close()
def interrupted(*_):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,interrupted)
try:
    if not (ROOT/'dist/server/index.js').exists():raise RuntimeError('The dashboard needs a build. See README.md.')
    for port in (5173,8766):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError(f'Port {port} is already in use. Close the previous dashboard first.')
    commands=[('reader',[str(ROOT/'.venv/bin/python'),str(ROOT/'server.py')]),('web',[node_binary(),str(ROOT/'node_modules/vinext/dist/cli.js'),'start','-H','127.0.0.1','-p','5173'])]
    for name,command in commands:
        handle=(ROOT/'logs'/f'{name}.log').open('a',buffering=1);handles.append(handle)
        children.append(subprocess.Popen(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT))
    for _ in range(120):
        if any(c.poll() is not None for c in children):raise RuntimeError('A service stopped. See the logs folder.')
        try:
            with urllib.request.urlopen(URL+'api/state',timeout=1) as response:
                json.load(response)
            break
        except Exception:time.sleep(.25)
    else:raise RuntimeError('The dashboard did not start. See the logs folder.')
    if '--no-open' not in sys.argv:webbrowser.open(URL)
    print(f'Blade Lab is running: {URL}\nKeep this window open. Press Control-C to stop.\nResults are saved in {ROOT / "data"}',flush=True)
    while all(c.poll() is None for c in children):time.sleep(1)
    raise RuntimeError('A dashboard service stopped. See the logs folder.')
except KeyboardInterrupt:print('\nStopping Blade Lab. Saved results will stay on this computer.')
except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)
finally:cleanup()
