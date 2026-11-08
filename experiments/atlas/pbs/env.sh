#!/bin/bash
# Pair A experiment environment on NUS HPC Atlas.
#
# The login nodes carry CentOS 7's Python 3.6.8, which the repo does not support
# (pyproject requires >=3.9) and whose pip cannot resolve modern PyPI metadata.
# The easybuild tree carries 3.12.3, which matches the 3.12.16 the homelab
# container runs, so the two platforms differ by a patch level rather than a
# minor version.
#
# /app1/ebenv only special-cases R-4.2.1, R-4.4.1 and Python-3.10.4 as arguments
# (see its tail), so a newer Python is selected with an explicit module load.
# Source this; do not pipe it, or the module load lands in a subshell and the
# environment change is discarded.

export FOW_ROOT=/hpctmp/$USER/fow
export FOW_VENV=$FOW_ROOT/venv

# /app1/ebenv reads LD_LIBRARY_PATH (line 39) and MODULEPATH before ever setting
# them, so sourcing it under `set -u` aborts with "unbound variable" and takes the
# job with it. Interactive shells have these set already, which is why it works by
# hand and failed in every PBS task. Disable -u across the source and restore
# whatever the caller had.
case $- in *u*) _fow_had_u=1 ;; *) _fow_had_u=0 ;; esac
set +u
source /app1/ebenv
module load Python/3.12.3-GCCcore-13.3.0
[ "$_fow_had_u" = 1 ] && set -u
unset _fow_had_u

if [ -f "$FOW_VENV/bin/activate" ]; then
    source "$FOW_VENV/bin/activate"
fi

export PYTHONPATH=$FOW_ROOT/repo/pair_b/src:$FOW_ROOT/experiment
