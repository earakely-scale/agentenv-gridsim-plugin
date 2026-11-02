---
title: "GridSimEnv Desk: a real ERCOT battery's trading desk"
emoji: 🔋
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8080
header: mini
pinned: false
license: cc-by-4.0
short_description: 15 AI models trade a real Texas battery
tags:
  - research-article-template
  - rl-environments
  - benchmark
  - agents
  - reinforcement-learning
  - simulation
  - energy
  - electricity-markets
  - battery-storage
  - agentenv
datasets:
  - earakely-scale/GridSimEnv-AgentEnv
thumbnail: >-
  https://huggingface.co/spaces/earakely-scale/GridSimEnv/resolve/main/app/public/og/gridsim-run.jpg
---

# GridSimEnv Desk: a real ERCOT battery's trading desk

A research article on **GridSimEnv Desk**, an RL environment in which an agent runs a real Texas grid battery's trading
desk on ERCOT's records: real prices, forecasts and grid conditions, each visible from the minute it was posted. The
agent runs the battery three days at a time across real weather fronts through the desk's tools (prices, forecasts,
the battery's status, the `optimize` planner, day-ahead and real-time offers with reserves, and the current operating
plan), and each window is scored by hindsight capture C, the share of the hindsight-optimal profit it captures.

The article opens on what is in the environment: a recorded benchmark run filmed on the 3D viewer, then the battery's
real operator against the agents on the windows where the agents did better, from ERCOT's 60-day disclosures.

- **Dataset:** [earakely-scale/GridSimEnv-AgentEnv](https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv),
  the benchmark's grades and Episode JSON under `results/desk-v4-bench`.
- **Viewer:** [earakely-scale/GridSimEnv-AgentEnv](https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv),
  every benchmark run replayed in 3D, and its [results](https://earakely-scale-gridsimenv-agentenv.static.hf.space/results.html?v=bench).
- **Code:** [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin), a plugin for the
  [AgentEnv Framework](https://www.agentenvframework.com).

GridSimEnv v1 (one-shot day-ahead schedule, training results) is archived at revision
[fcf2a721](https://huggingface.co/spaces/earakely-scale/GridSimEnv/tree/fcf2a721790ca530f222c5206ae7df2d7a4becd0).

Built with the [research-article-template](https://huggingface.co/spaces/tfrere/research-article-template) by Thibaud
Frere, licensed CC BY 4.0, with GridSimEnv's own chapters, charts and colours.

## Where the content lives

The source is `hub/article/` in [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin):
`scripts/hub_desk_film.py` films the run and `scripts/hub_article.py` rebuilds the article's data, checks it and
publishes this Space.

| Path | What |
| --- | --- |
| `app/src/content/article.mdx` | Front matter and the chapter registry, in running order |
| `app/src/content/chapters/` | One `.mdx` per section; every number in the prose is read from `facts.json` |
| `app/src/content/embeds/` | The D3 figures, one file each |
| `app/src/content/assets/data/` | The figures' data: `facts.json` (the prose's numbers) and `duel.json` (the real operator against the agents), from `results/desk-v4-bench`, its episodes and the benchmark's pack |
| `app/public/media/gridsim-run.mp4`, `gridsim-run.gif` | The run film, filmed on the viewer by `scripts/hub_desk_film.py`: the MP4 plays in the article, the GIF is its fallback; uploaded with the Space, not committed |
| `app/src/content/bibliography.bib` | References, cited as `[@key]` |
| `app/public/` | The social card and `scripts/gridsim-kit.js`, the figures' shared helpers |

```bash
cd app && npm ci && npm run dev     # http://localhost:4321
```

## Licences

Text and charts: CC BY 4.0. Prices, forecasts, notices and the 60-day disclosures are ERCOT's public data, used under
ERCOT's Website User Agreement and not relicensed; weather alerts are the U.S. National Weather Service's. GridSimEnv
is not affiliated with or endorsed by ERCOT. The batteries are shown only as anonymised cards. The code is Apache-2.0.
