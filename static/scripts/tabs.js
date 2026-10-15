// The panel's Load profiles / Flexibility / KPIs tabs.
import { DEFAULT_NOTE } from "./analysis.js";

const TABS = { "load-tab": "Load Profiles", "flex-tab": "Flexibility" };

/**
 * @param {object} deps
 * @param {object} deps.state shared analysis state
 * @param {{hidden: boolean}} deps.kpiSubnav the KPI category bar, shown only on the KPI tab
 * @param {(tabId: string) => void} deps.setActiveTab marks the tab button as active
 * @param {() => void} deps.hideTooltips closes any open tab tooltip
 * @param {(text: string) => void} deps.setNote sets the line under the controls
 * @param {() => void} deps.runActiveAnalysis analyses for the tab that was just opened
 */
export function createTabs({ state, kpiSubnav, setActiveTab, hideTooltips, setNote, runActiveAnalysis }) {
  function showTab(tabId) {
    state.active_tab = TABS[tabId] || "KPIs";
    hideTooltips();
    setActiveTab(tabId);
    kpiSubnav.hidden = state.active_tab !== "KPIs";
    setNote(DEFAULT_NOTE);
    runActiveAnalysis();
  }
  return { showTab };
}
