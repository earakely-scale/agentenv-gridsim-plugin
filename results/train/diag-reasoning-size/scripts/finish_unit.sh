#!/bin/bash
G=/home/ubuntu/gridsim-diag; R=$G/runs/diag; F=$R/eval_q8b-on16384-n50.json
end=$(date -u -d '2026-10-26 22:50' +%s)
while [ ! -f $F ] && [ "$(date -u +%s)" -lt "$end" ]; do sleep 5; done
sleep 8
systemctl stop gsd-run2; pkill -f code/diag_eval.py; sleep 5
[ -f $F ] && echo "PROBE_DONE $(date -u)" || echo "PROBE_STOPPED $(date -u)"
ls $R
tar -C $G/runs -czf $G/results-diag.tgz diag && ls -la $G/results-diag.tgz
nvidia-smi -i 3 --query-gpu=memory.used --format=csv,noheader
echo FINISH_DONE
