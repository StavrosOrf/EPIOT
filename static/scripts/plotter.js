// ---------------------------------------------------------------------------
// Shared rendering: every chart goes through renderPlot so that sizing,
// typography and the small-screen layout stay consistent.
// ---------------------------------------------------------------------------

const NARROW_WIDTH = 640;
// Below this width per subplot column, a multi-column grid is stacked
const MIN_COLUMN_WIDTH = 300;
let lastPlot = null;

function containerWidth(container) {
  return container.clientWidth || window.innerWidth;
}

function isNarrow(container) {
  return containerWidth(container) < NARROW_WIDTH;
}

// Layout "mode" used to decide when a resize needs a full re-layout
function layoutMode(container, columns) {
  const width = containerWidth(container);
  const stacked = columns > 1 && width / columns < MIN_COLUMN_WIDTH;
  return `${isNarrow(container) ? "n" : "w"}${stacked ? "s" : "g"}`;
}

// Word-wrap a (possibly <b>-wrapped) subplot title for small screens
function wrapTitle(text, maxChars) {
  const bold = /^<b>(.*)<\/b>$/.exec(text);
  const words = (bold ? bold[1] : text).split(" ");
  const lines = [""];
  words.forEach((word) => {
    const current = lines[lines.length - 1];
    if (current && (current + " " + word).length > maxChars) lines.push(word);
    else lines[lines.length - 1] = current ? current + " " + word : word;
  });
  const wrapped = lines.join("<br>");
  return bold ? `<b>${wrapped}</b>` : wrapped;
}

function renderPlot(data, layout) {
  const container = document.getElementById("graph");
  // Keep pristine copies so the plot can be re-laid out on resize
  lastPlot = { data: structuredClone(data), layout: structuredClone(layout) };

  const narrow = isNarrow(container);
  const grid = layout.grid || { rows: 1, columns: 1 };
  const columns = grid.columns || 1;
  let rows = grid.rows || 1;
  const mode = layoutMode(container, columns);

  // When the columns would get too thin, stack the grid into one column.
  // Grid cells are numbered row-major, so axis references keep their meaning.
  const stacked = mode.endsWith("s");
  if (stacked) {
    rows = rows * columns;
    layout.grid = { ...grid, rows: rows, columns: 1 };
  }

  const rowHeight = narrow ? 250 : columns > 1 && !stacked ? 300 : 320;
  const margin = narrow
    ? { t: 96, b: 64, l: 64, r: 12 }
    : { t: 100, b: 80, l: 80, r: 32 };

  layout.grid = {
    ...layout.grid,
    ygap: rows > 1 ? (narrow ? 0.35 : 0.3) : undefined,
    xgap: narrow ? undefined : 0.12,
  };
  // Fill the visible panel area, growing (and scrolling) when there are many rows
  const body = container.parentElement;
  const available = body ? body.clientHeight - 24 : 0;
  layout.height = Math.max(
    narrow ? 380 : 460,
    rows * rowHeight + margin.t + margin.b,
    Math.min(available, 900)
  );
  layout.autosize = true;
  layout.margin = margin;
  layout.font = {
    family: "Inter, system-ui, -apple-system, Segoe UI, sans-serif",
    size: narrow ? 11 : 12,
    color: "#18221c",
  };
  layout.paper_bgcolor = "rgba(0,0,0,0)";
  layout.plot_bgcolor = "#ffffff";
  layout.hoverlabel = { font: { family: layout.font.family } };
  layout.legend = {
    ...(layout.legend || {}),
    orientation: "h",
    x: 0.5,
    xanchor: "center",
    y: 1,
    yanchor: "top",
    yref: "container",
    font: { size: narrow ? 11 : 12 },
  };

  (layout.annotations || []).forEach((annotation) => {
    annotation.font = { ...(annotation.font || {}), size: narrow ? 12 : 14 };
    if (narrow && annotation.text) {
      annotation.text = wrapTitle(annotation.text, 36);
    }
  });

  // Style every axis consistently
  Object.keys(layout)
    .filter((key) => /^[xy]axis\d*$/.test(key))
    .forEach((key) => {
      layout[key] = {
        gridcolor: "#eef1ef",
        zerolinecolor: "#dfe5e1",
        linecolor: "#dfe5e1",
        automargin: true,
        ...layout[key],
      };
    });

  container.innerHTML = "";
  container.dataset.mode = mode;

  Plotly.newPlot(container, data, layout, {
    responsive: true,
    displaylogo: false,
    // The modebar would cover the legend on small screens
    displayModeBar: narrow ? false : "hover",
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    toImageButtonOptions: { filename: "epiot_chart", scale: 2 },
  });
}

// Replace the chart area with an explanatory message (errors, empty areas)
export function showGraphMessage(title, detail = "") {
  const container = document.getElementById("graph");
  lastPlot = null;
  container.innerHTML = `
    <div class="graph-message" role="status">
      <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
      <div class="graph-message__title"></div>
      <div class="graph-message__detail"></div>
    </div>
  `;
  container.querySelector(".graph-message__title").textContent = title;
  container.querySelector(".graph-message__detail").textContent = detail;
}

// Re-lay out the current chart when crossing the narrow/wide breakpoint
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const container = document.getElementById("graph");
    if (!lastPlot || !container || !container.querySelector(".plot-container")) {
      return;
    }
    const columns = (lastPlot.layout.grid && lastPlot.layout.grid.columns) || 1;
    if (layoutMode(container, columns) !== container.dataset.mode) {
      const { data, layout } = lastPlot;
      renderPlot(data, layout);
    }
  }, 150);
});

export function createGraph(groupData, cs_mode = true, startDate = null) {
  var data = [];
  var layout = {
    grid: { rows: groupData.length, columns: 1, pattern: "independent" },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    margin: { t: 80, b: 80, l: 80, r: 80 },
  };

  let maxPower = Math.max(
    ...groupData.map((dataItem) =>
      Math.max(...dataItem.pastData, ...dataItem.futureData)
    )
  );
  maxPower += maxPower * 0.1; // Add 10% padding to the maximum power value

  // Initialize shapes and annotations arrays
  layout.shapes = [];
  layout.annotations = [];

  // Set default start date to yesterday at 00:00 if not provided
  if (!startDate) {
    let today = new Date();
    startDate = new Date(
      today.getFullYear(),
      today.getMonth(),
      today.getDate() - 1,
      0,
      0,
      0
    );
  } else {
    // Ensure startDate is a Date object
    startDate = new Date(startDate);
    startDate.setDate(startDate.getDate() - 1);
    startDate.setHours(0, 0, 0, 0);
  }
  // Generate time steps as Date objects
  var defaultTimeSteps = Array.from({ length: 288 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setMinutes(date.getMinutes() + i * 10);
    return date;
  });

  groupData.forEach((dataItem, index) => {
    const timeSteps = dataItem.pastTimes ? dataItem.pastTimes.concat(dataItem.futureTimes) : defaultTimeSteps;
    const pastSteps = dataItem.pastData.length;
    // Create traces for past and future data as step plots
    var pastTrace = {
      x: timeSteps.slice(0, pastSteps),
      y: dataItem.pastData,
      mode: "lines",
      line: { color: "green", shape: "hv" }, // Step plot
      name: "Previous day (" + formatDate(new Date(timeSteps[0])) + ")",
      xaxis: "x" + (index + 1),
      yaxis: "y" + (index + 1),
      legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var futureTrace = {
      x: timeSteps.slice(pastSteps),
      y: dataItem.futureData,
      mode: "lines",
      line: { color: "blue", shape: "hv" }, // Step plot
      name: "Target day (" + formatDate(new Date(timeSteps[pastSteps])) + ")",
      xaxis: "x" + (index + 1),
      yaxis: "y" + (index + 1),
      legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    data.push(pastTrace, futureTrace);

    let showXLabels = false;
    if (groupData.length === 1) {
      showXLabels = true;
    } else {
      showXLabels = index === groupData.length - 1;
    }
    // Define x-axis and y-axis for each subplot
    layout["xaxis" + (index + 1)] = {
      //   matches: "x", // Match x-axes to the main x-axis
      showticklabels: showXLabels, // Show tick labels only on the last subplot
      tickangle: -45, // Rotate labels if needed
      title: dataItem.pastTimes ? "Time (UTC)" : undefined,
    };

    layout["yaxis" + (index + 1)] = {
      title: "Power (kW)",
      range: [0, maxPower],
      anchor: "x" + (index + 1),
    };

    // Add shaded areas to indicate past and future periods
    layout.shapes.push(
      {
        type: "rect",
        xref: "x",
        yref: "y" + (index + 1) + " domain",
        x0: timeSteps[0],
        y0: 0,
        x1: timeSteps[pastSteps - 1],
        y1: 1,
        fillcolor: "rgba(150, 150, 150, 0.2)",
        layer: "below",
        line: { width: 0 },
      },
      {
        type: "rect",
        xref: "x",
        yref: "y" + (index + 1) + " domain",
        x0: timeSteps[pastSteps],
        y0: 0,
        x1: timeSteps[timeSteps.length - 1],
        y1: 1,
        fillcolor: "rgba(220, 220, 220, 0.2)",
        layer: "below",
        line: { width: 0 },
      }
    );
    let label = "";

    if (cs_mode) {
      label =
        "<b>Aggregated EV Charging Load for: " +
        dataItem.groupName +
        " (" +
        dataItem.number_of_chargers +
        " chargers)" +
        "</b>";
    } else {
      label =
        "<b>Aggregated EV charging Load at MVLV Transformer for: " +
        dataItem.groupName +
        " (" +
        dataItem.number_of_transformers +
        " tr.)" +
        "</b>";
    }

    // Add titles to each subplot
    layout.annotations.push({
      text: label,
      xref: "paper",
      yref: "y" + (index + 1) + " domain",
      x: 0.5,
      y: 1.05,
      xanchor: "center",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 16 },
    });
  });

  // //   add the plot main x-axis

  //     layout.xaxis = {
  //         showticklabels: false, // Show tick labels only on the last subplot
  //         tickangle: -45, // Rotate labels if needed
  //         };

  renderPlot(data, layout);
}

export function createFlexGraph(groupData, flex_mode = true, startDate = null) {
  var data = [];
  var layout = {
    grid: { rows: groupData.length, columns: 1, pattern: "independent" },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    margin: { t: 80, b: 80, l: 80, r: 80 },
  };

  let maxPower = Math.max(
    ...groupData.map((dataItem) =>
      Math.max(
        ...dataItem.future_up_flex,
        ...dataItem.future_down_flex,
        ...dataItem.past_up_flex,
        ...dataItem.past_down_flex
      )
    )
  );

  let minPower = Math.min(
    ...groupData.map((dataItem) =>
      Math.min(
        ...dataItem.future_up_flex,
        ...dataItem.future_down_flex,
        ...dataItem.past_up_flex,
        ...dataItem.past_down_flex
      )
    )
  );

  maxPower += maxPower * 0.1; // Add 10% padding to the maximum power value
  minPower += minPower * 0.1; // Add 10% padding to the maximum power value
  // Initialize shapes and annotations arrays
  layout.shapes = [];
  layout.annotations = [];

  // Set default start date to yesterday at 00:00 if not provided
  if (!startDate) {
    let today = new Date();
    startDate = new Date(
      today.getFullYear(),
      today.getMonth(),
      today.getDate() - 1,
      0,
      0,
      0
    );
  } else {
    startDate = new Date(startDate);
    startDate.setDate(startDate.getDate() - 1);
    startDate.setHours(0, 0, 0, 0);
  }

  // Generate time steps as Date objects
  var defaultTimeSteps = Array.from({ length: 288 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setMinutes(date.getMinutes() + i * 10);
    return date;
  });

  groupData.forEach((dataItem, index) => {
    const timeSteps = dataItem.pastTimes ? dataItem.pastTimes.concat(dataItem.futureTimes) : defaultTimeSteps;
    const pastSteps = dataItem.pastData.length;
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps.slice(0, pastSteps),
      y: dataItem.past_up_flex,
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "hv" }, // Step plot
      name: "Upward Flexibility",
      xaxis: "x" + (index + 1),
      yaxis: "y" + (index + 1),
      legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps.slice(0, pastSteps),
      y: dataItem.past_down_flex,
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "hv" }, // Step plot
      name: "Downward Flexibility",
      xaxis: "x" + (index + 1),
      yaxis: "y" + (index + 1),
      legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var futureTrace_up = {
      x: timeSteps.slice(pastSteps),
      y: dataItem.future_up_flex,
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "hv" }, // Step plot
      // name: "Today (" + formatDate(timeSteps[144]) + ")",
      xaxis: "x" + (index + 1),
      yaxis: "y" + (index + 1),
      legendgroup: "group",
      showlegend: false, // Show legend only once
    };

    var futureTrace_down = {
      x: timeSteps.slice(pastSteps),
      y: dataItem.future_down_flex,
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "hv" }, // Step plot
      // name: "Today (" + formatDate(timeSteps[144]) + ")",
      xaxis: "x" + (index + 1),
      yaxis: "y" + (index + 1),
      legendgroup: "group",
      showlegend: false, // Show legend only once
    };

    data.push(pastTrace_down, pastTrace_up, futureTrace_up, futureTrace_down);

    let showXLabels = false;
    if (groupData.length === 1) {
      showXLabels = true;
    } else {
      showXLabels = index === groupData.length - 1;
    }
    // Define x-axis and y-axis for each subplot
    layout["xaxis" + (index + 1)] = {
      //   matches: "x", // Match x-axes to the main x-axis
      showticklabels: showXLabels, // Show tick labels only on the last subplot
      tickangle: -45, // Rotate labels if needed
      title: dataItem.pastTimes ? "Time (UTC)" : undefined,
    };

    layout["yaxis" + (index + 1)] = {
      title: "Power (kW)",
      range: [minPower, maxPower],
      anchor: "x" + (index + 1),
    };

    // Add shaded areas to indicate past and future periods
    layout.shapes.push(
      {
        type: "rect",
        xref: "x",
        yref: "y" + (index + 1) + " domain",
        x0: timeSteps[0],
        y0: 0,
        x1: timeSteps[pastSteps - 1],
        y1: 1,
        fillcolor: "rgba(150, 150, 150, 0.2)",
        layer: "below",
        line: { width: 0 },
      },
      {
        type: "rect",
        xref: "x",
        yref: "y" + (index + 1) + " domain",
        x0: timeSteps[pastSteps],
        y0: 0,
        x1: timeSteps[timeSteps.length - 1],
        y1: 1,
        fillcolor: "rgba(220, 220, 220, 0.2)",
        layer: "below",
        line: { width: 0 },
      }
    );
    let label = "";

    if (flex_mode) {
      label =
        "<b>Aggregated EV Charging Load for: " +
        dataItem.groupName +
        " (" +
        dataItem.number_of_chargers +
        " chargers)" +
        "</b>";
    } else {
      label =
        "<b>Aggregated EV Charging Flexibility: " +
        dataItem.groupName +
        " (" +
        dataItem.number_of_chargers +
        " chargers)" +
        "</b>";
    }

    // Add titles to each subplot
    layout.annotations.push({
      text: label,
      xref: "paper",
      yref: "y" + (index + 1) + " domain",
      x: 0.5,
      y: 1.05,
      xanchor: "center",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 16 },
    });
  });

  renderPlot(data, layout);
}

export function createUserKPIGraph(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 3,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Time (Hour)" },
    yaxis1: { title: "Sessions Count" },
    xaxis2: { title: "Time (Hour)" },
    yaxis2: { title: "Sessions Count" },
    xaxis3: { title: "Time (Hour)" },
    yaxis3: { title: "Sessions Count" },
    xaxis4: { title: "Time (Hour)" },
    yaxis4: { title: "Sessions Count" },
    xaxis5: { title: "Time (Hour)" },
    yaxis5: { title: "Sessions Count" },
    xaxis6: { title: "Time (Hour)" },
    yaxis6: { title: "Sessions Count" },
    xaxis7: { title: "Time (Hour)" },
    yaxis7: { title: "Sessions Count" },
    xaxis8: { title: "Time (Hour)" },
    yaxis8: { title: "Sessions Count" },
    xaxis9: { title: "Time (Hour)" },
    yaxis9: { title: "Sessions Count" },
  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });

  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps,
      y: dataItem.kpi.arrival_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "spline" },
      name: "Weekdays",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps,
      y: dataItem.kpi.arrival_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "spline" }, // Step plot
      name: "Weekends",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var dist_2_wd = {
      x: timeSteps,
      y: dataItem.kpi.duration_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      // legendgroup: "group",
      showlegend: false,
    };

    var dist_2_we = {
      x: timeSteps,
      y: dataItem.kpi.duration_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      legendgroup: "group",
      showlegend: false,
    };

    var dist_3_we = {
      x: timeSteps,
      y: dataItem.kpi.departure_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      legendgroup: "group",
      showlegend: false,
    };

    var dist_3_wd = {
      x: timeSteps,
      y: dataItem.kpi.departure_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      legendgroup: "group",
      showlegend: false,
    };

    data.push(
      pastTrace_down,
      pastTrace_up,
      dist_2_we,
      dist_2_wd,
      dist_3_we,
      dist_3_wd
    );

    if (groupData.length === 2) {
      layout.xaxis1.title = '';
      layout.xaxis2.title = '';
      layout.xaxis3.title = '';
    } else if (groupData.length === 3) {
      layout.xaxis1.title = '';
      layout.xaxis2.title = '';
      layout.xaxis3.title = '';
      layout.xaxis4.title = '';
      layout.xaxis5.title = '';
      layout.xaxis6.title = '';
    }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `<b>${dataItem.groupName}</b><br>Sessions Count`;
    } else if (index == 1) {
      layout.yaxis4.title = `<b>${dataItem.groupName}</b><br>Sessions Count`;
    } else if (index == 2) {
      layout.yaxis7.title = `<b>${dataItem.groupName}</b><br>Sessions Count`;
    }

    let label = "";

    label =
      "<b>User Probability Distributions: " +
      dataItem.groupName +
      " (" +
      dataItem.number_of_chargers +
      " chargers)" +
      "</b>";

    let label1 = "<b>Arrival Distribution</b>";
    let label2 = "<b>Duration Distribution</b>";
    let label3 = "<b>Departure Distribution</b>";

    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (3 * index + 1) + " domain",
        yref: "y" + (3 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (3 * index + 2) + " domain",
        yref: "y" + (3 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label3,
        xref: "x" + (3 * index + 3) + " domain",
        yref: "y" + (3 * index + 3) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
    }
  });

  // //   add the plot main x-axis

  //     layout.xaxis = {
  //         showticklabels: false, // Show tick labels only on the last subplot
  //         tickangle: -45, // Rotate labels if needed
  //         };

  renderPlot(data, layout);
}

// Helper function to format date as 'DD/MM/YYYY'
function formatDate(date) {
  let day = ("0" + date.getDate()).slice(-2);
  let month = ("0" + (date.getMonth() + 1)).slice(-2); // Months are zero-based
  let year = date.getFullYear();
  return day + "/" + month + "/" + year;
}

export function createGridKPIGraph(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 3,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Arrival Time (Hour)" },
    yaxis1: { title: "Charged Energy (kWh)" },
    xaxis2: { title: "Daily Charged Energy (kWh)" },
    yaxis2: { title: "Days Count" },
    xaxis3: { title: "Session Energy Charged (kWh)" },
    yaxis3: { title: "Sessions Count" },

    xaxis4: { title: "Arrival Time (Hour)" },
    yaxis4: { title: "Charged Energy (kWh)" },
    xaxis5: { title: "Daily Charged Energy (kWh)" },
    yaxis5: { title: "Days Count" },
    xaxis6: { title: "Session Energy Charged (kWh)" },
    yaxis6: { title: "Sessions Count" },

    xaxis7: { title: "Arrival Time (Hour)" },
    yaxis7: { title: "Charged Energy (kWh)" },
    xaxis8: { title: "Daily Charged Energy (kWh)" },
    yaxis8: { title: "Days Count" },
    xaxis9: { title: "Session Energy Charged (kWh)" },
    yaxis9: { title: "Sessions Count" },

  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });

  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps,
      y: dataItem.kpi.hour_of_arrival_consumption_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "hv" },
      name: "Weekdays",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps,
      y: dataItem.kpi.hour_of_arrival_consumption_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "hv" }, // Step plot
      name: "Weekends",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var dist_2_wd = {
      x: Array.from({length: 10}, (_, i) => 10+20*i),
      y: dataItem.kpi.daily_consumption_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      // legendgroup: "group",
      showlegend: false,
    };

    var dist_2_we = {
      x: Array.from({length: 10}, (_, i) => 10+20*i),
      y: dataItem.kpi.daily_consumption_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      legendgroup: "group",
      showlegend: false,
    };

    var dist_3_wd = {
      x: Array.from({length: 10}, (_, i) => 5+10*i),
      y: dataItem.kpi.consumption_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      // legendgroup: "group",
      showlegend: false,
    };

    var dist_3_we = {
      x: Array.from({length: 10}, (_, i) => 5+10*i),
      y: dataItem.kpi.consumption_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      legendgroup: "group",
      showlegend: false,
    };


    data.push(
      pastTrace_down,
      pastTrace_up,
      dist_2_we,
      dist_2_wd,
      dist_3_we,
      dist_3_wd
    );

    // if (groupData.length === 2) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';      
    // } else
     if (groupData.length === 3) {
      layout.xaxis1.title = '';
      layout.xaxis2.title = '';
      layout.xaxis3.title = '';
      layout.xaxis4.title = '';
      layout.xaxis5.title = '';
      layout.xaxis6.title = '';
    }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `<b>${dataItem.groupName}</b><br>Charged Energy (kWh)`;
    } else if (index == 1) {
      layout.yaxis4.title = `<b>${dataItem.groupName}</b><br>Charged Energy (kWh)`;
    } else if (index == 2) {
      layout.yaxis7.title = `<b>${dataItem.groupName}</b><br>Charged Energy (kWh)`;
    }


    let label1 = "<b>Session Energy Distribution</b>";
    let label2 = "<b>Daily Charger Energy Consumption</b>";
    let label3 = "<b>Session Energy Consumption Distribution</b>";


    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (2 * index + 1) + " domain",
        yref: "y" + (2 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (2 * index + 2) + " domain",
        yref: "y" + (2 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label3,
        xref: "x" + (2 * index + 3) + " domain",
        yref: "y" + (2 * index + 3) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
     
    }
  });

 

  renderPlot(data, layout);
}

export function createMobilityKPIGraph(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 1,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Number of Sessions per Charger" },
    yaxis1: { title: "Charged Energy (kWh)" },
    xaxis2: { title: "Number of Sessions per Charger" },
    yaxis2: { title: "Days Count" },
    xaxis3: { title: "Number of Sessions per Charger" },
    yaxis3: { title: "Sessions Count" },

  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });

  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var day_0 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_0,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Monday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };
    var day_1 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_1,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Tuesday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };

    var day_2 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_2,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Wednesday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    var day_3 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_3,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Thursday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    var day_4 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_4,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Friday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    var day_5 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_5,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Saturday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };

    var day_6 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_6,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Sunday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    


    data.push(
      day_0,
      day_1,
      day_2,
      day_3,
      day_4,
      day_5,
      day_6
    );

    // if (groupData.length === 2) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';      
    // } else
    //  if (groupData.length === 3) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';
    //   layout.xaxis3.title = '';
    //   layout.xaxis4.title = '';
    //   layout.xaxis5.title = '';
    //   layout.xaxis6.title = '';
    // }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `<b>${dataItem.groupName}</b><br>Probability`;
    } else if (index == 1) {
      layout.yaxis2.title = `<b>${dataItem.groupName}</b><br>Probability`;
    } else if (index == 2) {
      layout.yaxis3.title = `<b>${dataItem.groupName}</b><br>Probability`;
    }


    let label1 = "<b>Number of Charger Sessions per Day</b>";
    // let label2 = "<b>Daily Charger Energy Consumption</b>";
    // let label3 = "<b>Session Energy Consumption Distribution</b>";


    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (1 * index + 1) + " domain",
        yref: "y" + (1 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
     
    }
  });

 

  renderPlot(data, layout);
}


export function createCityKPIGraph(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 2,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Time of the Day (Hour)" },
    yaxis1: { title: "Probability" },
    xaxis2: { title: "Occupancy Ratio (%)" },
    yaxis2: { title: "Probability" },
    xaxis3: { title: "Time of the Day (Hour)" },
    yaxis3: { title: "Probability" },
    xaxis4: { title: "Occupancy Ratio (%)" },
    yaxis4: { title: "Probability" },
    xaxis5: { title: "Time of the Day (Hour)" },
    yaxis5: { title: "Probability" },
    xaxis6: { title: "Occupancy Ratio (%)" },
    yaxis6: { title: "Probability" },


  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 48 }, (_, i) => i/2);
  // console.log(timeSteps);
  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps,
      y: dataItem.kpi.weekday_availability,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "hvh" },
      name: "Weekdays",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps,
      y: dataItem.kpi.weekend_availability,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "hvh" }, // Step plot
      name: "Weekends",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var dist_2_wd = {
      x: Array.from({length: 20}, (_, i) => 2.5+5*i),
      y: dataItem.kpi.occupation_ratio_dist
      ,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "orange", shape: "spline" },
      name: "Whole Week",
      opacity: 0.3,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      // legendgroup: "group",
      showlegend: index === 0,
    };


    data.push(
      pastTrace_down,
      pastTrace_up,
      dist_2_wd,
    );

    // if (groupData.length === 2) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';      
    // } else
    //  if (groupData.length === 3) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';
    //   layout.xaxis3.title = '';
    //   layout.xaxis4.title = '';
    //   layout.xaxis5.title = '';
    //   layout.xaxis6.title = '';
    // }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `<b>${dataItem.groupName}</b><br>Probability`;
    } else if (index == 1) {
      layout.yaxis3.title = `<b>${dataItem.groupName}</b><br>Probability`;
    } else if (index == 2) {
      layout.yaxis5.title = `<b>${dataItem.groupName}</b><br>Probability`;
    }


    let label1 = "<b>Charger Availability Probability</b>";
    let label2 = "<b>Charger Occupancy Ratio</b>";



    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (2 * index + 1) + " domain",
        yref: "y" + (2 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (2 * index + 2) + " domain",
        yref: "y" + (2 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });

     
    }
  });

  renderPlot(data, layout);
}



export function createEnvironmentKPIGraph(groupData) {
    var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 2,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: " " },
    yaxis1: { title: "Carbon (gCO2eq/kWh)" },    
    xaxis2: { title: " " },
    yaxis2: { title: "Percentage (%)" },
    xaxis3: { title: " " },
    yaxis3: { title: "gCO2eq/kWh" },
    xaxis4: { title: " " },
    yaxis4: { title: "Percentage (%)" },
    xaxis5: { title: "Time of the Day (Hour)" },
    yaxis5: { title: "gCO2eq/kWh" },
    xaxis6: { title: " " },
    yaxis6: { title: "Percentage (%)" },


  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });
  // console.log(timeSteps);
  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var d1 = {
      x: timeSteps,
      y: dataItem.kpi.co2_intensities_uncontrolled,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "blue", shape: "hvh" },
      name: "As Fast As Possible",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var d2 = {
      x: timeSteps,
      y: dataItem.kpi.co2_intensities_delayed,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "red", shape: "hvh" }, // Step plot
      name: "As Late As Possible",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var d3 = {
      x: timeSteps,
      y: dataItem.kpi.co2_intensities_avg,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: "orange", shape: "hvh" }, // Step plot
      name: "Average Power",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var d4 = {
      x: ["As Fast As Possible"],
      y: [dataItem.kpi.renewable_energy_shared_uncontrolled],
      type: "bar",
      marker: { color: "blue" },
      name: "As Fast As Possible",
      opacity: 0.7,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      showlegend: false,
    };

    var d5 = {
      x: ["As Late As Possible"],
      y: [dataItem.kpi.renewable_energy_shared_delayed],
      type: "bar",
      marker: { color: "red" },
      name: "As Late As Possible",
      opacity: 0.7,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      showlegend: false,
    };

    var d6 = {
      x: ["Average Power"],
      y: [dataItem.kpi.renewable_energy_shared_avg],
      type: "bar",
      marker: { color: "orange" },
      name: "Average Power",
      opacity: 0.7,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      showlegend: false,
    };


    data.push(
      d1,
      d2,
      d3,
      d4,
      d5,
      d6
    );
    if (dataItem.kpi.co2_intensities_mincarbon) {
      data.push({
        x: timeSteps, y: dataItem.kpi.co2_intensities_mincarbon,
        type: "scatter", mode: "lines", name: "Minimum Carbon",
        line: {color: "#187040", shape: "hvh"},
        xaxis: "x"+(2*index+1), yaxis: "y"+(2*index+1), showlegend: index===0,
      }, {
        x: ["Minimum Carbon"], y: [dataItem.kpi.renewable_energy_shared_mincarbon],
        type: "bar", name: "Minimum Carbon", marker: {color: "#187040"},
        xaxis: "x"+(2*index+2), yaxis: "y"+(2*index+2), showlegend: false,
      });
    }


    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `<b>${dataItem.groupName}</b><br>Carbon<br>(gCO2eq/kWh)<br>`;
    } else if (index == 1) {
      layout.yaxis3.title = `<b>${dataItem.groupName}</b><br>Carbon<br>(gCO2eq/kWh)<br>`;
    } else if (index == 2) {
      layout.yaxis5.title = `<b>${dataItem.groupName}</b><br>Carbon<br>(gCO2eq/kWh)<br>`;
    }


    let label1 = "<b>Charging-weighted Carbon Intensity</b>";
    let label2 = "<b>Renewable Energy Share</b>";



    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (2 * index + 1) + " domain",
        yref: "y" + (2 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (2 * index + 2) + " domain",
        yref: "y" + (2 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });

     
    }
  });

  renderPlot(data, layout);
}
