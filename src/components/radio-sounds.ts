/*
 * Radio sounds.
 * - tick: a tiny band-passed click per keystroke, synthesised with Web Audio.
 * Audio starts on the first call, which always comes from a key press, so browsers allow it.
 */

let ctx: AudioContext | null = null;
let noise: AudioBuffer | null = null;

function audio() {
  if (typeof window === "undefined") return null;
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  if (!noise) {
    noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  }
  return ctx;
}

// A burst of static through a band-pass, shaped by a fast attack and exponential fall.
function staticBurst(a: AudioContext, at: number, length: number, freq: number, q: number, peak: number) {
  const src = a.createBufferSource();
  src.buffer = noise;
  const band = a.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = freq;
  band.Q.value = q;
  const gain = a.createGain();
  gain.gain.setValueAtTime(0, at);
  gain.gain.linearRampToValueAtTime(peak, at + 0.003);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
  src.connect(band).connect(gain).connect(a.destination);
  src.start(at, Math.random() * 0.5, length + 0.02);
}

export function playTick() {
  const a = audio();
  if (!a) return;
  // Small random pitch so fast typing doesn't sound like a machine gun.
  staticBurst(a, a.currentTime, 0.022, 2600 + Math.random() * 900, 6, 0.09);
}
