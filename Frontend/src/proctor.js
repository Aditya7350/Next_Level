// Camera checks during an interview: sends a small still image every few seconds, reports tab switches,
// and returns the warning to show. It fails open: if the backend has no proctoring routes, or can't run the
// models, it quietly stops and the interview carries on.
import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { PROCTORING_ENABLED, PROCTOR_FRAME_INTERVAL_MS } from "./config.js";

const NOTICE_MS = 12000;   // how long a warning stays up once the candidate can see it
const MAX_WIDTH = 640;     // frames are shrunk to this width before sending (about 50 KB each)

export function useProctoring({ interviewId, videoRef, active }) {
  const [notice, setNotice] = useState(null); // { message, used, max }
  const [status, setStatus] = useState({ on: false });
  const dismissTimer = useRef(0);
  const noticeShown = useRef(false);

  useEffect(() => {
    if (!PROCTORING_ENABLED || !active) return undefined;

    let stopped = false;
    let busy = false;
    let missingVideoTicks = 0;
    const canvas = document.createElement("canvas");

    // Start the countdown only when the candidate is looking at the page, so a warning that arrives while
    // they are on another tab is still there when they come back.
    const scheduleDismiss = () => {
      window.clearTimeout(dismissTimer.current);
      dismissTimer.current = window.setTimeout(() => {
        noticeShown.current = false;
        setNotice(null);
      }, NOTICE_MS);
    };

    const handle = (res) => {
      if (!res) return;
      if (res.status === "unavailable") {
        stopped = true;
        setStatus({ on: false });
        return;
      }
      if (res.status !== "ok") return;
      setStatus({ on: true });
      if (res.warning) {
        noticeShown.current = true;
        setNotice({ message: res.warning, used: res.warnings_used, max: res.warnings_max });
        if (!document.hidden) scheduleDismiss();
      }
    };

    // 404/405/501: this backend has no proctoring routes. Stop trying.
    const fail = (err) => {
      if (err && [404, 405, 501].includes(err.status)) {
        stopped = true;
        setStatus({ on: false });
      }
    };

    async function tick() {
      if (stopped || busy || document.hidden) return;
      const video = videoRef.current;
      if (!video || video.readyState < 2 || !video.videoWidth) {
        missingVideoTicks += 1;
        if (missingVideoTicks === 3) {
          busy = true;
          try {
            handle(await api.sendProctorEvent(interviewId, "camera_unavailable"));
          } catch (err) {
            fail(err);
          } finally {
            busy = false;
          }
        }
        return;
      }
      missingVideoTicks = 0;
      busy = true;
      try {
        const scale = Math.min(1, MAX_WIDTH / video.videoWidth);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.7));
        if (blob) handle(await api.sendFrame(interviewId, blob));
      } catch (err) {
        fail(err);
      } finally {
        busy = false;
      }
    }

    const onVisibility = async () => {
      if (stopped) return;
      if (document.hidden) {
        try {
          handle(await api.sendProctorEvent(interviewId, "tab_hidden"));
        } catch (err) {
          fail(err);
        }
      } else if (noticeShown.current) {
        scheduleDismiss();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    const first = window.setTimeout(tick, 1500);
    const timer = window.setInterval(tick, PROCTOR_FRAME_INTERVAL_MS);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearTimeout(first);
      window.clearInterval(timer);
      window.clearTimeout(dismissTimer.current);
    };
  }, [interviewId, videoRef, active]);

  return {
    notice,
    status,
    dismiss: () => {
      window.clearTimeout(dismissTimer.current);
      noticeShown.current = false;
      setNotice(null);
    },
  };
}