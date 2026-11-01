import React from "react";
import { Composition } from "remotion";
import { Reel1, totalFrames, FPS } from "./Reel1";

export const RemotionRoot = () => (
  <Composition id="Reel1" component={Reel1} durationInFrames={totalFrames} fps={FPS} width={1080} height={1920} />
);
