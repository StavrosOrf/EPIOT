// Per-area settings. Each area is analysed under its own charging strategy and
// target date (load profiles, flexibility) or date range (KPIs) and demand
// scenario. They are kept by area name, which is unique, so they follow an area
// through moves, renames and copies.
export const DEFAULT_STRATEGY = "afap";
export const DEFAULT_DEMAND = "base";

export function createAreaSettings(now = () => new Date()) {
  const areaSettings = new Map();

  function settingsOf(name) {
    let settings = areaSettings.get(name);
    if (!settings) {
      const today = now();
      const weekStart = new Date(today);
      weekStart.setDate(weekStart.getDate() - 6);
      settings = { strategy: DEFAULT_STRATEGY, demand: DEFAULT_DEMAND, date: today, range: [weekStart, today] };
      areaSettings.set(name, settings);
    }
    return settings;
  }

  return { areaSettings, settingsOf };
}
