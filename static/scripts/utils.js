// Charging strategies an area can be analysed under: [value, label]
export const STRATEGIES = [
  ["afap", "As Fast As Possible"],
  ["alap", "As Late As Possible"],
  ["avg", "Average Power"],
  ["mincarbon", "Min. Carbon Footprint"],
  ["ocost", "Min. Charging Cost"],
];
// Demand scenarios: [value, label]
export const DEMANDS = [
  ["low", "Low demand"],
  ["base", "Base demand"],
  ["high", "High demand"],
];
const strategyLabel = value => (STRATEGIES.find(([key]) => key === value) || [, value || ""])[1];

// Show a status message in the bottom action bar
export function animateSelectMessage(newMessage) {
  const message = document.getElementById("select-message");
  if (!message) return;

  message.textContent = newMessage || message.textContent;

  // Restart the fade-in animation
  message.classList.remove("flash");
  void message.offsetWidth;
  message.classList.add("flash");
}

function generateLoadDataSheet(profile_data) {
  // Initialize an array for worksheet data with headers
  const wsData = [
    [
      "Area Name",
      "Timestamp (UTC)",
      "EV Load (kW)",
      "Upward Flexibility (kW)",
      "Downward Flexibility (kW)",
      "Session source", "Demand assumption", "Synthetic", "Charging strategy",
    ],
  ];
  // Seeded draws add the 10th and 90th percentile of the load
  const withBand = profile_data.some((group) => group.band);
  if (withBand) wsData[0].push("EV Load 10th percentile (kW)", "EV Load 90th percentile (kW)");

  // Calculate the starting time (yesterday 00:00)
  const today = new Date();
  const startTime = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  for (let i = 0; i < profile_data.length; i++) {
    const group = profile_data[i];
    const groupName = group.groupName;
    const pastData = group.pastData;
    const futureData = group.futureData;
    const future_down_flex = group.future_down_flex;
    const future_up_flex = group.future_up_flex;
    const past_down_flex = group.past_down_flex;
    const past_up_flex = group.past_up_flex;

    // Combine past and future data
    const combinedData = pastData.concat(futureData);
    const combinedDownFlex = past_down_flex.concat(future_down_flex);
    const combinedUpFlex = past_up_flex.concat(future_up_flex);
    const dataLength = combinedData.length;

    for (let t = 0; t < dataLength; t++) {
      const evLoad = combinedData[t];
      const upFlex = combinedUpFlex[t];
      const downFlex = combinedDownFlex[t];

      const suppliedTimes = group.pastTimes?.concat(group.futureTimes);
      const timestamp = suppliedTimes ? new Date(suppliedTimes[t])
        : new Date(startTime.getTime() + t * 10 * 60000);

      // Format timestamp as desired (e.g., 'YYYY-MM-DD HH:mm:ss')
      const formattedTimestamp = timestamp
        .toISOString()
        .replace("T", " ")
        .substring(0, 19);

      const row = [groupName, formattedTimestamp, evLoad, upFlex, downFlex,
        group.source?.label || "Stored sessions", group.source?.assumption || "", group.source?.synthetic ?? "",
        strategyLabel(group.strategy)];
      if (withBand) row.push(group.band?.p10[t] ?? "", group.band?.p90[t] ?? "");
      wsData.push(row);
    }
  }

  // Convert array to worksheet
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  return ws;
}

function generateChargerIdSheet(selectedChargerIds, profile_data) {
  // Initialize an array for worksheet data with headers
  const wsData = [["Area Name", "Charger IDs"]];

  for (let i = 0; i < selectedChargerIds.length; i++) {
    const chargerIds = selectedChargerIds[i];
    const groupName = profile_data[i]
      ? profile_data[i].groupName
      : `Area ${i + 1}`;

    for (let j = 0; j < chargerIds.length; j++) {
      const chargerId = chargerIds[j];
      wsData.push([groupName, chargerId]);
    }
  }

  // Convert array to worksheet
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  return ws;
}

function generateKPIsSheet(kpi_data_list) {
  const group = kpi_data_list;
  kpi_data_list = kpi_data_list.kpi;
  const wsData = [];

  // Add a header row (optional)
  wsData.push(["KPI Category", "Values"]);
  wsData.push(["Session source", group.source?.label || kpi_data_list.source?.label || "Stored sessions"]);
  wsData.push(["Demand assumption", kpi_data_list.source?.assumption || ""]);
  wsData.push(["Synthetic", kpi_data_list.source?.synthetic ?? ""]);
  wsData.push(["Start date (inclusive)", kpi_data_list.range?.start_date || ""]);
  wsData.push(["End date (inclusive)", kpi_data_list.range?.end_date || ""]);
  wsData.push(["Timezone", kpi_data_list.range?.timezone || ""]);
  const environment = kpi_data_list.environment;
  if (environment?.strategies) {
    wsData.push(["Environmental method", environment.note]);
    wsData.push(["Historical grid reference", environment.uses_historical_reference]);
    wsData.push(["Reference observations start", environment.reference_source_start || ""]);
    wsData.push(["Reference observations end", environment.reference_source_end || ""]);
    wsData.push(["Strategy", "Energy (kWh)", "Covered emissions (kgCO2e)", "Mean intensity (gCO2e/kWh)",
      "Renewable share (%)", "Carbon energy coverage (%)", "Renewable energy coverage (%)",
      "Matching-date carbon coverage (%)", "Estimated carbon energy (%)", "Status", "Footprint difference vs AFAP (kgCO2e)"]);
    for (const value of Object.values(environment.strategies)) {
      wsData.push([value.label, value.energy_kwh, value.emissions_kg, value.average_intensity_g_per_kwh,
        value.renewable_share_pct, value.carbon_energy_coverage_pct, value.renewable_energy_coverage_pct,
        value.matching_date_carbon_coverage_pct, value.estimated_carbon_energy_pct, value.status,
        value.footprint_difference_vs_afap_kg]);
    }
  }

  // Push each distribution array as a separate row
  wsData.push(["arrival_dist_wd", ...kpi_data_list.arrival_dist_wd]);
  wsData.push(["arrival_dist_we", ...kpi_data_list.arrival_dist_we]);
  wsData.push(["consumption_dist_wd", ...kpi_data_list.consumption_dist_wd]);
  wsData.push(["consumption_dist_we", ...kpi_data_list.consumption_dist_we]);
  wsData.push([
    "daily_consumption_dist_wd",
    ...kpi_data_list.daily_consumption_dist_wd,
  ]);
  wsData.push([
    "daily_consumption_dist_we",
    ...kpi_data_list.daily_consumption_dist_we,
  ]);
  wsData.push(["departure_dist_wd", ...kpi_data_list.departure_dist_wd]);
  wsData.push(["departure_dist_we", ...kpi_data_list.departure_dist_we]);
  wsData.push(["duration_dist_wd", ...kpi_data_list.duration_dist_wd]);
  wsData.push(["duration_dist_we", ...kpi_data_list.duration_dist_we]);
  wsData.push([
    "hour_of_arrival_consumption_wd",
    ...kpi_data_list.hour_of_arrival_consumption_wd,
  ]);
  wsData.push([
    "hour_of_arrival_consumption_we",
    ...kpi_data_list.hour_of_arrival_consumption_we,
  ]);
  wsData.push([
    "occupation_ratio_dist",
    ...kpi_data_list.occupation_ratio_dist,
  ]);

  // Sessions per day for days 0 through 6
  for (let i = 0; i < 7; i++) {
    wsData.push([
      `sessions_per_day_${i}`,
      ...kpi_data_list[`sessions_per_day_${i}`],
    ]);
  }

  wsData.push(["weekday_availability", ...kpi_data_list.weekday_availability]);
  wsData.push(["weekend_availability", ...kpi_data_list.weekend_availability]);

  // Series of newer responses; older ones simply lack them
  const series = [
    ...["wd", "we"].flatMap((kind) => [`slack_dist_${kind}`, `load_profile_${kind}`]),
    "load_duration_kw", "weekday_blocking", "weekend_blocking",
    "sessions_per_day_mean", "sessions_per_day_p90", "sessions_per_day_observations",
  ];
  for (const name of series) {
    if (Array.isArray(kpi_data_list[name])) wsData.push([name, ...kpi_data_list[name]]);
  }
  const usage = kpi_data_list.charger_usage;
  if (usage?.id?.length) {
    wsData.push(["Charger", "Occupancy (share of time)", "Utilisation (energy / rated power)", "Sessions", "Energy (kWh)"]);
    usage.id.forEach((id, i) => wsData.push([id, usage.occupancy[i], usage.utilisation[i], usage.sessions[i], usage.energy_kwh[i]]));
  }
  const summary = kpi_data_list.summary;
  if (summary) {
    const figures = [
      ["Sessions", summary.session_count], ["Median stay (h)", summary.median_duration_hours],
      ["90th percentile stay (h)", summary.p90_duration_hours], ["Mean arrival (local hour)", summary.mean_arrival_hour],
      ["Idle share of stay time", summary.slack_share], ["Peak uncontrolled load (kW)", summary.peak_kw],
      ["Peak time (local)", summary.peak_time], ["Load factor", summary.load_factor],
      ["Coincidence factor", summary.coincidence_factor], ["Idle charger-day share", summary.idle_charger_day_share],
      ["Sessions per used charger-day", summary.sessions_per_used_charger_day],
      ["Median gap between sessions (h)", summary.median_idle_gap_hours],
      ["Mean utilisation", summary.mean_utilisation], ["Highest all-busy probability", summary.max_blocking_probability],
    ];
    for (const [name, value] of figures) if (value !== undefined) wsData.push([name, value]);
  }

  // Convert the 2D array to a worksheet
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  return ws;
}

// Excel sheet names are at most 31 characters, exclude \ / ? * [ ] : and must be
// unique, whatever the areas are called
function sheetName(area, suffix, used) {
  const cleaned = String(area).replace(/[\\/?*\[\]:]/g, " ").trim() || "Area";
  const fit = (tag = "") => cleaned.slice(0, 31 - suffix.length - tag.length).trim() + tag + suffix;
  let name = fit();
  for (let number = 2; used.has(name.toLowerCase()); number++) name = fit(`_${number}`);
  used.add(name.toLowerCase());
  return name;
}

export function generateAndDownloadExcel(selectedChargerIds, profile_data, kpi_data_list) {
  // First Sheet: Load Data
  const loadDataSheet = generateLoadDataSheet(profile_data);

  // Second Sheet: Charger IDs
  const chargerIdSheet = generateChargerIdSheet(
    selectedChargerIds,
    profile_data.length ? profile_data : kpi_data_list
  );

  // Create a new Workbook
  const wb = XLSX.utils.book_new();

  // Append the sheets to the workbook
  if (profile_data.length) XLSX.utils.book_append_sheet(wb, loadDataSheet, "Load Data");
  XLSX.utils.book_append_sheet(wb, chargerIdSheet, "Charger IDs");

  const usedSheetNames = new Set(["load data", "charger ids"]);
  for (let i = 0; i < kpi_data_list.length; i++) {
    var kpisSheet = generateKPIsSheet(kpi_data_list[i]);
    XLSX.utils.book_append_sheet(wb, kpisSheet, sheetName(kpi_data_list[i].groupName, "_KPIs", usedSheetNames));
  }

  // Generate XLSX file and trigger download
  XLSX.writeFile(wb, "DRIVE2X_EPIOT_report.xlsx");
}
