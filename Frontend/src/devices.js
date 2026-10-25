// Camera and microphone access, with an optional live microphone level for the setup check.
import { useEffect, useState } from "react";

export function useDevices({ audio = false } = {}) {
  const [stream, setStream] = useState(null);
  const [camera, setCamera] = useState("pending"); // pending | ok | denied
  const [mic, setMic] = useState(audio ? "pending" : "off");
  const [level, setLevel] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let active = null;
    let ctx = null;
    let timer = 0;

    const get = async (constraints) => {
      try {
        return await navigator.mediaDevices.getUserMedia(constraints);
      } catch {
        return null;
      }
    };

    (async () => {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setCamera("denied");
        if (audio) setMic("denied");
        return;
      }
      let media = await get({ video: true, audio });
      if (!media && audio) {
        // One of the two may be refused or missing: try each on its own.
        const v = await get({ video: true });
        const a = await get({ audio: true });
        const tracks = [...(v ? v.getTracks() : []), ...(a ? a.getTracks() : [])];
        media = tracks.length ? new MediaStream(tracks) : null;
      }
      if (cancelled) {
        if (media) media.getTracks().forEach((t) => t.stop());
        return;
      }
      active = media;
      setStream(media);
      setCamera(media && media.getVideoTracks().length ? "ok" : "denied");
      if (audio) setMic(media && media.getAudioTracks().length ? "ok" : "denied");

      if (audio && media && media.getAudioTracks().length) {
        try {
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          ctx = new AudioCtx();
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 512;
          ctx.createMediaStreamSource(new MediaStream(media.getAudioTracks())).connect(analyser);
          const data = new Uint8Array(analyser.fftSize);
          timer = window.setInterval(() => {
            analyser.getByteTimeDomainData(data);
            let sum = 0;
            for (let i = 0; i < data.length; i++) {
              const v = (data[i] - 128) / 128;
              sum += v * v;
            }
            setLevel(Math.min(1, Math.sqrt(sum / data.length) * 4));
          }, 80);
        } catch {
          /* no level meter, the mic still works */
        }
      }
    })();

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      if (ctx) ctx.close().catch(() => {});
      if (active) active.getTracks().forEach((t) => t.stop());
    };
  }, [audio]);

  return { stream, camera, mic, level };
}
