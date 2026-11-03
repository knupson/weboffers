import React from "react";
import { Composition } from "remotion";
import { Reel1, totalFrames, FPS } from "./Reel1";

import { Duelo, tiemposDuelo, type DueloProps } from "./Duelo";
import duelo from "./duelo.json";
import { Historia, FRAMES_HISTORIA, FPS_HISTORIA } from "./Historia";

export const RemotionRoot = () => (
  <>
  <Composition id="Reel1" component={Reel1} durationInFrames={totalFrames} fps={FPS} width={1080} height={1920} />
  <Composition id="Duelo" component={Duelo} defaultProps={duelo as DueloProps} calculateMetadata={({ props }) => ({ durationInFrames: tiemposDuelo(props).totalFrames })} fps={FPS} width={1080} height={1920} />
  <Composition id="Historia" component={Historia} defaultProps={{ img: "sony-wh-ch520.webp", nombre: "Sony WH-CH520" }} durationInFrames={FRAMES_HISTORIA} fps={FPS_HISTORIA} width={1080} height={1920} />
  </>
);
