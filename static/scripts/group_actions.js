// Edits to the list of analysed areas made from the result cards. The page
// keeps several arrays parallel to the drawn areas (specs, charger ids,
// profiles, KPIs); each helper returns a new array so the same edit can be
// applied to all of them.

export const MAX_AREAS = 3;
// Names end up in Excel sheet names and map labels, so keep them short
export const MAX_NAME_LENGTH = 40;

export function moved(items, from, to) {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return items.slice();
  const next = items.slice();
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next;
}

export function removed(items, index) {
  return items.filter((_, position) => position !== index);
}

// Insert a copy right below the item it was made from
export function copied(items, index, copy) {
  const next = items.slice();
  next.splice(index + 1, 0, copy(items[index]));
  return next;
}

// "Area 1" -> "Area 1 (copy)" -> "Area 1 (copy 2)"; names identify areas, so
// the result never repeats one that is taken
export function copyName(name, taken) {
  const base = name.replace(/ \(copy(?: \d+)?\)$/, "");
  let candidate = `${base} (copy)`;
  for (let number = 2; taken.includes(candidate); number++) candidate = `${base} (copy ${number})`;
  return candidate;
}

// A new name must be filled in and not taken, since names identify areas.
// Returns { name } with the tidied name, or { error } to show the user.
export function validName(requested, others) {
  const name = String(requested).trim().replace(/\s+/g, " ");
  if (!name) return { error: "Give the area a name." };
  if (name.length > MAX_NAME_LENGTH) return { error: `Use at most ${MAX_NAME_LENGTH} characters.` };
  if (others.some((other) => other.toLowerCase() === name.toLowerCase())) {
    return { error: "Another area already has this name." };
  }
  return { name };
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

// Colours already worn by an area are skipped, so a copy stays distinguishable
export function freeColor(palette, used) {
  return palette.find((color) => !used.includes(color)) ?? palette[used.length % palette.length];
}
