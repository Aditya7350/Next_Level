// Full screen needs a click: browsers refuse to start it on their own. Call enterFullscreen() from a button handler.
export const fullscreenSupported = typeof document !== "undefined" && Boolean(document.documentElement.requestFullscreen);

export function isFullscreen() {
  return Boolean(document.fullscreenElement);
}

export async function enterFullscreen() {
  try {
    if (fullscreenSupported && !document.fullscreenElement) await document.documentElement.requestFullscreen();
  } catch {
    // Refused (older browser, embedded frame): the interview carries on in a normal window.
  }
}

export async function exitFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
  } catch {
    // ignore
  }
}