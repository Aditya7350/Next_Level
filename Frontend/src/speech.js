// Browser speech: recognition (candidate voice -> text) and synthesis (Aria's voice).
// Recognition works in Chrome and Edge (and Safari, partly). Elsewhere the room falls back to typing.
import { useCallback, useEffect, useRef, useState } from "react";

const Recognition =
  typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

export const speechInputSupported = Boolean(Recognition);
export const speechOutputSupported = typeof window !== "undefined" && "speechSynthesis" in window;

/** Continuous dictation. onFinal(text) is called for each finished phrase. */
export function useListener({ onFinal }) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const recRef = useRef(null);
  const wantRef = useRef(false);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  const stop = useCallback(() => {
    wantRef.current = false;
    const rec = recRef.current;
    recRef.current = null;
    if (rec) {
      rec.onend = null;
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    }
    setListening(false);
    setInterim("");
  }, []);

  const start = useCallback(() => {
    if (!Recognition || wantRef.current) return;
    wantRef.current = true;
    setError("");

    const launch = () => {
      const rec = new Recognition();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (e) => {
        let partial = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const result = e.results[i];
          if (result.isFinal) {
            const text = result[0].transcript.trim();
            if (text) onFinalRef.current(text);
          } else {
            partial += result[0].transcript;
          }
        }
        setInterim(partial);
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          setError("Microphone access is blocked. You can type your answer instead.");
          wantRef.current = false;
          setListening(false);
        } else if (e.error === "network") {
          setError("Speech recognition lost its connection. You can type your answer instead.");
          wantRef.current = false;
          setListening(false);
        }
      };
      // Chrome ends a session after a pause in speech; restart while the candidate is still answering.
      rec.onend = () => {
        if (wantRef.current) {
          try {
            launch();
          } catch {
            wantRef.current = false;
            setListening(false);
          }
        } else {
          setListening(false);
        }
      };
      recRef.current = rec;
      try {
        rec.start();
        setListening(true);
      } catch {
        wantRef.current = false;
        setListening(false);
      }
    };
    launch();
  }, []);

  useEffect(() => stop, [stop]);

  return { listening, interim, error, start, stop, supported: speechInputSupported };
}

/** Speak text aloud. Returns a cancel function. onEnd fires when finished (or immediately if unsupported). */
export function speak(text, { onEnd } = {}) {
  if (!speechOutputSupported) {
    if (onEnd) setTimeout(onEnd, 0);
    return () => {};
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    if (onEnd) onEnd();
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  window.speechSynthesis.speak(utterance);
  return () => {
    done = true;
    window.speechSynthesis.cancel();
  };
}
