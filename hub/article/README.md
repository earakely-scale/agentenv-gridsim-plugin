---
title: "GridSimEnv: running a grid battery on ERCOT's real prices"
emoji: 🔋
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8080
header: mini
pinned: false
license: cc-by-4.0
short_description: A Texas grid battery on real ERCOT prices, as an RL env
tags:
  - research-article-template
  - rl-environments
  - reinforcement-learning
  - simulation
  - energy
  - electricity-markets
  - battery-storage
  - agentenv
thumbnail: >-
  https://huggingface.co/spaces/earakely-scale/GridSimEnv/resolve/main/app/public/og/og-image.jpg
---

# GridSimEnv: running a grid battery on ERCOT's real prices

A long-form research article on **GridSimEnv**, an RL environment in which an agent runs one grid battery at an ERCOT
hub or load zone for one day, on the Texas day-ahead market's real prices, graded exactly against the optimum a
dynamic program finds. It covers the environment, how GPT-6.1 Sol, GPT-6 Luna, Beam-1.0 and Qwen3-4B bid, how the 4B
was trained (solver labels, GRPO in TRL, and exact per-hour advantages from the dynamic program), what the decisions
are worth in dollars per MW of battery, and the live sealed board.

- **Dataset:** [earakely-scale/GridSimEnv-AgentEnv](https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv),
  every battery-day, its references and every published run, with the results folders the article cites.
- **3D viewer:** [earakely-scale/GridSimEnv-AgentEnv](https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv),
  every recorded run replayed as a battery yard in its region, and the live board.
- **Code:** [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin), a plugin for the
  [AgentEnv Framework](https://www.agentenvframework.com).

Built with the [research-article-template](https://huggingface.co/spaces/tfrere/research-article-template) by Thibaud
Frere, licensed CC BY 4.0, with GridSimEnv's own chapters, charts and colours.

## Where the content lives

The source is `hub/article/` in [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin),
and `scripts/hub_article.py` there rebuilds the article's data and publishes this Space.

| Path | What |
| --- | --- |
| `app/src/content/article.mdx` | Front matter and the chapter registry, in running order |
| `app/src/content/chapters/` | One `.mdx` per section |
| `app/src/content/embeds/` | The D3 and HTML figures, one file each |
| `app/src/content/assets/data/` | The figures' data: `results.json` (from `results/overview/results.json`), and the days, the advantage example, the timeline and the banner, re-graded with `gridsim_core` |
| `app/src/content/bibliography.bib` | References, cited as `[@key]` |
| `app/public/` | The stills, the recorded replay and the social card |

```bash
cd app && npm ci && npm run dev     # http://localhost:4321
```

## Licences

Text and charts: CC BY 4.0. The prices are ERCOT's public data (report NP4-180-ER), used under ERCOT's Website User
Agreement and not relicensed; GridSimEnv is not affiliated with or endorsed by ERCOT. Battery sizes: U.S. EIA Form
EIA-860, public domain. Weather in the viewer: Iowa Environmental Mesonet. Texas outline: U.S. Census Bureau via
us-atlas. The code is Apache-2.0.
