export function shareLinks(title: string, url: string) {
  return {
    whatsapp: `https://wa.me/?${new URLSearchParams({ text: `${title} ${url}` })}`,
    x: `https://twitter.com/intent/tweet?${new URLSearchParams({ text: title, url })}`,
  };
}

export function enableNativeShare(root: ParentNode, navigator: Pick<Navigator, "share">) {
  if (typeof navigator.share !== "function") return;
  root.querySelectorAll<HTMLButtonElement>("[data-native-share]").forEach((button) => {
    button.hidden = false;
    button.addEventListener("click", async () => {
      try { await navigator.share({ title: button.dataset.title, url: button.dataset.url }); }
      catch { /* Cancelar el diálogo conserva la página actual. */ }
    });
  });
}
