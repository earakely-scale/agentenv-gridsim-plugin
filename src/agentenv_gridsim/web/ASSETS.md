# Viewer assets

Everything in the scene is procedural: geometry built in code (`stage/*.js`) and textures drawn on a canvas at load
(panel seams, louvres, the chain-link fence, the Texas state flag, glow sprites). No image or model file ships; the desk
pages (`desk/`) ship IBM Plex Sans and Mono.

| Asset | Source | Licence |
|---|---|---|
| three.js 0.180.0 (`vendor/three-0.180.0/build`, `OrbitControls.js`, `BufferGeometryUtils.js`, `Sky.js`, `RectAreaLightUniformsLib.js` and `RectAreaLightTexturesLib.js` for the trading room's area lights) | https://github.com/mrdoob/three.js (npm `three@0.180.0`) | MIT, `vendor/three-0.180.0/LICENSE` |
| Sky model (`Sky.js`, Preetham) | three.js examples | MIT |
| Battery enclosures, inverter skids, transformers, substation, lattice towers, fence, O&M building | procedural, this repository | CC0 |
| Terrain, shrubs, trees, wind turbines, pumpjacks, refinery, grain elevator, city massing | procedural, this repository | CC0 |
| Texas state flag (drawn on a canvas) | public state symbol, drawn in code | public domain |
| IBM Plex Sans and IBM Plex Mono, Latin subsets (`desk/fonts/`) | https://github.com/IBM/plex | SIL Open Font License 1.1, `desk/fonts/OFL.txt` |
| v5 trading room (desks, monitors, turrets, people, video wall, curtain-wall towers), gas peaker plant, tracker block | procedural, this repository | CC0 |

No ERCOT logo or trademark appears, and the battery enclosures carry no brand.
