// Function to animate the select message
export function animateSelectMessage(newMessage) {
  const message = document.getElementById("select-message");
  if (!message) return;

  const text = newMessage || message.innerText;

  message.innerHTML = ""; // Clear current content

  // Split each character into a span with a delay effect
  text.split("").forEach((char, i) => {
    const span = document.createElement("span");
    span.style.setProperty("--i", i); // Set a custom property for animation delay
    span.innerText = char;
    if (char === " ") {
      span.style.width = "10px"; // Add extra space for spaces
    }
    message.appendChild(span);
  });
}

function generateLoadDataSheet(profile_data) {
  // Initialize an array for worksheet data with headers
  const wsData = [
    [
      "Area Name",
      "Timestamp",
      "EV Load (kWh)",
      "Upward Flexibility (kW)",
      "Downward Flexibility (kW)",
    ],
  ];

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

      const timestamp = new Date(startTime.getTime() + (t + 6) * 10 * 60000); // 10 minutes in milliseconds

      // Format timestamp as desired (e.g., 'YYYY-MM-DD HH:mm:ss')
      const formattedTimestamp = timestamp
        .toISOString()
        .replace("T", " ")
        .substring(0, 19);

      wsData.push([groupName, formattedTimestamp, evLoad, upFlex, downFlex]);
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
  kpi_data_list = kpi_data_list.kpi;
  const wsData = [];

  // Add a header row (optional)
  wsData.push(["KPI Category", "Values"]);

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

  // Convert the 2D array to a worksheet
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  return ws;
}

export function generateAndDownloadExcel(selectedChargerIds, profile_data, kpi_data_list) {
  // First Sheet: Load Data
  const loadDataSheet = generateLoadDataSheet(profile_data);

  // Second Sheet: Charger IDs
  const chargerIdSheet = generateChargerIdSheet(
    selectedChargerIds,
    profile_data
  );

  // Create a new Workbook
  const wb = XLSX.utils.book_new();

  // Append the sheets to the workbook
  XLSX.utils.book_append_sheet(wb, loadDataSheet, "Load Data");
  XLSX.utils.book_append_sheet(wb, chargerIdSheet, "Charger IDs");

  for (let i = 0; i < kpi_data_list.length; i++) {
    // find area name from the selected_area_names
    let area_name = profile_data[i].groupName;
    var kpisSheet = generateKPIsSheet(kpi_data_list[i]);
    var name = area_name + "_KPIs";
    XLSX.utils.book_append_sheet(wb, kpisSheet, name);
  }

  // Generate XLSX file and trigger download
  XLSX.writeFile(wb, "DRIVE2X_EPIOT_report.xlsx");
}
