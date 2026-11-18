// Historia de IG/FB (9:16, 10 s): gancho, producto, duelo ML vs Amazon y llamado al sticker de enlace.
// Sin precios a propósito: las historias se programan el lunes para toda la semana y el precio del día está en el sitio.
import { Audio } from "@remotion/media";
import { loadFont } from "@remotion/fonts";
import { fitText } from "@remotion/layout-utils";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { AbsoluteFill, continueRender, delayRender, Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

export const FPS_HISTORIA = 30;
export const FRAMES_HISTORIA = 10 * FPS_HISTORIA;
export type HistoriaProps = { img: string; nombre: string };

const C = { esmalte: "#141210", crema: "#f4efe4", rojo: "#d7262b", amarillo: "#f2c230", celeste: "#6ec6f0", naranja: "#ff9900" };
const ULTRA = "Ultra";
const ARCHIVO = "Archivo";
const W = 900;
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const SALIDA = Easing.bezier(0.23, 1, 0.32, 1);

const fuentes = Promise.all([
  loadFont({ family: ULTRA, url: staticFile("ultra.woff2") }),
  loadFont({ family: ARCHIVO, url: staticFile("archivo.woff2"), weight: "100 900" }),
]);
const ConFuentes = ({ children }: { children: ReactNode }) => {
  const [listo, setListo] = useState(false);
  const [h] = useState(() => delayRender("fuentes"));
  useEffect(() => { fuentes.then(() => { setListo(true); continueRender(h); }); }, [h]);
  return listo ? <>{children}</> : null;
};

const useSec = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return { frame, fps, s: (sec: number) => Math.round(sec * fps) };
};

const Pop = ({ at, children, from = 0.6, y = 40, style }: { at: number; children: ReactNode; from?: number; y?: number; style?: CSSProperties }) => {
  const { frame, fps, s } = useSec();
  const p = spring({ frame: frame - s(at), fps, config: { damping: 13, stiffness: 190, mass: 0.7 } });
  return (
    <div style={{ opacity: at <= 0.05 ? 1 : interpolate(p, [0, 0.4], [0, 1], clamp), scale: String(Math.min(1, interpolate(p, [0, 1], [from, 1]))), translate: `0px ${interpolate(p, [0, 1], [y, 0])}px`, ...style }}>
      {children}
    </div>
  );
};

const Letra = ({ text, max, color = C.amarillo, width = W }: { text: string; max: number; color?: string; width?: number }) => {
  const fs = Math.min(max, fitText({ text, withinWidth: width, fontFamily: ULTRA }).fontSize * 0.96);
  return <div style={{ fontFamily: ULTRA, fontSize: fs, lineHeight: 1.04, color, whiteSpace: "nowrap", textAlign: "center", textShadow: `.05em .05em 0 ${C.rojo}, .09em .09em 0 #0b0a09` }}>{text}</div>;
};

const Fondo = () => {
  const frame = useCurrentFrame();
  const a = frame / 60;
  return (
    <AbsoluteFill style={{
      backgroundColor: C.esmalte,
      backgroundImage: [
        `radial-gradient(900px 800px at ${50 + Math.sin(a) * 20}% ${42 + Math.cos(a * 0.8) * 8}%, rgba(215,38,43,.28), transparent 70%)`,
        `radial-gradient(800px 800px at ${50 - Math.cos(a * 0.7) * 24}% ${80 + Math.sin(a) * 6}%, rgba(242,194,48,.16), transparent 70%)`,
        "repeating-linear-gradient(0deg, rgba(255,255,255,.025) 0 2px, transparent 2px 6px)",
      ].join(","),
    }} />
  );
};

/** Dos tiendas que se alternan el «foco» como un duelo, con VS en el medio. */
const Duelo = () => {
  const { frame, s } = useSec();
  const t = Math.max(0, frame - s(3.0));
  const turno = Math.floor(t / 9) % 2; // cambia cada 0,3 s
  const fin = frame >= s(5.6);
  const tienda = (txt: string, color: string, activa: boolean) => (
    <div style={{
      fontFamily: ARCHIVO, fontWeight: 900, fontSize: 50, color: activa ? C.esmalte : color,
      background: activa ? color : "rgba(11,10,9,.6)", border: `5px solid ${color}`, borderRadius: 22,
      padding: "16px 26px", scale: activa ? "1.08" : "0.94", transition: "none", whiteSpace: "nowrap",
    }}>{txt}</div>
  );
  return (
    <Pop at={3.0} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 30 }}>
      {tienda("Mercado Libre", C.amarillo, fin || turno === 0)}
      <div style={{ fontFamily: ULTRA, fontSize: 64, color: C.crema }}>vs</div>
      {tienda("Amazon", C.naranja, fin || turno === 1)}
    </Pop>
  );
};

// 17/11: las historias salen por la API de Meta, que no pone sticker de enlace: el link va escrito en pantalla.
export const SITIO_VISIBLE = "ofertas.knunet.com";

const Llamado = () => (
  <div style={{ position: "absolute", top: 1300, width: "100%", display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
    <Pop at={6.2} from={0.4} y={60}>
      <div style={{ fontFamily: ARCHIVO, fontWeight: 900, fontSize: 54, color: C.crema, textAlign: "center" }}>
        Mirá el precio de hoy en
      </div>
    </Pop>
    <Pop at={6.5} from={0.4} y={40}>
      <div style={{ fontFamily: ULTRA, fontSize: 74, color: "#fff", background: C.rojo, padding: "18px 44px", borderRadius: 24, boxShadow: "0 14px 30px rgba(0,0,0,.45)" }}>
        {SITIO_VISIBLE}
      </div>
    </Pop>
  </div>
);

// El sitio queda escrito durante toda la historia (debajo de la barra de progreso de Instagram).
const SitioArriba = () => (
  <div style={{ position: "absolute", top: 150, width: "100%", textAlign: "center", fontFamily: ARCHIVO, fontWeight: 900, fontSize: 40, color: C.crema, letterSpacing: 1, textShadow: "0 3px 10px rgba(0,0,0,.6)" }}>
    {SITIO_VISIBLE}
  </div>
);

export const Historia = ({ img, nombre }: HistoriaProps) => {
  const { frame, s, fps } = useSec();
  const { durationInFrames } = useVideoConfig();
  const flote = Math.sin(frame / 14) * 10;
  const zoom = interpolate(frame, [s(0.7), durationInFrames], [1, 1.08], clamp);
  const sale = interpolate(frame, [s(2.6), s(3.0)], [1, 0.94], { ...clamp, easing: SALIDA });
  const sube = interpolate(frame, [s(2.6), s(3.0)], [0, -30], { ...clamp, easing: SALIDA });
  const pregunta = spring({ frame: frame - s(4.4), fps, config: { damping: 12, stiffness: 160 } });
  return (
    <ConFuentes>
      <AbsoluteFill>
        <Fondo />
        <Audio src={staticFile("musica.mp3")} volume={(f) => interpolate(f, [0, 8, durationInFrames - 20, durationInFrames], [0, 0.9, 0.9, 0], clamp)} />
        <div style={{ position: "absolute", top: 250, left: (1080 - W) / 2, width: W, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
          <Pop at={0}><Letra text="¿Amazon o" max={150} /></Pop>
          <Pop at={0.3}><Letra text="Mercado Libre?" max={150} /></Pop>
        </div>
        <div style={{ position: "absolute", top: 500, width: "100%", display: "flex", justifyContent: "center", translate: `0px ${sube}px`, scale: String(sale) }}>
          <Pop at={0.6} from={0.3} y={160}>
            <Img src={staticFile(img)} style={{ width: 940, height: 720, objectFit: "contain", rotate: "-3deg", translate: `0px ${flote}px`, scale: String(zoom), filter: "drop-shadow(0 34px 34px rgba(0,0,0,.55))" }} />
          </Pop>
        </div>
        <div style={{ position: "absolute", top: 1190, left: 70, right: 90, display: "flex", flexDirection: "column", alignItems: "center", gap: 26 }}>
          {frame < s(3.0) ? (
            <Pop at={1.5}>
              <div style={{ fontFamily: ARCHIVO, fontWeight: 800, fontSize: 58, color: C.crema, textAlign: "center", lineHeight: 1.15 }}>{nombre}</div>
            </Pop>
          ) : (
            <Duelo />
          )}
        </div>
        {frame >= s(4.4) && frame < s(6.2) && (
          <div style={{ position: "absolute", top: 1330, width: "100%", textAlign: "center", fontFamily: ARCHIVO, fontWeight: 800, fontSize: 56, color: C.crema, opacity: Math.min(1, pregunta * 2), scale: String(0.8 + pregunta * 0.2) }}>
            ¿Cuál te sale menos <span style={{ color: C.amarillo }}>hoy</span>?
          </div>
        )}
        <SitioArriba />
        <Llamado />
      </AbsoluteFill>
    </ConFuentes>
  );
};
