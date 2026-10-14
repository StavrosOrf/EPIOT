// One-line summary of the day-level calendar effects reported with a scenario.
const factor = value => `×${value.toFixed(2)}`;

export function calendarNote(metadata) {
  const calendar = metadata?.calendar;
  if (!calendar?.applied) return "";
  const [country, days] = Object.entries(calendar.days || {})[0] || [];
  if (!days?.length) return "";
  const label = day => day.holiday ? `${day.holiday} (${day.day_type === "partial" ? "partial holiday" : "holiday"})` : day.day_type;
  if (metadata.target_date) {
    const day = days.find(item => item.date === metadata.target_date) || days.at(-1);
    return `${day.date}, ${country}: ${label(day)}, synthetic ${day.temperature_c.toFixed(1)} °C, ` +
      `demand ${factor(day.volume_factor)}, energy per session ${factor(day.energy_factor)}.`;
  }
  const volumes = days.map(day => day.volume_factor), temperatures = days.map(day => day.temperature_c);
  const holidays = days.filter(day => day.holiday).map(day => day.holiday);
  return `${country} day effects: demand ${factor(Math.min(...volumes))}–${factor(Math.max(...volumes))}, ` +
    `synthetic ${Math.min(...temperatures).toFixed(0)} to ${Math.max(...temperatures).toFixed(0)} °C` +
    (holidays.length ? `, holidays: ${holidays.join(", ")}.` : ".");
}
