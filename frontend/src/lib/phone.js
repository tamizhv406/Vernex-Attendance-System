// Contact numbers: the same rules and the same messages as the backend
// (backend/app/utils/validation.py, normalize_phone). Both are checked against
// backend/tests/data/phone_cases.json, so the form never accepts what the API refuses.

export const PHONE_DIGITS = 10;
const COUNTRY_CODE = "91";
// Space, tab, line break and the non-breaking space that comes along with copied text.
const SPACES = /[ \t\r\n ]/g;

function lengthMessage(found, digits = "") {
  const message = `Phone number must have exactly ${PHONE_DIGITS} digits (found ${found})`;
  // Twelve digits starting with 91 is almost certainly a country code without its "+". It is still
  // refused: guessing which two digits to drop is how a wrong number gets stored.
  return found === PHONE_DIGITS + COUNTRY_CODE.length && digits.startsWith(COUNTRY_CODE) ? `${message}. To include the country code, write it as +91` : message;
}

// { value: "9876543210" } for a number that is accepted, { error: "why not" } for one that is not.
// Accepted: ten digits, optionally grouped with spaces or hyphens, optionally with +91 in front.
export function checkPhone(input) {
  const text = String(input ?? "").replace(SPACES, " ").replace(/^ +| +$/g, "");
  if (!text) return { error: "Enter a phone number" };
  const hasCountryCode = text.startsWith("+");
  const body = hasCountryCode ? text.slice(1) : text;
  if (body.includes("+")) return { error: "A + is only allowed at the start, as +91" };
  if (/[^0-9 -]/.test(body)) return { error: "Phone number can only contain digits, spaces and hyphens, with an optional +91 in front" };
  const digits = body.replace(/[ -]/g, "");
  if (!digits) return { error: lengthMessage(0) };
  if (hasCountryCode && !/^[0-9]/.test(body)) return { error: "Write the country code as +91, with nothing between + and 91" };
  if (!/^[0-9](?:[ -]*[0-9])*$/.test(body)) return { error: "Spaces and hyphens are only allowed between digits" };
  if (hasCountryCode) {
    if (!digits.startsWith(COUNTRY_CODE)) return { error: "Only the +91 country code is supported" };
    const national = digits.slice(COUNTRY_CODE.length);
    if (national.length !== PHONE_DIGITS) return { error: `Phone number must have exactly ${PHONE_DIGITS} digits after +91 (found ${national.length})` };
    return { value: national };
  }
  if (digits.length !== PHONE_DIGITS) return { error: lengthMessage(digits.length, digits) };
  return { value: digits };
}
