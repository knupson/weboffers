import { expect, it, vi } from "vitest";
import { enableNativeShare, shareLinks } from "./share";

it("codifica título y URL para WhatsApp y X sin perder acentos ni símbolos", () => {
  const title = "Qué conviene: SSD & RAM";
  const url = "https://ofertas.knunet.com/guias/ssd/?a=1&b=2";
  const links = shareLinks(title, url);
  expect(new URL(links.whatsapp).searchParams.get("text")).toBe(`${title} ${url}`);
  expect(new URL(links.x).searchParams.get("text")).toBe(title);
  expect(new URL(links.x).searchParams.get("url")).toBe(url);
});
it("deja oculto el botón sin soporte nativo", () => {
  const root = { querySelectorAll: vi.fn() };
  enableNativeShare(root as any, {} as any);
  expect(root.querySelectorAll).not.toHaveBeenCalled();
});
it("habilita el botón, comparte y tolera cancelar el diálogo", async () => {
  let click: () => Promise<void>;
  const button = { hidden: true, dataset: { title: "SSD", url: "https://ofertas.knunet.com/productos/ssd/" },
    addEventListener: (_: string, cb: typeof click) => { click = cb; } };
  const share = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("cancelado"));
  enableNativeShare({ querySelectorAll: () => [button] } as any, { share });
  expect(button.hidden).toBe(false);
  await click!();
  expect(share).toHaveBeenCalledWith(button.dataset);
  await expect(click!()).resolves.toBeUndefined();
});
