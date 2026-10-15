// Whether the person on camera is looking at this screen, so the preview should behave like a mirror:
// a front camera, or a webcam (which says nothing about its direction and faces whoever sits at the
// computer). A phone's rear camera pointed at a class says "environment" and is shown as it is.
// opened: the facingMode the opened camera reports ("" when it says nothing); asked: the one asked for.
export function facesThePerson(opened, asked, touchScreen = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches) {
  if (opened) return opened === "user";
  return asked === "user" || !touchScreen;
}
