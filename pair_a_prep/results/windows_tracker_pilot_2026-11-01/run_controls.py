from pathlib import Path
import configparser,json,subprocess,sys
root=Path.cwd(); out=root/'pair_a_prep/local_runs/windows-20261101'
out.mkdir(parents=True, exist_ok=True)
# Require the actual native library before running the comparison.
from pair_a_prep._belief_native import library
assert library() is not None
script='pair_a_prep/results/windows_tracker_pilot_2026-11-01/profile_update_windows_v1.py'
cases=[('native-short','native',250,5000,64,17),('native-medium','native',1000,5000,64,6),('native-relaxed','native',15000,15000,512,1),('python-control','python',None,5000,None,1)]
for name,backend,slice_ms,total_ms,memory,calls in cases:
 for trial in range(3 if backend=='native' else 1):
  dest=out/f'{name}-{trial}.json'
  if dest.exists(): raise FileExistsError(dest)
  cmd=[sys.executable,'-c',f"import runpy; runpy.run_path({script!r},run_name='__main__')",'--backend',backend,'--input','pair_a_prep/results/tracker_budget_profile_2026-10-31/private-stream.jsonl','--no-instrument','--output',str(dest),'--max-calls',str(calls)]
  if slice_ms is not None: cmd+=['--slice-ms',str(slice_ms),'--total-ms',str(total_ms),'--memory-mb',str(memory)]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
  print(name,trial,p.returncode,p.stdout.strip()[-600:],p.stderr.strip()[-300:],flush=True)
  if p.returncode: raise RuntimeError(name)
