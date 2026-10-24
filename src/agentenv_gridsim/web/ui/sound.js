/** Optional sound, off by default: a quiet transformer hum whose level follows the MW flowing. */
export function buildSound() {
  let ctx = null, gain = null;
  return {
    set(on) {
      if (on && !ctx) {
        ctx = new AudioContext();
        gain = ctx.createGain();
        gain.gain.value = 0;
        const lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.value = 500;
        for (const [f, g] of [[120, 1], [240, 0.35], [360, 0.12]]) {
          const o = ctx.createOscillator();
          o.frequency.value = f;
          const og = ctx.createGain();
          og.gain.value = g;
          o.connect(og).connect(lp);
          o.start();
        }
        lp.connect(gain).connect(ctx.destination);
      }
      if (ctx) on ? ctx.resume() : ctx.suspend();
    },
    level(load) {
      if (gain) gain.gain.setTargetAtTime(0.012 + 0.05 * load, ctx.currentTime, 0.3);
    },
  };
}
