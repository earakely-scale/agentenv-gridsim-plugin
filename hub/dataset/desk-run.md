**Run the desk.** It lives on the plugin's `desk` branch; these commands pin the `{ref}` tag. In process, with no
Docker and no key, play the anchor policy on the pilot's two real battery-days:

```bash
git clone --branch {ref} https://github.com/earakely-scale/agentenv-gridsim-plugin
cd agentenv-gridsim-plugin && uv sync --extra dev
uv run python scripts/desk_run.py --pack desk-v2-pilot --policy anchor --out runs/anchor
```

Each run writes every battery-day's Episode JSON and a results row with its grade; `--policy model` with `--base-url`
plays a model behind any OpenAI-compatible endpoint the same way. The desk's tables load like the others:

```python
board = load_dataset(repo, "desk_leaderboard", split="{latest}")  # models and references
runs = load_dataset(repo, "desk_runs", split="{latest}")          # one row per battery-day
```
