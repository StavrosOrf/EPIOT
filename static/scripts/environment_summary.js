const escape = value => String(value ?? "").replace(/[&<>"']/g, character => ({
  "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;",
})[character]);

const format = (value, digits=1) => Number.isFinite(value) ? value.toLocaleString(undefined, {
  minimumFractionDigits:digits, maximumFractionDigits:digits,
}) : "—";

export function renderEnvironmentSummary(groups, container) {
  if (!container) return;
  container.hidden = !groups.length;
  container.innerHTML = groups.map(group => {
    const environment = group.kpi.environment;
    if (!environment?.strategies) return "";
    const usesReference = environment.uses_historical_reference;
    const statuses = Object.values(environment.strategies).map(value => value.status);
    const partial = statuses.some(value => value === "partial" || value === "partial_reference");
    const badge = usesReference ? (partial ? "Partial historical reference" : "Historical reference")
      : partial ? "Partial grid coverage" : environment.covered_steps ? "Matching-date grid data" : "Grid data unavailable";
    const period = usesReference ? `${environment.reference_source_start?.slice(0,10)}–${environment.reference_source_end?.slice(0,10)}` : "";
    const rows = Object.entries(environment.strategies).map(([strategy, value]) => {
      const difference = value.footprint_difference_vs_afap_pct;
      const delta = Number.isFinite(difference) ? `${difference>0?"+":""}${format(difference)}%` : "—";
      const coverage = Number.isFinite(value.carbon_energy_coverage_pct) ? `${format(value.carbon_energy_coverage_pct,0)}%` : "—";
      const actual = Number.isFinite(value.matching_date_carbon_coverage_pct) ? `${format(value.matching_date_carbon_coverage_pct,0)}% on matching dates` : "";
      return `<tr class="${strategy==="afap"?"environment-baseline":""}">
        <th scope="row">${escape(value.label)}${strategy==="afap"?' <span class="environment-baseline-label">Baseline</span>':""}</th>
        <td>${format(value.energy_kwh)}</td><td>${format(value.emissions_kg,2)}</td>
        <td>${format(value.average_intensity_g_per_kwh,0)}</td><td>${Number.isFinite(value.renewable_share_pct)?`${format(value.renewable_share_pct)}%`:"—"}<small>${Number.isFinite(value.renewable_energy_coverage_pct)?`${format(value.renewable_energy_coverage_pct,0)}% energy covered`:""}</small></td>
        <td>${coverage}<small>${escape(actual)}</small></td><td>${delta}</td>
      </tr>`;
    }).join("");
    const unavailable = Object.values(environment.strategies).filter(value => !value.available && value.reason)
      .map(value => `<p class="environment-warning">${escape(value.label)}: ${escape(value.reason)}</p>`).join("");
    return `<article class="environment-card">
      <header><h3>${escape(group.groupName)}</h3><span class="environment-badge ${usesReference||partial?"environment-badge--reference":""}">${escape(badge)}</span></header>
      ${usesReference?`<p class="environment-context">Reference observations: ${escape(period)}. Reused by local hour; these are not the actual grid mix for other dates.</p>`:""}
      <div class="environment-table-scroll"><table>
        <caption class="sr-only">Equal-energy environmental scenario comparison for ${escape(group.groupName)}</caption>
        <thead><tr><th>Strategy</th><th>Energy<br>kWh</th><th>${partial?"Covered emissions":"Emissions"}<br>kgCO₂e</th><th>Mean intensity<br>gCO₂e/kWh</th><th>Renewable<br>share</th><th>Carbon energy<br>coverage</th><th>Footprint difference<br>vs AFAP</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p class="environment-context">Same charging energy and plug-power limits for every strategy. Boundary sessions contribute their in-range energy share. Differences are estimated scenario footprints, not demonstrated avoided emissions.</p>
      ${partial?'<p class="environment-warning">Partial results include only covered charging energy. Comparisons against AFAP are withheld when carbon coverage is incomplete.</p>':""}
      ${unavailable}
    </article>`;
  }).join("");
}
