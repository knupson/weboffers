// Reel 1 de Instagram — «¿Amazon o Mercado Libre?».
// Precios relevados y verificados contra ML y Amazon el 01/11/2026 (los mismos que publicaba ofertas.knunet.com ese día).
import { Audio } from "@remotion/media";
import { loadFont } from "@remotion/fonts";
import { fitText } from "@remotion/layout-utils";
import React, { createContext, useContext, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const FPS = 30;

const C = {
  esmalte: "#141210",
  crema: "#f4efe4",
  crema2: "#cfc6b6",
  rojo: "#d7262b",
  amarillo: "#f2c230",
  verde: "#5cc489",
  celeste: "#6ec6f0",
};
const ULTRA = "Ultra";
const ARCHIVO = "Archivo";

// fitText mide con la fuente real: no se dibuja nada hasta que las dos estén cargadas.
const fuentes = Promise.all([
  loadFont({ family: ULTRA, url: staticFile("ultra.woff2") }),
  loadFont({ family: ARCHIVO, url: staticFile("archivo.woff2"), weight: "100 900" }),
]);
const ConFuentes = ({ children }: { children: ReactNode }) => {
  const [listo, setListo] = useState(false);
  const [h] = useState(() => delayRender("fuentes"));
  useEffect(() => {
    fuentes.then(() => {
      setListo(true);
      continueRender(h);
    });
  }, [h]);
  return listo ? <>{children}</> : null;
};

// Duración de cada locución (ffprobe) + aire para que respire la escena.
export type DueloProducto = {
  img: string; nombre: string; ml: number; az: number;
  mlAt: number[]; azAt: number[]; gana: "ml" | "amazon";
  ganaAt: number; nota: string;
};
export type DueloProps = {
  voz: number[]; audio: string[]; subs: [number, string][][];
  duelos: DueloProducto[]; hookImage: string; cantidad: number;
  textos: {
    marca: string; gancho: string[]; ganchoSub: string; giro: string[];
    regla: string; tarjetas: { titulo: string; sub: string }[];
    cierre: string[]; ml: string; amazon: string; selloMl: string;
    selloAmazon: string; pie: string;
  };
};
const Datos = createContext<DueloProps>(null!);
const useDatos = () => useContext(Datos);
const AIRE = [0.25, 1.0, 0.25, 1.0, 0.5, 1.4];
export const tiemposDuelo = (props: DueloProps, fps = FPS) => {
  if (props.voz.length !== 6 || props.audio.length !== 6 || props.subs.length !== 6 || props.duelos.length !== 2 || props.voz.some(v => !Number.isFinite(v) || v <= 0)) {
    throw new Error("Duelo necesita seis escenas con audio, subtítulos y duraciones positivas, y dos productos.");
  }
  const dur = props.voz.map((v, i) => Math.ceil((v + AIRE[i]) * fps));
  const start = dur.map((_, i) => dur.slice(0, i).reduce((a, b) => a + b, 0));
  return { dur, start, totalFrames: dur.reduce((a, b) => a + b, 0) };
};

const ars = (n: number) => "$ " + Math.round(n).toLocaleString("es-AR");
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const SALIDA = Easing.bezier(0.23, 1, 0.32, 1);
const W = 920; // ancho útil (zona segura de Reels)

// ---------- piezas ----------

const useSec = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return { frame, fps, s: (sec: number) => Math.round(sec * fps) };
};

/** Entra con resorte en `at` segundos (relativo a la escena). */
const Pop = ({ at, children, from = 0.6, y = 40, style }: { at: number; children: ReactNode; from?: number; y?: number; style?: CSSProperties }) => {
  const { frame, fps, s } = useSec();
  const p = spring({ frame: frame - s(at), fps, config: { damping: 13, stiffness: 190, mass: 0.7 } });
  return (
    <div style={{ opacity: at <= 0.05 ? 1 : interpolate(p, [0, 0.4], [0, 1], clamp), scale: String(Math.min(1, interpolate(p, [0, 1], [from, 1]))), translate: `0px ${interpolate(p, [0, 1], [y, 0])}px`, ...style }}>
      {children}
    </div>
  );
};

/** Título en Ultra que nunca pasa del ancho dado. */
const Letra = ({ text, max, width = W, color = C.amarillo, sombra = true, style }: { text: string; max: number; width?: number; color?: string; sombra?: boolean; style?: CSSProperties }) => {
  const fs = Math.min(max, fitText({ text, withinWidth: width, fontFamily: ULTRA }).fontSize * 0.96);
  return (
    <div style={{ fontFamily: ULTRA, fontSize: fs, lineHeight: 1.02, color, whiteSpace: "nowrap", textAlign: "center", textShadow: sombra ? `.05em .05em 0 ${C.rojo}, .09em .09em 0 #0b0a09` : "none", ...style }}>
      {text}
    </div>
  );
};

const Texto = ({ children, size = 48, weight = 700, color = C.crema, style }: { children: ReactNode; size?: number; weight?: number; color?: string; style?: CSSProperties }) => (
  <div style={{ fontFamily: ARCHIVO, fontSize: size, fontWeight: weight, color, lineHeight: 1.2, textAlign: "center", ...style }}>{children}</div>
);

const Columna = ({ children, top, gap = 24 }: { children: ReactNode; top: number; gap?: number }) => (
  <div style={{ position: "absolute", top, left: (1080 - W) / 2, width: W, display: "flex", flexDirection: "column", alignItems: "center", gap }}>{children}</div>
);

// ---------- fondo y marca (todo el video) ----------

const Fondo = () => {
  const frame = useCurrentFrame();
  const a = frame / 90;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.esmalte,
        backgroundImage: [
          `radial-gradient(900px 700px at ${50 + Math.sin(a) * 18}% ${30 + Math.cos(a * 0.8) * 8}%, rgba(215,38,43,.22), transparent 70%)`,
          `radial-gradient(800px 800px at ${50 - Math.cos(a * 0.7) * 22}% ${75 + Math.sin(a) * 6}%, rgba(242,194,48,.12), transparent 70%)`,
          "repeating-linear-gradient(0deg, rgba(255,255,255,.025) 0 2px, transparent 2px 6px)",
        ].join(","),
      }}
    />
  );
};

const Marca = () => {
  const { textos } = useDatos();
  const { frame } = useSec();
  const { durationInFrames } = useVideoConfig();
  return (
    <>
      <div style={{ position: "absolute", top: 70, left: 80, right: 80, height: 8, borderRadius: 4, background: "rgba(244,239,228,.15)" }}>
        <div style={{ height: "100%", borderRadius: 4, background: C.amarillo, width: `${(frame / durationInFrames) * 100}%` }} />
      </div>
      <div style={{ position: "absolute", top: 110, width: "100%", textAlign: "center", fontFamily: ULTRA, fontSize: 50, color: C.amarillo, textShadow: `.05em .05em 0 ${C.rojo}` }}>{textos.marca}</div>
    </>
  );
};

// ---------- subtítulos por frase ----------

const Subs = ({ partes }: { partes: [number, string][] }) => {
  const { frame, s } = useSec();
  const actual = [...partes].reverse().find(([t]) => frame >= s(t));
  if (!actual) return null;
  const [t, txt] = actual;
  const p = interpolate(frame - s(t), [0, 6], [0, 1], { ...clamp, easing: SALIDA });
  return (
    <div style={{ position: "absolute", top: 1330, left: 70, right: 70, display: "flex", justifyContent: "center" }}>
      <div style={{ fontFamily: ARCHIVO, fontWeight: 800, fontSize: 54, lineHeight: 1.18, color: C.crema, textAlign: "center", background: "rgba(11,10,9,.82)", padding: "16px 30px", borderRadius: 20, opacity: p, translate: `0px ${(1 - p) * 16}px` }}>
        {txt}
      </div>
    </div>
  );
};

// ---------- escenas ----------

const Gancho = () => {
  const { textos, hookImage } = useDatos();
  const { frame, s } = useSec();
  const flote = Math.sin(frame / 12) * 8;
  return (
    <AbsoluteFill>
      <Columna top={290} gap={6}>
        <Pop at={0}><Letra text={textos.gancho[0]} max={170} color={C.crema} /></Pop>
        <Pop at={0.45}><Letra text={textos.gancho[1]} max={150} color={C.crema} /></Pop>
        <Pop at={0.82} from={0.55} y={0}><Letra text={textos.gancho[2]} max={230} /></Pop>
      </Columna>
      <div style={{ position: "absolute", top: 900, width: "100%", display: "flex", flexDirection: "column", alignItems: "center", gap: 28 }}>
        <Pop at={1.6} from={0.3} y={120}>
          <Img src={staticFile(hookImage)} style={{ width: 400, height: 400, objectFit: "contain", rotate: "-4deg", translate: `0px ${flote}px`, filter: "drop-shadow(0 30px 30px rgba(0,0,0,.5))" }} />
        </Pop>
        <Pop at={2.4}>
          <div style={{ fontFamily: ARCHIVO, fontWeight: 800, fontSize: 52, color: "#fff", background: C.rojo, padding: "14px 34px", borderRadius: 18, opacity: frame >= s(2.4) ? 1 : 0 }}>
            {textos.ganchoSub}
          </div>
        </Pop>
      </div>
    </AbsoluteFill>
  );
};

const Fila = ({ label, monto, desde, hasta, max, gana, ganaAt }: { label: string; monto: number; desde: number; hasta: number; max: number; gana: boolean; ganaAt: number }) => {
  const { frame, s } = useSec();
  const k = interpolate(frame, [s(desde), s(hasta)], [0, 1], { ...clamp, easing: SALIDA });
  const g = interpolate(frame, [s(ganaAt), s(ganaAt) + 8], [0, 1], clamp);
  const pierde = !gana && g > 0;
  return (
    <div style={{ width: W, padding: "18px 30px 22px", boxSizing: "border-box", borderRadius: 24, background: `rgba(244,239,228,${0.06 + g * (gana ? 0.06 : 0)})`, boxShadow: gana ? `inset 0 0 0 ${g * 5}px ${C.verde}` : "none", opacity: k > 0 ? (pierde ? 1 - g * 0.45 : 1) : 0.25 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", whiteSpace: "nowrap", gap: 20 }}>
        <span style={{ fontFamily: ARCHIVO, fontWeight: 700, fontSize: 42, color: C.crema2 }}>{label}</span>
        <span style={{ fontFamily: ULTRA, fontSize: 80, color: gana && g > 0 ? C.verde : C.crema }}>{(label.startsWith("Amazon") ? "~" : "") + ars(monto * k)}</span>
      </div>
      <div style={{ marginTop: 12, height: 18, borderRadius: 9, background: "rgba(244,239,228,.1)" }}>
        <div style={{ height: "100%", borderRadius: 9, width: `${(monto / max) * 100 * k}%`, background: gana && g > 0 ? C.verde : label.startsWith("Mercado") ? C.amarillo : C.celeste }} />
      </div>
    </div>
  );
};

const Sello = ({ text, at }: { text: string; at: number }) => {
  const { frame, fps, s } = useSec();
  const p = spring({ frame: frame - s(at), fps, config: { damping: 11, stiffness: 260, mass: 0.6 } });
  if (frame < s(at)) return null;
  return (
    <div style={{ position: "absolute", top: 330, right: 70, rotate: "8deg", scale: String(interpolate(p, [0, 1], [2.6, 1])), opacity: interpolate(p, [0, 0.3], [0, 1], clamp), fontFamily: ULTRA, fontSize: 64, lineHeight: 1, color: C.esmalte, background: C.verde, padding: "18px 26px", borderRadius: 18, boxShadow: `0 0 0 6px ${C.esmalte}, 0 0 0 10px ${C.verde}, 0 20px 40px rgba(0,0,0,.5)`, textAlign: "center", whiteSpace: "pre-line" }}>
      {text}
    </div>
  );
};

const DueloEscena = (d: DueloProducto) => {
  const { textos } = useDatos();
  const { frame } = useSec();
  const max = Math.max(d.ml, d.az);
  const ganaTxt = d.gana === "ml" ? textos.selloMl : textos.selloAmazon;
  return (
    <AbsoluteFill>
      <Columna top={220} gap={18}>
        <Pop at={0} from={0.5}>
          <Img src={staticFile(d.img)} style={{ width: 440, height: 440, objectFit: "contain", translate: `0px ${Math.sin(frame / 14) * 7}px`, filter: "drop-shadow(0 30px 30px rgba(0,0,0,.5))" }} />
        </Pop>
        <Pop at={0.15}><Texto size={54} weight={800}>{d.nombre}</Texto></Pop>
        <Fila label={textos.ml} monto={d.ml} desde={d.mlAt[0]} hasta={d.mlAt[1]} max={max} gana={d.gana === "ml"} ganaAt={d.ganaAt} />
        <Fila label={textos.amazon} monto={d.az} desde={d.azAt[0]} hasta={d.azAt[1]} max={max} gana={d.gana === "amazon"} ganaAt={d.ganaAt} />
        <Pop at={d.ganaAt + 0.15}><Texto size={44} weight={800} color={C.verde}>{d.nota}</Texto></Pop>
      </Columna>
      <Sello text={ganaTxt} at={d.ganaAt} />
      <div style={{ position: "absolute", top: 1480, width: "100%" }}>
        <Texto size={30} weight={600} color={C.crema2}>{textos.pie}</Texto>
      </div>
    </AbsoluteFill>
  );
};

const Giro = () => {
  const { textos } = useDatos();
  const { frame } = useSec();
  const shake = frame < 10 ? Math.sin(frame * 2.6) * (10 - frame) * 2.4 : 0;
  return (
    <AbsoluteFill style={{ translate: `${shake}px 0px` }}>
      <Columna top={560} gap={30}>
        <Pop at={0} from={0.55} y={0}><Letra text={textos.giro[0]} max={190} color={C.rojo} sombra={false} style={{ textShadow: `.05em .05em 0 ${C.crema}` }} /></Pop>
        <Pop at={0.85}><Letra text={textos.giro[1]} max={130} color={C.crema} /></Pop>
        <Pop at={1.3}><Letra text={textos.giro[2]} max={130} /></Pop>
      </Columna>
    </AbsoluteFill>
  );
};

const Tarjeta = ({ at, desde, titulo, sub, color }: { at: number; desde: number; titulo: string; sub: string; color: string }) => {
  const { frame, fps, s } = useSec();
  const p = spring({ frame: frame - s(at), fps, config: { damping: 16, stiffness: 170 } });
  return (
    <div style={{ width: W, boxSizing: "border-box", padding: "34px 40px", borderRadius: 30, background: "rgba(244,239,228,.07)", boxShadow: `inset 0 0 0 4px ${color}`, opacity: interpolate(p, [0, 0.3], [0, 1], clamp), translate: `${(1 - p) * desde}px 0px` }}>
      <Letra text={titulo} max={92} width={W - 100} color={color} sombra={false} style={{ textAlign: "left" }} />
      <Texto size={50} weight={800} style={{ textAlign: "left", marginTop: 14 }}>{sub}</Texto>
    </div>
  );
};

const Regla = () => {
 const { textos } = useDatos();
 return (
  <AbsoluteFill>
    <Columna top={330} gap={44}>
      <Pop at={0}><Letra text={textos.regla} max={150} /></Pop>
      <Tarjeta at={0.85} desde={-1100} titulo={textos.tarjetas[0].titulo} sub={textos.tarjetas[0].sub} color={C.amarillo} />
      <Tarjeta at={3.45} desde={1100} titulo={textos.tarjetas[1].titulo} sub={textos.tarjetas[1].sub} color={C.verde} />
    </Columna>
  </AbsoluteFill>
);

};

const Cierre = () => {
  const { textos, cantidad } = useDatos();
  const { frame, s } = useSec();
  const n = Math.round(interpolate(frame, [s(0.5), s(1.25)], [0, cantidad], { ...clamp, easing: SALIDA }));
  const salto = frame >= s(3.2) ? Math.abs(Math.sin((frame - s(3.2)) / 5)) * -18 : 0;
  return (
    <AbsoluteFill>
      <Columna top={300} gap={10}>
        <Pop at={0}><Texto size={60} weight={800}>{textos.cierre[0]}</Texto></Pop>
        <div style={{ opacity: frame < s(0.45) ? 0 : 1, fontFamily: ULTRA, fontSize: 300, lineHeight: 1, color: C.amarillo, textShadow: `.04em .04em 0 ${C.rojo}, .07em .07em 0 #0b0a09` }}>{n}</div>
        <Pop at={1.2}><Texto size={72} weight={900}>{textos.cierre[1]}</Texto><Texto size={56} weight={700} color={C.crema2}>{textos.cierre[2]}</Texto></Pop>
        <Pop at={1.9} style={{ marginTop: 50 }}>
          <div style={{ fontFamily: ULTRA, fontSize: 66, color: "#fff", background: C.rojo, padding: "24px 46px", borderRadius: 22, boxShadow: `inset 0 0 0 5px ${C.rojo}, inset 0 0 0 9px ${C.crema}` }}>{textos.cierre[3]}</div>
        </Pop>
        <Pop at={3.2} style={{ marginTop: 60, translate: `0px ${salto}px` }}>
          <Texto size={60} weight={900} color={C.amarillo}>{textos.cierre[4]}</Texto>
        </Pop>
      </Columna>
    </AbsoluteFill>
  );
};

// ---------- montaje ----------

const Musica = () => {
  const { durationInFrames } = useVideoConfig();
  return (
    <Audio
      src={staticFile("musica.mp3")}
      volume={(f) => interpolate(f, [0, 8, durationInFrames - 30, durationInFrames], [0, 0.13, 0.13, 0], clamp)}
    />
  );
};

export const Duelo = (props: DueloProps) => {
  const { dur: DUR, start: START } = tiemposDuelo(props);
  const ESCENAS = [<Gancho />, <DueloEscena {...props.duelos[0]} />, <Giro />, <DueloEscena {...props.duelos[1]} />, <Regla />, <Cierre />];
  const { fps } = useVideoConfig();
  return (
    <Datos.Provider value={props}><AbsoluteFill style={{ backgroundColor: C.esmalte }}>
     <ConFuentes>
      <Fondo />
      {ESCENAS.map((e, i) => (
        <Sequence key={i} name={`Escena ${i + 1}`} from={START[i]} durationInFrames={DUR[i]}>
          {e}
          <Subs partes={props.subs[i]} />
          <Audio src={staticFile(props.audio[i])} />
          {i > 0 && <Audio src="https://remotion.media/whoosh.wav" volume={0.35} />}
        </Sequence>
      ))}
      <Sequence name="Ding Amazon" from={START[1] + Math.round(props.duelos[0].ganaAt * fps)} durationInFrames={fps}>
        <Audio src="https://remotion.media/ding.wav" volume={0.4} />
      </Sequence>
      <Sequence name="Ding ML" from={START[3] + Math.round(props.duelos[1].ganaAt * fps)} durationInFrames={fps}>
        <Audio src="https://remotion.media/ding.wav" volume={0.4} />
      </Sequence>
      <Musica />
      <Marca />
     </ConFuentes>
    </AbsoluteFill></Datos.Provider>
  );
};
