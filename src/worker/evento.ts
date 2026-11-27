import type { Env, WorkerContext } from "./types";

export interface EventoInput {
  event: "PageView" | "ClickAfiliado";
  event_id: string;
  url: string;
  fbc?: string;
  data?: {
    tienda?: "amazon" | "ml";
    slug?: string;
    categoria?: string;
    ubicacion?: string;
    boton?: string;
    precio_usd?: number;
    ahorro_pct?: number;
  };
}

const FBC = /^fb\.1\.\d{10,13}\.[A-Za-z0-9_-]{10,500}$/;
let warnedMissing = false;

function parseInput(raw: unknown): EventoInput | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (value.event !== "PageView" && value.event !== "ClickAfiliado") return null;
  if (typeof value.event_id !== "string" || !/^[A-Za-z0-9_-]{8,64}$/.test(value.event_id)) return null;
  if (typeof value.url !== "string") return null;
  try {
    const url = new URL(value.url);
    if (url.protocol !== "https:" || url.hostname !== "ofertas.knunet.com") return null;
  } catch { return null; }
  const data: NonNullable<EventoInput["data"]> = {};
  if (value.data && typeof value.data === "object") {
    const source = value.data as Record<string, unknown>;
    if (source.tienda === "amazon" || source.tienda === "ml") data.tienda = source.tienda;
    for (const key of ["slug", "categoria", "ubicacion", "boton"] as const) {
      if (typeof source[key] === "string") data[key] = source[key].trim().slice(0, 100);
    }
    for (const key of ["precio_usd", "ahorro_pct"] as const) {
      if (typeof source[key] === "number" && Number.isFinite(source[key])) data[key] = source[key];
    }
  }
  return {
    event: value.event, event_id: value.event_id, url: value.url,
    ...(typeof value.fbc === "string" && FBC.test(value.fbc) ? { fbc: value.fbc } : {}),
    ...(value.data ? { data } : {}),
  };
}

/** Arma los eventos sin acceder a la red, al reloj ni a secretos. */
export function buildCapiEvents(input: EventoInput, headers: Headers, nowSec: number) {
  const ip = headers.get("CF-Connecting-IP");
  const ua = headers.get("User-Agent");
  const common = {
    event_time: nowSec, action_source: "website", event_source_url: input.url,
    user_data: {
      ...(ip ? { client_ip_address: ip } : {}),
      ...(ua ? { client_user_agent: ua } : {}),
      ...(input.fbc && FBC.test(input.fbc) ? { fbc: input.fbc } : {}),
    },
  };
  if (input.event === "PageView") return [{ ...common, event_name: "PageView", event_id: input.event_id }];
  const data = input.data ?? {};
  return [
    { ...common, event_name: "ClickAfiliado", event_id: input.event_id, custom_data: data },
    { ...common, event_name: "InitiateCheckout", event_id: `${input.event_id}-ic`, custom_data: {
      ...(data.slug !== undefined ? { content_ids: [data.slug] } : {}),
      content_type: "product", currency: "USD",
      ...(data.categoria !== undefined ? { content_category: data.categoria } : {}),
      ...(typeof data.precio_usd === "number" && Number.isFinite(data.precio_usd) ? { value: data.precio_usd } : {}),
    } },
  ];
}

async function forwardEvents(input: EventoInput, headers: Headers, env: Env): Promise<void> {
  try {
    const response = await fetch(`https://graph.facebook.com/v23.0/${env.META_PIXEL_ID}/events`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ access_token: env.META_CAPI_TOKEN, data: buildCapiEvents(input, headers, Math.floor(Date.now() / 1000)) }),
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) console.warn(`[evento] Meta HTTP ${response.status}`);
  } catch {
    // Nunca registrar la excepción: puede contener credenciales o cuerpos de respuesta.
    console.warn("[evento] Meta HTTP error");
  }
}

export async function handleEvento(request: Request, env: Env, ctx: WorkerContext): Promise<Response> {
  const origin = request.headers.get("Origin");
  if (origin !== null && origin !== "https://ofertas.knunet.com") return new Response(null, { status: 403 });
  if (Number(request.headers.get("Content-Length")) > 4096) return new Response(null, { status: 413 });
  let raw: unknown;
  try {
    // Se limita el cuerpo real, incluso si falta Content-Length o el pedido llega por partes.
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 4096) {
          void reader.cancel().catch(() => {});
          return new Response(null, { status: 413 });
        }
        chunks.push(value);
      }
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    raw = JSON.parse(new TextDecoder().decode(bytes));
  } catch { return new Response(null, { status: 400 }); }
  const input = parseInput(raw);
  if (!input) return new Response(null, { status: 400 });
  if (!env.META_CAPI_TOKEN || !env.META_PIXEL_ID) {
    if (!warnedMissing) { console.warn("[evento] Meta no configurado"); warnedMissing = true; }
  } else {
    ctx.waitUntil(forwardEvents(input, request.headers, env));
  }
  return new Response(null, { status: 204 });
}
