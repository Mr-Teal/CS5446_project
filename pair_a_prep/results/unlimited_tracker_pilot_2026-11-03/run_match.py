"""Local fresh-process readiness probe; captures only private tracker inputs."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import asdict
import json,sys,threading,time
from pathlib import Path
from pair_c import run_evaluation as runner
from pair_c.tracking import RecordingTracker

class Memory(C.Structure):
 _fields_=[('cb',W.DWORD),('PageFaultCount',W.DWORD)]+[(n,C.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
k=C.WinDLL('kernel32');k.GetCurrentProcess.restype=C.c_void_p
ps=C.WinDLL('psapi');ps.GetProcessMemoryInfo.argtypes=[C.c_void_p,C.POINTER(Memory),W.DWORD]
def memory():
 m=Memory();m.cb=C.sizeof(m)
 if not ps.GetProcessMemoryInfo(k.GetCurrentProcess(),C.byref(m),m.cb):raise C.WinError()
 return dict(rss=m.WorkingSetSize,peak_rss=m.PeakWorkingSetSize,private_commit=m.PagefileUsage,peak_private_commit=m.PeakPagefileUsage)
stage=sys.argv[1];out=Path('pair_a_prep/local_runs/unlimited-20261103');stop=threading.Event();samples=[]
def monitor():
 while not stop.is_set():samples.append(dict(seconds=time.perf_counter()-began,**memory()));stop.wait(.1)
config=out/(stage+'.ini');game=0
stream=(out/(stage+'-private-stream.jsonl')).open('w',encoding='utf-8')
class Capture(RecordingTracker):
 def update(self,observation,own_move=None):
  global game
  if observation.ply==0 and self.player=='white':game+=1
  stream.write(json.dumps(dict(game=game,player=self.player,tracker_seed=17+game-1+(self.player=='black'),observation=asdict(observation),own_move=own_move))+'\n');stream.flush()
  return super().update(observation,own_move)
runner.RecordingTracker=Capture
began=time.perf_counter();thread=threading.Thread(target=monitor,daemon=True);thread.start()
try:summary=runner.run(runner.load_config(config),config)
finally:
 stop.set();thread.join();stream.close();samples.append(dict(seconds=time.perf_counter()-began,**memory()));(out/(stage+'-memory.json')).write_text(json.dumps(dict(scope='runner process only; excludes Stockfish children; sampled RSS plus OS peak',samples=samples,wall_seconds=time.perf_counter()-began),indent=2)+'\n')
print(json.dumps(summary),flush=True)
