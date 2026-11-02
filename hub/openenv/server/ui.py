"""The Try Environment tab: reset(split=) and reset(index=) over the windows, load one or draw one at random, and the
play page under them (/play/), which plays the window over its own OpenEnv WebSocket session with the tools, budgets
and grading the benchmark's agents had."""

import html
import random
from urllib.parse import quote

import gradio as gr

from .windows import windows

STYLE = ("<style>.gradio-container{width:100%!important;max-width:1440px!important}"
         ".gradio-container h1{font-size:22px!important;margin:4px 0 6px!important;letter-spacing:-.01em}"
         ".gradio-container .main.fillable{max-width:none!important;padding-left:12px!important;"
         "padding-right:12px!important}.gradio-container .html-container:has(iframe.gs-play){padding:0!important}"
         ".gs-reset{align-items:end!important;gap:10px!important}"
         ".gs-reset button{min-height:42px!important;max-height:46px}"
         "iframe.gs-play{width:100%;height:calc(100vh - 228px);min-height:700px;display:block;border-radius:10px;"
         "border:1px solid var(--border-color-primary)}"
         "@media (max-width:700px){iframe.gs-play{height:1240px;min-height:0}}</style>")


def _label(n: int) -> str:
    return f"reset(index=)  ·  0 to {n - 1}"


def frame(index, split: str) -> str:
    w = windows()
    ids = w.ids(split if split in w.splits() else w.split)
    i = min(max(int(index or 0), 0), len(ids) - 1)
    card = w.cards[ids[i]]
    src = f"/play/?embed=1&split={quote(w.split)}&index={i}&task={quote(ids[i])}"
    return (f'{STYLE}<iframe class="gs-play" src="{html.escape(src)}" title="GridSimEnv Desk: '
            f'{html.escape(card["title"])}" allow="fullscreen"></iframe>')


def build_try() -> gr.Blocks:
    w = windows()
    ids = w.ids(w.split)
    i0 = ids.index(w.default)
    with gr.Blocks() as ui:
        with gr.Row(elem_classes="gs-reset"):
            split_box = gr.Dropdown(choices=w.splits(), value=w.split, label="reset(split=)", scale=1,
                                    interactive=len(w.splits()) > 1)
            index_box = gr.Number(value=i0, minimum=0, maximum=len(ids) - 1, step=1, precision=0,
                                  label=_label(len(ids)), scale=2)
            load = gr.Button("load episode", variant="primary", scale=1)
            draw = gr.Button("random episode", scale=1)
        pane = gr.HTML(frame(i0, w.split), show_label=False)

        def drawn(split: str):
            i = random.randrange(len(w.ids(split)))
            return i, frame(i, split)

        load.click(frame, [index_box, split_box], pane)
        draw.click(drawn, split_box, [index_box, pane])
    return ui
