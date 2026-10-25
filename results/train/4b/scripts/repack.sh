set -e
cd /home/ubuntu/gs
tar -C pack -czf adapter-4b-final.tgz adapter/sft-lora adapter/grpo-lora
tar -C pack -czf adapter-4b-ckpts.tgz adapter/checkpoints
ls -la results-4b.tgz adapter-4b-final.tgz adapter-4b-ckpts.tgz; ls pack/adapter pack/adapter/checkpoints | tr '\n' ' '
