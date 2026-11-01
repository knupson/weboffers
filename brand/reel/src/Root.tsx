import React from "react";
import { Composition } from "remotion";
import { Reel1, totalFrames, FPS } from "./Reel1";

import { Duelo, tiemposDuelo, type DueloProps } from "./Duelo";
import duelo from "./duelo.json";

export const RemotionRoot = () => (
  <>
  <Composition id="Reel1" component={Reel1} durationInFrames={totalFrames} fps={FPS} width={1080} height={1920} />
  <Composition id="Duelo" component={Duelo} defaultProps={duelo as DueloProps} calculateMetadata={({ props }) => ({ durationInFrames: tiemposDuelo(props).totalFrames })} fps={FPS} width={1080} height={1920} />
  </>
);
