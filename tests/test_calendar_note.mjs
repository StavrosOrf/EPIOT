import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const code = readFileSync(new URL("../static/scripts/calendar_note.js", import.meta.url), "utf8").replace(/^export /gm, "");
const { calendarNote } = new Function(code+";return {calendarNote};")();
const day = (date, extra = {}) => ({ date, day_type: "workday", holiday: null, volume_factor: 1.05, temperature_c: 9.44, energy_factor: 0.98, ...extra });

test("a load profile names the target day's holiday, weather and factors", () => {
  const metadata = { target_date: "2026-04-27", calendar: { applied: true, days: { NL: [
    day("2026-04-26", { day_type: "weekend" }), day("2026-04-27", { day_type: "holiday", holiday: "Koningsdag", volume_factor: 0.84 })] } } };
  assert.equal(calendarNote(metadata), "2026-04-27, NL: Koningsdag (holiday), synthetic 9.4 °C, demand ×0.84, energy per session ×0.98.");
});

test("a KPI range summarizes factors and lists its holidays", () => {
  const metadata = { calendar: { applied: true, days: { NL: [day("2026-05-14", { holiday: "Hemelvaartsdag", volume_factor: 0.8, temperature_c: 11 }),
    day("2026-05-15", { day_type: "partial", holiday: "Bridge day", volume_factor: 1.2, temperature_c: 15 })] } } };
  assert.equal(calendarNote(metadata), "NL day effects: demand ×0.80–×1.20, synthetic 11 to 15 °C, holidays: Hemelvaartsdag, Bridge day.");
});

test("disabled or missing effects add nothing", () => {
  assert.equal(calendarNote({ calendar: { applied: false } }), "");
  assert.equal(calendarNote(undefined), "");
});
