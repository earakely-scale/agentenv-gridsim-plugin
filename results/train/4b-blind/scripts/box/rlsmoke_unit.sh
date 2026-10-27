#!/bin/bash
while [ ! -f /home/ubuntu/gs7/runs/sft/DONE ]; do sleep 10; done
NAME=smoke STEPS=4 bash /home/ubuntu/gs7/code/rl_unit.sh
