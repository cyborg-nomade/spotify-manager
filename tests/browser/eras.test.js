import { test } from "node:test";
import assert from "node:assert/strict";
import {
  eraBand,
  eraBands,
  eraCells,
  eraHighlight,
  groupedEraOrder,
} from "../../spotify_manager/frontend/lastfm-assets/eras-v1.js";

function fixture(similarities, plays = similarities.map(() => 1)) {
  return {
    periods: plays.map((count, index) => ({
      label: String(index),
      plays: count,
    })),
    similarities,
  };
}

test("fixed bands have exact nonoverlapping boundaries and distinct colors", () => {
  const cases = [
    [0, "<2%"],
    [0.019999, "<2%"],
    [0.02, "2–5%"],
    [0.049999, "2–5%"],
    [0.05, "5–10%"],
    [0.099999, "5–10%"],
    [0.1, "10–20%"],
    [0.199999, "10–20%"],
    [0.2, "20–35%"],
    [0.349999, "20–35%"],
    [0.35, "≥35%"],
    [1, "≥35%"],
  ];
  for (const [value, label] of cases) assert.equal(eraBand(value).label, label);
  assert.equal(new Set(eraBands.map((band) => band.color)).size, 6);
});

test("similar months become contiguous without changing their original scores", () => {
  const data = fixture([
    [1, 0.02, 0.8, 0.01],
    [0.02, 1, 0.03, 0.85],
    [0.8, 0.03, 1, 0.04],
    [0.01, 0.85, 0.04, 1],
  ]);
  const before = JSON.stringify(data);
  assert.deepEqual(groupedEraOrder(data), [0, 2, 1, 3]);
  assert.equal(JSON.stringify(data), before);
});

test("average linkage weights every original period when group sizes differ", () => {
  // After merging 0/1/2, similarity to 5 is (0.1 + 0.1 + 0.79) / 3,
  // below 0.4 to group 3/4. Unweighted cluster averages choose the wrong merge.
  const data = fixture([
    [1, 0.99, 0.8, 0.4, 0.4, 0.1],
    [0.99, 1, 0.8, 0.4, 0.4, 0.1],
    [0.8, 0.8, 1, 0.4, 0.4, 0.79],
    [0.4, 0.4, 0.4, 1, 0.95, 0.2],
    [0.4, 0.4, 0.4, 0.95, 1, 0.2],
    [0.1, 0.1, 0.79, 0.2, 0.2, 1],
  ]);
  assert.deepEqual(groupedEraOrder(data), [0, 1, 2, 3, 4, 5]);
});

test("ties are chronological and empty periods follow populated groups", () => {
  assert.deepEqual(
    groupedEraOrder(fixture(Array.from({ length: 4 }, () => [1, 1, 1, 1]))),
    [0, 1, 2, 3],
  );
  assert.deepEqual(
    groupedEraOrder(
      fixture(
        [
          [1, null, 0.7],
          [null, null, null],
          [0.7, null, 1],
        ],
        [2, 0, 3],
      ),
    ),
    [0, 2, 1],
  );
  assert.deepEqual(
    groupedEraOrder(
      fixture(
        [
          [null, null],
          [null, null],
        ],
        [0, 0],
      ),
    ),
    [0, 1],
  );
  assert.deepEqual(
    groupedEraOrder(
      fixture(
        [
          [null, null],
          [null, 1],
        ],
        [0, 1],
      ),
    ),
    [1, 0],
  );
  assert.deepEqual(groupedEraOrder(fixture([])), []);
});

test("grouped chart coordinates retain original indices, nulls and exact scores", () => {
  const data = fixture(
    [
      [1, 0.02, null],
      [0.02, 1, null],
      [null, null, null],
    ],
    [1, 1, 0],
  );
  const before = JSON.stringify(data);
  const cells = eraCells(data, [1, 0, 2], 0.05);
  assert.equal(cells.length, 9);
  const pair = cells[1];
  assert.deepEqual(pair.value, [1, 0, 0.02]);
  assert.equal(pair.originalRow, 1);
  assert.equal(pair.originalColumn, 0);
  assert.equal(pair.itemStyle.color, eraBand(0.02).color);
  assert.equal(pair.itemStyle.opacity, 0.16);
  assert.equal(cells[0].itemStyle.color, "#727981");
  assert.equal(cells[0].itemStyle.opacity, 1);
  assert.equal(cells[2].value[2], null);
  assert.equal(cells[2].itemStyle.color, "#15232a");
  assert.equal(eraCells(data, [0, 1, 2], 0)[1].itemStyle.opacity, 1);
  assert.equal(JSON.stringify(data), before);
});

test("accessible highlight descriptions distinguish self, empty and threshold boundaries", () => {
  assert.equal(eraHighlight(null, true, 0), "Not comparable");
  assert.equal(eraHighlight(1, true, 1), "Self-comparison");
  assert.equal(eraHighlight(0.1, false, 0.1), "Highlighted");
  assert.equal(eraHighlight(0.099999, false, 0.1), "Below highlight threshold");
});

test("maximum monthly matrix yields a complete deterministic permutation", () => {
  const matrix = Array.from({ length: 240 }, (_, row) =>
    Array.from({ length: 240 }, (_, column) =>
      row === column ? 1 : row % 4 === column % 4 ? 0.8 : 0.01,
    ),
  );
  const order = groupedEraOrder(fixture(matrix));
  assert.equal(order.length, 240);
  assert.equal(new Set(order).size, 240);
  assert.deepEqual(
    [...order].sort((a, b) => a - b),
    Array.from({ length: 240 }, (_, index) => index),
  );
  for (let group = 0; group < 4; group++) {
    const positions = order
      .map((index, position) => (index % 4 === group ? position : -1))
      .filter((position) => position >= 0);
    assert.equal(positions.at(-1) - positions[0], 59);
  }
});
