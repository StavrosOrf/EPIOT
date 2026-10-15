import { readFileSync } from "node:fs";

// Runs the real plotter.js against a minimal fake DOM and a plotting sink, so
// chart tests need neither a browser nor the Plotly CDN script.

class FakeElement {
  constructor(tag, width) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.style = { setProperty: (name, value) => { this.style[name] = value; } };
    this.className = "";
    this.textContent = "";
    this.clientWidth = width;
    this._html = "";
  }

  set innerHTML(value) {
    this.children = [];
    this._html = value;
  }

  get innerHTML() {
    return this._html;
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }

  querySelector() {
    return new FakeElement("div", this.clientWidth);
  }

  find(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.find(predicate, found);
    }
    return found;
  }
}

// width: size of the chart area and of every plot inside a card
export function loadPlotter({ width = 1000 } = {}) {
  const plots = [];
  const host = new FakeElement("div", width);
  const source = readFileSync(new URL("../static/scripts/plotter.js", import.meta.url), "utf8")
    .replace(/\r\n/g, "\n")
    .replace(/^export /gm, "");
  const names = [...source.matchAll(/^function (\w+)/gm)].map((match) => match[1]);
  const api = new Function("window", "document", "Plotly", "structuredClone",
    `${source};return {${names.join(",")}};`)(
    { innerWidth: width, addEventListener() {} },
    { getElementById: () => host, createElement: (tag) => new FakeElement(tag, width) },
    {
      newPlot: (element, data, layout) => plots.push({ element, data, layout }),
      purge() {},
    },
    structuredClone);
  const cards = () => host.find((node) => node.className === "group-card");
  return { api, plots, host, cards };
}
