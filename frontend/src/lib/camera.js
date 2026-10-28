// Whether the person on camera is looking at this screen, so the preview should behave like a mirror:
// a front camera, or a webcam (which says nothing about its direction and faces whoever sits at the
// computer). A phone's rear camera pointed at a class says "environment" and is shown as it is.
// opened: the facingMode the opened camera reports ("" when it says nothing); asked: the one asked for.
export function facesThePerson(opened, asked, touchScreen = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches) {
  if (opened) return opened === "user";
  return asked === "user" || !touchScreen;
}

// The backend answers 503 models_unavailable when its face models are not loaded: no frame can be
// checked until the server is fixed, so the pages stop or wait and say so instead of blaming the face.
const MODELS_NOT_LOADED = "The face models are not loaded on the server, so no frame could be checked. This is not a problem with the face, the light or the camera.";
export const MODELS_UNAVAILABLE_TEXT = {
  enrollment: `${MODELS_NOT_LOADED} Nothing was saved. Ask whoever runs the server to check it (GET /health), then start the enrollment again.`,
  scanner: `${MODELS_NOT_LOADED} Nobody is being marked. Ask whoever runs the server to check it (GET /health); scanning resumes by itself once it works.`
};

export function modelsUnavailable(error) {
  const payload = error?.payload || {};
  return payload.quality_status === "models_unavailable" || payload.status === "models_unavailable";
}

// Which side of the screen the head-turn arrow points to. The backend asks for a turn to the person's
// OWN left or right. On a mirrored preview (the camera faces the person) their own left is on the
// screen's left; on a preview shown as the camera sees it (a rear camera pointed at a class) it is on
// the screen's right. The arrow only shows the way: the backend alone decides whether the turn counted.
export function turnArrow(direction, mirrored) {
  if (direction !== "left" && direction !== "right") return null;
  if (mirrored) return direction;
  return direction === "left" ? "right" : "left";
}
