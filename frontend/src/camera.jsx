// The camera: opening it, taking frames for the backend, and drawing what the backend said about them.
import React, { useEffect, useRef, useState } from "react";
import { CameraOff, Loader2, RefreshCw, SwitchCamera } from "lucide-react";
import { titleCase } from "./lib/format";

export function useCamera(active, initialFacing = "environment") {
  const videoRef = useRef(null);
  const [facing, setFacing] = useState(initialFacing);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setReady(false);
    if (!active) return;
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(window.isSecureContext ? "This browser does not support camera access." : "The camera only works over HTTPS. Start the frontend with `npm run dev:https` and open the https:// link.");
      return;
    }
    let stream = null;
    let cancelled = false;
    navigator.mediaDevices.getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
      .then(result => {
        if (cancelled) { result.getTracks().forEach(track => track.stop()); return; }
        stream = result;
        // A camera that is unplugged or taken by another app ends its track; say so instead of freezing.
        result.getVideoTracks().forEach(track => { track.onended = () => { if (!cancelled) { setReady(false); setError("The camera stopped. Check that it is connected and not in use by another app, then try again."); } }; });
        if (videoRef.current) videoRef.current.srcObject = result;
      })
      .catch(err => setError(err.name === "NotAllowedError" ? "Camera permission denied. Allow camera access for this site and try again." : err.name === "NotFoundError" ? "No camera was found on this device." : err.message || "Unable to open the camera."));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach(track => track.stop());
    };
  }, [active, facing, attempt]);
  // Frames are downscaled before upload: faces stay large enough to recognize and requests stay small.
  // Enrollment and the scanner use the same size, so a face reaches the model at the same scale in both.
  const capture = (maxWidth = 960) => new Promise(resolve => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) { resolve(null); return; }
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(blob => resolve(blob ? { blob, width: canvas.width, height: canvas.height } : null), "image/jpeg", 0.8);
  });
  const flip = () => setFacing(current => current === "environment" ? "user" : "environment");
  const retry = () => setAttempt(current => current + 1);
  return { videoRef, error, capture, flip, retry, facing, ready, setReady };
}

// Why the scanner could not judge a face at all.
const SCAN_LABELS = { too_far: "Too far", low_light: "Too dark", too_bright: "Too bright", blurry: "Blurry", unclear: "Unclear" };

// What the scanner decided about one face, in words. Every face in the frame gets its own verdict
// from the backend (`face.result`); nothing here decides anything. `identity` and `liveness` say what
// that verdict implies about the two checks, and "–" where the answer does not tell.
export function faceVerdict(face) {
  const name = face.person_name;
  switch (face.result) {
    case "verified": return { tone: "success", name, label: `Marked ${titleCase(face.attendance_status)}`, identity: "Verified", liveness: "Passed" };
    case "already_marked": return { tone: "success", name, label: `Already marked${face.attendance_status ? ` ${titleCase(face.attendance_status)}` : ""}`, identity: "Matched", liveness: "Not rechecked" };
    case "recognized": return { tone: "info", name, label: "Recognized, nothing marked", identity: "Matched", liveness: "–" };
    case "pending": return { tone: "warning", name, label: `Verifying ${face.confirm_hits}/${face.confirm_needed}`, identity: "Matched", liveness: "Passed" };
    // The backend asks each face for its own movement, in a direction it picked at random.
    case "challenge": return face.challenge?.action === "turn"
      ? { tone: "info", name, label: `Turn head to YOUR ${String(face.challenge.direction || "").toUpperCase()}`, identity: "Matched", liveness: "Passed", ask: true }
      : { tone: "info", name, label: "Look straight", identity: "Matched", liveness: "Passed", ask: true };
    case "challenge_failed": return { tone: "danger", name, label: "Wrong movement, wait", identity: "Matched", liveness: "Passed" };
    case "locked": return { tone: "danger", name, label: "Locked, mark by hand", identity: "Matched", liveness: "–" };
    case "liveness_uncertain": return { tone: "neutral", name: "Cannot verify", label: "Cannot confirm a real face", identity: "–", liveness: "Uncertain" };
    case "not_marked": return { tone: "warning", name, label: "Not marked", identity: "Matched", liveness: "Passed", note: face.message };
    case "ambiguous": return { tone: "danger", name: "Cannot verify", label: "Unable to verify identity", identity: "Ambiguous", liveness: "–" };
    case "liveness_failed": return { tone: "danger", name: "Rejected", label: "Photo or screen detected", identity: "–", liveness: "Failed" };
    case "low_quality": return { tone: "neutral", name: "Cannot verify", label: SCAN_LABELS[face.status] || "Unclear", identity: "Not checked", liveness: "Not checked" };
    default: return { tone: "danger", name: "Unknown person", label: "Not verified", identity: "No match", liveness: "–" };
  }
}

const BOX = {
  success: { border: "border-emerald-400", chip: "bg-emerald-500" },
  warning: { border: "border-amber-400", chip: "bg-amber-500" },
  info: { border: "border-sky-400", chip: "bg-sky-600" },
  danger: { border: "border-red-400", chip: "bg-red-500" },
  neutral: { border: "border-slate-300", chip: "bg-slate-600" }
};

// guide: draw the oval the face should sit in. mirror: show the front camera like a mirror
// (the preview only; uploaded frames are never flipped).
export function CameraView({ camera, faces = [], frame, guide = false, mirror = false, children }) {
  const percent = (value, total) => `${(value / total) * 100}%`;
  return <div className="relative grid min-h-[15rem] place-items-center overflow-hidden rounded-3xl bg-ink">
    <div className="relative inline-block max-w-full">
      <video ref={camera.videoRef} className={`block max-h-[68vh] min-h-48 max-w-full transition-opacity duration-300 ${camera.ready ? "opacity-100" : "opacity-0"}`} style={mirror && camera.facing === "user" ? { transform: "scaleX(-1)" } : undefined} onLoadedData={() => camera.setReady(true)} autoPlay playsInline muted />
      {guide && camera.ready && <div className="pointer-events-none absolute inset-0 grid place-items-center overflow-hidden" aria-hidden="true">
        <div className="h-[78%] w-[36%] rounded-[50%] border-2 border-dashed border-white/80 shadow-[0_0_0_100vmax_rgba(14,17,22,.45)]" />
      </div>}
      {frame && faces.map((face, index) => {
        // Keyed by the backend's track, not by position in the list, so a box and its label stay
        // with the same face while people move and the order of the list changes.
        const verdict = faceVerdict(face);
        const style = BOX[verdict.tone];
        return <div key={face.track_id ?? index} className={`absolute rounded-xl border-2 transition-all duration-150 ease-linear ${style.border}`} style={{ left: percent(face.box.x, frame.width), top: percent(face.box.y, frame.height), width: percent(face.box.w, frame.width), height: percent(face.box.h, frame.height) }}>
          <span className={`absolute left-0 top-full mt-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold text-white shadow ${style.chip}`}>{verdict.name ? `${verdict.name}: ` : ""}{verdict.label}</span>
        </div>;
      })}
    </div>
    {children}
    {!camera.ready && !camera.error && <div className="absolute inset-0 grid place-items-center text-center text-white">
      <div role="status"><Loader2 className="mx-auto animate-spin text-brand-200" size={28} aria-hidden="true" /><p className="mt-3 text-sm font-medium text-white/80">Starting camera…</p><p className="mt-1 text-xs text-white/50">Allow camera access if your browser asks.</p></div>
    </div>}
    {camera.error && <div className="absolute inset-0 grid place-items-center bg-ink p-6 text-center">
      <div role="alert" className="max-w-sm">
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-white/10 text-red-300"><CameraOff size={22} aria-hidden="true" /></div>
        <p className="mt-4 font-semibold text-white">Camera unavailable</p>
        <p className="mt-1 text-sm text-white/70">{camera.error}</p>
        <button type="button" className="btn btn-sm mt-4 bg-white text-ink hover:bg-slate-100" onClick={camera.retry}><RefreshCw size={15} aria-hidden="true" />Try again</button>
      </div>
    </div>}
    {!camera.error && <button type="button" className="absolute right-3 top-3 grid h-10 w-10 place-items-center rounded-full bg-white/90 text-ink shadow transition duration-150 hover:bg-white active:scale-95" onClick={camera.flip} aria-label="Switch camera" title="Switch camera"><SwitchCamera size={18} aria-hidden="true" /></button>}
  </div>;
}

export function CameraPlaceholder({ icon: Icon, title, message }) {
  return <div className="grid aspect-video min-h-[15rem] w-full place-items-center rounded-3xl bg-ink p-6 text-center text-white">
    <div className="max-w-sm">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-white/10 text-brand-200"><Icon size={26} aria-hidden="true" /></div>
      <p className="mt-4 font-semibold">{title}</p>
      {message && <p className="mt-1 text-sm text-white/60">{message}</p>}
    </div>
  </div>;
}
