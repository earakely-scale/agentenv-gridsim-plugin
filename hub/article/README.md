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
short_description: Models in agent harnesses run a real ERCOT battery desk
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
  https://huggingface.co/spaces/earakely-scale/GridSimEnv/resolve/main/app/public/og/og-image.jpg
---

# GridSimEnv Desk: a real ERCOT battery's trading desk

A long-form research article on **GridSimEnv Desk**, an RL environment in which an agent runs a real Texas grid
battery's trading desk through ERCOT's day-ahead market and real time. It submits ERCOT's own market objects (energy
bid/offer curves, the Current Operating Plan, from v3 reserve offers) on prices, forecasts, notices and alerts as each
was posted, while AgentEnv's virtual clock stands still in a turn and runs between turns. Every task settles on the
battery's ERCOT statement and is graded against the hindsight optimum and the battery's real operator, whose bids ERCOT
discloses 60 days later. The article leads with the v4 benchmark: models in native agent harnesses (Claude Code, Codex
CLI, Gemini CLI, and OpenCode for the open Qwen3-4B) run the desk for three days at a time across real Texas weather
fronts, and it reports their hindsight capture before and after the models' training cutoffs, with what a window cost.
Then come the desk itself, its clock and tools, the development ladder of versions v2 to v4 and the v5 price-impact check,
the methods and the limitations.

- **Dataset:** [earakely-scale/GridSimEnv-AgentEnv](https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv),
  the benchmark's grades and Episode JSON under `results/desk-v4-bench`, and every development task, reference, grade,
  Episode JSON and run log under `results/desk-v2` to `results/desk-v5`.
- **Viewer:** [earakely-scale/GridSimEnv-AgentEnv](https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv), the benchmark's [results and 3D replays](https://earakely-scale-gridsimenv-agentenv.static.hf.space/results.html?v=bench) first, then the desk's development runs version by version.
- **Code:** [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin), a plugin for the
  [AgentEnv Framework](https://www.agentenvframework.com).

GridSimEnv v1 (one-shot day-ahead schedule, training results) is archived at revision
[fcf2a721](https://huggingface.co/spaces/earakely-scale/GridSimEnv/tree/fcf2a721790ca530f222c5206ae7df2d7a4becd0).

Built with the [research-article-template](https://huggingface.co/spaces/tfrere/research-article-template) by Thibaud
Frere, licensed CC BY 4.0, with GridSimEnv's own chapters, charts and colours.

## Where the content lives

The source is `hub/article/` in [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin),
and `scripts/hub_article.py` there rebuilds the article's data and publishes this Space.

| Path | What |
| --- | --- |
| `app/src/content/article.mdx` | Front matter and the chapter registry, in running order |
| `app/src/content/chapters/` | One `.mdx` per section; every number in the prose is read from `facts.json` |
| `app/src/content/embeds/` | The D3 figures, one file each; the benchmark's two draw with the dataset card's own chart code |
| `app/src/content/assets/data/` | The figures' data: `bench.json` (from `results/desk-v4-bench/summary.json`), `desk.json` (from `results/overview/desk.json`), `facts.json` (the prose's numbers, formatted from both), and the banner's front and the bid curve, read from the committed episodes and grades |
| `app/src/content/bibliography.bib` | References, cited as `[@key]` |
| `app/public/` | The social card, and `scripts/desk-charts.js`, the dataset card's chart code (`hub/desk-charts/charts.js`) |

```bash
cd app && npm ci && npm run dev     # http://localhost:4321
```

## Licences

Text and charts: CC BY 4.0. Prices, forecasts, notices and the 60-day disclosures are ERCOT's public data, used under
ERCOT's Website User Agreement and not relicensed; weather alerts are the U.S. National Weather Service's. GridSimEnv
is not affiliated with or endorsed by ERCOT. The batteries are shown only as anonymised cards. Texas outline: U.S.
Census Bureau via us-atlas. The code is Apache-2.0.
