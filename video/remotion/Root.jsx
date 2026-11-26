import { Composition } from "remotion";
import { Airlock, TOTAL_FRAMES, FPS } from "./Airlock.jsx";

export const Root = () => (
  <Composition id="Airlock" component={Airlock} durationInFrames={TOTAL_FRAMES} fps={FPS} width={1920} height={1080} />
);
