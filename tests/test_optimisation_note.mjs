import assert from "node:assert/strict";
import test from "node:test";

import { optimisationNote } from "../static/scripts/analysis.js";

test("strategies without optimisation add nothing", () => {
  assert.equal(optimisationNote([{ label: "Simple" }, undefined]), "");
});

test("reference prices and replaced ReFlex plans are named", () => {
  const sources = [
    { optimisation: { prices_use_reference: false, reflex_plans_replaced: 1 } },
    { optimisation: { prices_use_reference: true, reflex_plans_replaced: 2 } },
  ];
  const note = optimisationNote(sources);
  assert.match(note, /nearest priced day/);
  assert.match(note, /3 ReFlex plans were outside the plug or energy limits/);
  assert.match(optimisationNote([sources[0]]), /1 ReFlex plan was outside/);
});

test("connections still waiting for ReFlex are not mentioned", () => {
  assert.equal(optimisationNote([{ optimisation: { reflex_pending: 4 } }]), "");
});
