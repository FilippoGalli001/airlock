// The Airlock demo video. Real footage (public/takes/*.webm, recorded by record.mjs) + title cards, zooms, captions.
// Times are in seconds of the source take; see public/takes/*.json for the marks they came from.
import React from "react";
import {
  AbsoluteFill, Img, OffthreadVideo, Sequence, Series, interpolate, staticFile, useCurrentFrame, Easing,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";

export const FPS = 30;
const { fontFamily } = loadFont("normal", { weights: ["400", "600", "700"], subsets: ["latin"] });
const INK = "#f2f1ec";
const BG = "#111210";
const GREEN = "#6cc394";
const RED = "#ef7b72";
const sec = s => Math.round(s * FPS);
const ease = Easing.bezier(0.4, 0, 0.2, 1);

// ---------- building blocks ----------

// One stretch of a take. Recorded at 1536x864, shown at 1920x1080 (= browser zoom 125%).
// zoom: keyframes [{t, s, x, y}] in seconds from the start of this segment; x,y = focus point in 1920x1080 px.
const seg = (take, from, to, { rate = 1, zoom = [{ t: 0, s: 1, x: 960, y: 540 }] } = {}) => ({
  frames: Math.round(((to - from) / rate) * FPS),
  render: () => <Clip take={take} from={from} rate={rate} zoom={zoom} />,
});

const Clip = ({ take, from, rate, zoom }) => {
  const f = useCurrentFrame();
  const ts = zoom.map(k => sec(k.t));
  const pick = key => (zoom.length === 1 ? zoom[0][key]
    : interpolate(f, ts, zoom.map(k => k[key]), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease }));
  const s = pick("s"), x = pick("x"), y = pick("y");
  // keep the focus point where it is on screen, without showing outside the frame
  const tx = Math.min(0, Math.max(1920 - 1920 * s, 960 - x * s));
  const ty = Math.min(0, Math.max(1080 - 1080 * s, 540 - y * s));
  return (
    <AbsoluteFill style={{ background: "#f5f4ef", overflow: "hidden" }}>
      <div style={{ width: 1920, height: 1080, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${s})` }}>
        <OffthreadVideo src={staticFile(`takes/${take}.webm`)} trimBefore={sec(from)} playbackRate={rate} muted
          style={{ width: 1920, height: 1080 }} />
      </div>
    </AbsoluteFill>
  );
};

const fade = (f, dur, inF = 8, outF = 8) =>
  Math.min(interpolate(f, [0, inF], [0, 1], { extrapolateRight: "clamp" }),
    interpolate(f, [dur - outF, dur], [1, 0], { extrapolateLeft: "clamp" }));

// Captions: [{at, dur, text, tone}] in seconds from the start of the scene.
const Captions = ({ items }) => (
  <>
    {items.map((c, i) => (
      <Sequence key={i} from={sec(c.at)} durationInFrames={sec(c.dur)} layout="none">
        <Caption text={c.text} tone={c.tone} pos={c.pos} dur={sec(c.dur)} />
      </Sequence>
    ))}
  </>
);

const Caption = ({ text, tone, pos, dur }) => {
  const f = useCurrentFrame();
  const o = fade(f, dur);
  const lift = interpolate(f, [0, 10], [pos === "top" ? -14 : 14, 0], { extrapolateRight: "clamp", easing: ease });
  const accent = tone === "red" ? RED : tone === "green" ? GREEN : "#9cc1f0";
  return (
    <AbsoluteFill style={{ justifyContent: pos === "top" ? "flex-start" : "flex-end", alignItems: "center",
      paddingTop: 40, paddingBottom: 36, pointerEvents: "none" }}>
      <div style={{
        opacity: o, transform: `translateY(${lift}px)`, maxWidth: 1560, padding: "18px 34px", borderRadius: 18,
        background: "rgba(17,18,16,0.9)", color: INK, fontFamily, fontWeight: 600, fontSize: 46, lineHeight: 1.25,
        textAlign: "center", boxShadow: "0 10px 40px rgba(0,0,0,.25)", borderLeft: `8px solid ${accent}`,
      }}>{text}</div>
    </AbsoluteFill>
  );
};

const Card = ({ children }) => (
  <AbsoluteFill style={{ background: BG, color: INK, fontFamily, justifyContent: "center", padding: "0 160px" }}>
    {children}
  </AbsoluteFill>
);

const Appear = ({ at, children, style }) => {
  const f = useCurrentFrame() - sec(at);
  const o = interpolate(f, [0, 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const y = interpolate(f, [0, 12], [18, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  return <div style={{ opacity: o, transform: `translateY(${y}px)`, ...style }}>{children}</div>;
};

const Wordmark = () => (
  <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 40, fontWeight: 700, color: GREEN, marginBottom: 46 }}>
    <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke={GREEN} strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="4" /><path d="M9 3v18M15 3v18" />
    </svg>
    Airlock
  </div>
);

// ---------- scenes ----------

const Hook = () => (
  <Card>
    <Appear at={0.2}><Wordmark /></Appear>
    <Appear at={0.6} style={{ fontSize: 84, fontWeight: 700, lineHeight: 1.08, whiteSpace: "nowrap" }}>Your documents can attack your AI.</Appear>
    <Appear at={2.4} style={{ fontSize: 50, fontWeight: 400, marginTop: 40, color: "#cfcdc5", lineHeight: 1.3 }}>
      Airlock opens them in a Fly.io Sprite <span style={{ color: GREEN, fontWeight: 600 }}>with no keys</span>,
      then <span style={{ color: GREEN, fontWeight: 600 }}>wipes it</span>.
    </Appear>
  </Card>
);

const Close = () => (
  <Card>
    <Appear at={0.2}><Wordmark /></Appear>
    <Appear at={0.5} style={{ fontSize: 70, fontWeight: 700, lineHeight: 1.15 }}>The AI proposes.</Appear>
    <Appear at={1.0} style={{ fontSize: 70, fontWeight: 700, lineHeight: 1.15 }}>Code decides.</Appear>
    <Appear at={1.5} style={{ fontSize: 70, fontWeight: 700, lineHeight: 1.15, color: GREEN }}>You approve what's risky.</Appear>
    <Appear at={2.4} style={{ fontSize: 44, marginTop: 36, color: "#cfcdc5" }}>Every document gets a fresh Sprite.</Appear>
    <Appear at={3.2} style={{ fontSize: 34, marginTop: 60, color: "#9c998f", lineHeight: 1.6 }}>
      <span style={{ color: INK }}>Live demo: airlock-ctrl-jmgx.sprites.app</span><br />
      Code: github.com/FilippoGalli001/airlock<br />Fly.io Sprites · Ollama · Box · Pinecone
    </Appear>
  </Card>
);

// A real screenshot of the Box folder (names only: account details cropped out), with a slow push-in.
const BoxShot = () => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, sec(3.2)], [1, 1.06], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: "#f5f4ef", justifyContent: "center", alignItems: "center" }}>
      <div style={{ transform: `scale(${z})`, opacity: fade(f, sec(3.2), 8, 6), background: "#fff", borderRadius: 22,
        padding: "34px 44px", boxShadow: "0 20px 60px rgba(0,0,0,.12)", marginBottom: 150 }}>
        <Img src={staticFile("box-files.png")} style={{ width: 1515, display: "block" }} />
      </div>
      <Captions items={[{ at: 0.2, dur: 2.9, text: "Really on Box: the PDF and its .airlock.json record", tone: "green" }]} />
    </AbsoluteFill>
  );
};

// Each scene: segments of takes played in series, plus captions timed against the scene.
const SCENES = [
  { name: "hook", frames: sec(5.8), render: () => <Hook /> },

  { name: "architecture", segs: [
      seg("A", 1.3, 1.9, { rate: 0.06, zoom: [
        { t: 0, s: 1, x: 960, y: 540 }, { t: 1.2, s: 1.7, x: 640, y: 70 }, { t: 4.6, s: 1.7, x: 640, y: 70 },
        { t: 6.0, s: 1.7, x: 1500, y: 70 }, { t: 9.4, s: 1.7, x: 1500, y: 70 }, { t: 10, s: 1, x: 960, y: 540 }] }),
    ], captions: [
      { at: 1.0, dur: 4.2, text: "airlock-ctrl calls the connectors (Ollama · Box · Pinecone) and never opens a file" },
      { at: 5.6, dur: 4.2, text: "The chamber: no connectors, no network, wiped after every document", tone: "red" },
    ] },

  { name: "bill", segs: [
      seg("A", 2.6, 21.2, { rate: 2.8 }),
      seg("A", 29.6, 33.0, { zoom: [{ t: 0, s: 1, x: 960, y: 540 }, { t: 0.5, s: 1.7, x: 1500, y: 70 }] }),
    ], captions: [
      { at: 0.2, dur: 3.2, text: "A scanned bill, OCR'd inside the jail" },
      { at: 3.6, dur: 3.0, text: "The agent checks the math with code, in the jail" },
      { at: 6.9, dur: 3.1, text: "Clean bill → filed on Box automatically. Chamber wiped.", tone: "green" },
    ] },

  { name: "box", frames: sec(3.2), render: () => <BoxShot /> },

  { name: "invoice", segs: [
      seg("B", 2.8, 13.4, { rate: 3 }),
      seg("B", 13.4, 20.5, { zoom: [{ t: 0, s: 1, x: 960, y: 540 }, { t: 3.0, s: 1, x: 960, y: 540 },
        { t: 4.0, s: 1.55, x: 1120, y: 620 }] }),
    ], captions: [
      { at: 0.2, dur: 3.4, text: "A plumber's invoice" },
      { at: 3.8, dur: 7.0, text: "The agent's code finds a $30 overcharge → a person must look", tone: "red" },
    ] },

  { name: "review", segs: [
      seg("C", 2.8, 14.6, { rate: 1.7, zoom: [{ t: 0, s: 1, x: 960, y: 540 }, { t: 1.6, s: 1.35, x: 1300, y: 640 }] }),
      seg("C", 26.4, 28.4, { zoom: [{ t: 0, s: 1, x: 960, y: 540 }] }),
      seg("D", 2.8, 12.0, { rate: 3 }),
      seg("D", 11.9, 14.2, { zoom: [{ t: 0, s: 1, x: 960, y: 540 }, { t: 0.6, s: 1.5, x: 1000, y: 690 }] }),
      seg("D", 14.2, 18.4, { zoom: [{ t: 0, s: 1, x: 960, y: 540 }, { t: 0.8, s: 1.55, x: 1060, y: 560 }] }),
    ], captions: [
      { at: 0.2, dur: 3.4, text: "A paystub: SSN + bank account → you decide" },
      { at: 3.8, dur: 3.2, text: "You fix the issuer and say why" },
      { at: 7.2, dur: 2.0, text: "Approved → filed on Box, remembered in Pinecone", tone: "green" },
      { at: 9.4, dur: 2.5, text: "Next month's paystub arrives…" },
      { at: 12.1, dur: 2.2, text: "The issuer is already written your way…", tone: "green" },
      { at: 14.5, dur: 3.8, text: "…because Pinecone recalled your note (match 0.91)", tone: "green" },
    ] },

  { name: "contracts", segs: [
      seg("E", 2.6, 8.4, { zoom: [{ t: 0.3, s: 1, x: 960, y: 540 }, { t: 1.2, s: 1.35, x: 1160, y: 380 }] }),
      seg("E", 8.4, 13.0, { zoom: [{ t: 0, s: 1.35, x: 1160, y: 380 }] }),
    ], captions: [
      { at: 0.2, dur: 5.5, text: "A contract hides orders for the AI → caught by a fixed rule and the model", tone: "red" },
      { at: 5.9, dur: 4.4, text: "Paraphrased: the rule misses it. The model doesn't.", tone: "red" },
    ] },

  { name: "redteam", segs: [
      seg("F", 2.4, 9.6, { zoom: [{ t: 0, s: 1, x: 960, y: 540 }, { t: 5.2, s: 1, x: 960, y: 540 },
        { t: 6.4, s: 1.45, x: 1320, y: 1000 }] }),
      seg("F", 9.6, 13.4, { zoom: [{ t: 0, s: 1.45, x: 1320, y: 1000 }] }),
      seg("F", 13.4, 18.1, { zoom: [{ t: 0, s: 1.45, x: 1320, y: 1000 }, { t: 1.0, s: 1.9, x: 1540, y: 50 }] }),
    ], captions: [
      { at: 0.2, dur: 3.6, text: "Now assume the AI was fooled", tone: "red" },
      { at: 4.0, dur: 3.2, text: "Hostile code runs in the chamber…", pos: "top" },
      { at: 7.4, dur: 4.0, text: "No keys to steal. No network. The canary trips.", tone: "red", pos: "top" },
      { at: 11.6, dur: 4.0, text: "Nothing leaves. The chamber is wiped clean.", tone: "green" },
    ] },

  { name: "close", frames: sec(7), render: () => <Close /> },
];

const sceneFrames = s => s.frames ?? s.segs.reduce((a, g) => a + g.frames, 0);
export const TOTAL_FRAMES = SCENES.reduce((a, s) => a + sceneFrames(s), 0);

const Scene = ({ scene }) => {
  if (scene.render) return scene.render();
  return (
    <AbsoluteFill>
      <Series>
        {scene.segs.map((g, i) => (
          <Series.Sequence key={i} durationInFrames={g.frames}>{g.render()}</Series.Sequence>
        ))}
      </Series>
      <Captions items={scene.captions || []} />
    </AbsoluteFill>
  );
};

export const Airlock = () => (
  <AbsoluteFill style={{ background: BG }}>
    <Series>
      {SCENES.map(s => (
        <Series.Sequence key={s.name} durationInFrames={sceneFrames(s)}>
          <Scene scene={s} />
        </Series.Sequence>
      ))}
    </Series>
  </AbsoluteFill>
);
