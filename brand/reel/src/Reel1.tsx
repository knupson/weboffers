// Reel 1 de Instagram — «¿Amazon o Mercado Libre?».
// Precios relevados y verificados contra ML y Amazon el 01/11/2026 (los mismos que publicaba ofertas.knunet.com ese día).
import { Audio } from "@remotion/media";
import { loadFont } from "@remotion/fonts";
import { fitText } from "@remotion/layout-utils";
import React, { useEffect, useState, type CSSProperties, type ReactNode } from "react";
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
const VOZ = [4.008, 7.2, 2.832, 8.4, 5.664, 4.848];
const AIRE = [0.25, 1.0, 0.25, 1.0, 0.5, 1.4];
const DUR = VOZ.map((v, i) => Math.ceil((v + AIRE[i]) * FPS));
const START = DUR.map((_, i) => DUR.slice(0, i).reduce((a, b) => a + b, 0));
export const totalFrames = DUR.reduce((a, b) => a + b, 0);

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
  const { frame } = useSec();
  const { durationInFrames } = useVideoConfig();
  return (
    <>
      <div style={{ position: "absolute", top: 70, left: 80, right: 80, height: 8, borderRadius: 4, background: "rgba(244,239,228,.15)" }}>
        <div style={{ height: "100%", borderRadius: 4, background: C.amarillo, width: `${(frame / durationInFrames) * 100}%` }} />
      </div>
      <div style={{ position: "absolute", top: 110, width: "100%", textAlign: "center", fontFamily: ULTRA, fontSize: 50, color: C.amarillo, textShadow: `.05em .05em 0 ${C.rojo}` }}>Franquicia 400</div>
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
  const { frame, s } = useSec();
  const flote = Math.sin(frame / 12) * 8;
  return (
    <AbsoluteFill>
      <Columna top={290} gap={6}>
        <Pop at={0}><Letra text="PAGÁS" max={170} color={C.crema} /></Pop>
        <Pop at={0.45}><Letra text="MÁS DEL" max={150} color={C.crema} /></Pop>
        <Pop at={0.82} from={0.55} y={0}><Letra text="DOBLE" max={230} /></Pop>
      </Columna>
      <div style={{ position: "absolute", top: 900, width: "100%", display: "flex", flexDirection: "column", alignItems: "center", gap: 28 }}>
        <Pop at={1.6} from={0.3} y={120}>
          <Img src={staticFile("skullcandy-crusher-anc-2.webp")} style={{ width: 400, height: 400, objectFit: "contain", background: C.crema, borderRadius: 36, padding: 24, boxSizing: "border-box", rotate: "-4deg", translate: `0px ${flote}px`, boxShadow: "0 30px 60px rgba(0,0,0,.5)" }} />
        </Pop>
        <Pop at={2.4}>
          <div style={{ fontFamily: ARCHIVO, fontWeight: 800, fontSize: 52, color: "#fff", background: C.rojo, padding: "14px 34px", borderRadius: 18, opacity: frame >= s(2.4) ? 1 : 0 }}>
            si los comprás en Mercado Libre
          </div>
        </Pop>
      </div>
    </AbsoluteFill>
  );
};

type Duelo = {
  img: string;
  nombre: string;
  ml: number;
  az: number;
  mlAt: [number, number];
  azAt: [number, number];
  gana: "ml" | "az";
  ganaAt: number;
  nota: string;
  subs: [number, string][];
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

const DueloEscena = (d: Duelo) => {
  const { frame } = useSec();
  const max = Math.max(d.ml, d.az);
  const ganaTxt = d.gana === "ml" ? "GANA\nMERCADO\nLIBRE" : "GANA\nAMAZON";
  return (
    <AbsoluteFill>
      <Columna top={220} gap={18}>
        <Pop at={0} from={0.5}>
          <Img src={staticFile(d.img)} style={{ width: 440, height: 440, objectFit: "contain", background: C.crema, borderRadius: 36, padding: 24, boxSizing: "border-box", translate: `0px ${Math.sin(frame / 14) * 7}px`, boxShadow: "0 30px 60px rgba(0,0,0,.5)" }} />
        </Pop>
        <Pop at={0.15}><Texto size={54} weight={800}>{d.nombre}</Texto></Pop>
        <Fila label="Mercado Libre" monto={d.ml} desde={d.mlAt[0]} hasta={d.mlAt[1]} max={max} gana={d.gana === "ml"} ganaAt={d.ganaAt} />
        <Fila label="Amazon (EE.UU.)" monto={d.az} desde={d.azAt[0]} hasta={d.azAt[1]} max={max} gana={d.gana === "az"} ganaAt={d.ganaAt} />
        <Pop at={d.ganaAt + 0.15}><Texto size={44} weight={800} color={C.verde}>{d.nota}</Texto></Pop>
      </Columna>
      <Sello text={ganaTxt} at={d.ganaAt} />
      <Subs partes={d.subs} />
      <div style={{ position: "absolute", top: 1480, width: "100%" }}>
        <Texto size={30} weight={600} color={C.crema2}>Precios del 01/11/2026 · Amazon: estimado con envío e impuestos</Texto>
      </div>
    </AbsoluteFill>
  );
};

const Giro = () => {
  const { frame } = useSec();
  const shake = frame < 10 ? Math.sin(frame * 2.6) * (10 - frame) * 2.4 : 0;
  return (
    <AbsoluteFill style={{ translate: `${shake}px 0px` }}>
      <Columna top={560} gap={30}>
        <Pop at={0} from={0.55} y={0}><Letra text="PERO OJO" max={190} color={C.rojo} sombra={false} style={{ textShadow: `.05em .05em 0 ${C.crema}` }} /></Pop>
        <Pop at={0.85}><Letra text="NO SIEMPRE" max={130} color={C.crema} /></Pop>
        <Pop at={1.3}><Letra text="GANA AMAZON" max={130} /></Pop>
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

const Regla = () => (
  <AbsoluteFill>
    <Columna top={330} gap={44}>
      <Pop at={0}><Letra text="LA REGLA" max={150} /></Pop>
      <Tarjeta at={0.85} desde={-1100} titulo="MENOS DE USD 100" sub="Comprá en Mercado Libre: el envío desde EE.UU. te mata." color={C.amarillo} />
      <Tarjeta at={3.45} desde={1100} titulo="MÁS DE USD 100" sub="Compará: Amazon manda gratis y puede salir mucho menos." color={C.verde} />
    </Columna>
  </AbsoluteFill>
);

const Cierre = () => {
  const { frame, s } = useSec();
  const n = Math.round(interpolate(frame, [s(0.5), s(1.25)], [0, 97], { ...clamp, easing: SALIDA }));
  const salto = frame >= s(3.2) ? Math.abs(Math.sin((frame - s(3.2)) / 5)) * -18 : 0;
  return (
    <AbsoluteFill>
      <Columna top={300} gap={10}>
        <Pop at={0}><Texto size={60} weight={800}>Comparamos</Texto></Pop>
        <div style={{ opacity: frame < s(0.45) ? 0 : 1, fontFamily: ULTRA, fontSize: 300, lineHeight: 1, color: C.amarillo, textShadow: `.04em .04em 0 ${C.rojo}, .07em .07em 0 #0b0a09` }}>{n}</div>
        <Pop at={1.2}><Texto size={72} weight={900}>productos</Texto><Texto size={56} weight={700} color={C.crema2}>con los precios de hoy</Texto></Pop>
        <Pop at={1.9} style={{ marginTop: 50 }}>
          <div style={{ fontFamily: ULTRA, fontSize: 66, color: "#fff", background: C.rojo, padding: "24px 46px", borderRadius: 22, boxShadow: `inset 0 0 0 5px ${C.rojo}, inset 0 0 0 9px ${C.crema}` }}>ofertas.knunet.com</div>
        </Pop>
        <Pop at={3.2} style={{ marginTop: 60, translate: `0px ${salto}px` }}>
          <Texto size={60} weight={900} color={C.amarillo}>☝ LINK EN LA BIO</Texto>
        </Pop>
      </Columna>
    </AbsoluteFill>
  );
};

// ---------- montaje ----------

const ESCENAS: { el: ReactNode; nombre: string }[] = [
  { nombre: "Gancho", el: <Gancho /> },
  {
    nombre: "Skullcandy",
    el: (
      <DueloEscena
        img="skullcandy-crusher-anc-2.webp"
        nombre="Skullcandy Crusher ANC 2"
        ml={869099}
        az={350000}
        mlAt={[1.3, 2.9]}
        azAt={[5.0, 6.3]}
        gana="az"
        ganaAt={6.5}
        nota="Te ahorrás ~$ 520.000"
        subs={[[0.05, "Skullcandy Crusher ANC 2"], [1.3, "$ 869.099 en Mercado Libre"], [3.9, "Traídos de Amazon…"], [5.0, "unos $ 350.000"]]}
      />
    ),
  },
  { nombre: "Giro", el: <Giro /> },
  {
    nombre: "GameSir",
    el: (
      <DueloEscena
        img="gamesir-g7-2.webp"
        nombre="Joystick GameSir G7 SE"
        ml={96952}
        az={170000}
        mlAt={[1.4, 2.8]}
        azAt={[4.7, 5.7]}
        gana="ml"
        ganaAt={6.45}
        nota="El envío se come la diferencia"
        subs={[[0.05, "Joystick GameSir G7 SE"], [1.4, "$ 96.952 en Mercado Libre"], [3.85, "De Amazon: $ 170.000"], [6.45, "El envío se come todo"]]}
      />
    ),
  },
  { nombre: "Regla", el: <Regla /> },
  { nombre: "Cierre", el: <Cierre /> },
];

const Musica = () => {
  const { durationInFrames } = useVideoConfig();
  return (
    <Audio
      src={staticFile("musica.mp3")}
      volume={(f) => interpolate(f, [0, 8, durationInFrames - 30, durationInFrames], [0, 0.13, 0.13, 0], clamp)}
    />
  );
};

export const Reel1 = () => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ backgroundColor: C.esmalte }}>
     <ConFuentes>
      <Fondo />
      {ESCENAS.map((e, i) => (
        <Sequence key={e.nombre} name={e.nombre} from={START[i]} durationInFrames={DUR[i]}>
          {e.el}
          <Audio src={staticFile(`f${i}.mp3`)} />
          {i > 0 && <Audio src="https://remotion.media/whoosh.wav" volume={0.35} />}
        </Sequence>
      ))}
      <Sequence name="Ding Amazon" from={START[1] + Math.round(6.5 * fps)} durationInFrames={fps}>
        <Audio src="https://remotion.media/ding.wav" volume={0.4} />
      </Sequence>
      <Sequence name="Ding ML" from={START[3] + Math.round(6.45 * fps)} durationInFrames={fps}>
        <Audio src="https://remotion.media/ding.wav" volume={0.4} />
      </Sequence>
      <Musica />
      <Marca />
     </ConFuentes>
    </AbsoluteFill>
  );
};
