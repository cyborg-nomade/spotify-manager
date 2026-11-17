// Presentation-only transformations. Original indices and scores stay intact.
export const eraBands = [
  { lt: 0.02, label: "<2%", color: "#293c55" },
  { gte: 0.02, lt: 0.05, label: "2–5%", color: "#426fa3" },
  { gte: 0.05, lt: 0.1, label: "5–10%", color: "#6caed6" },
  { gte: 0.1, lt: 0.2, label: "10–20%", color: "#d9ac52" },
  { gte: 0.2, lt: 0.35, label: "20–35%", color: "#f0d783" },
  { gte: 0.35, label: "≥35%", color: "#fff4cf" },
];

export function eraBand(value) {
  return eraBands.find((band) => value < (band.lt ?? Infinity));
}

function closestPair(active, nodes, scores, width) {
  let best = { left: active[0], right: active[1], score: -1, tie: Infinity };
  for (let left = 0; left < active.length; left++) {
    for (let right = left + 1; right < active.length; right++) {
      const a = active[left],
        b = active[right];
      const score = scores[a][b];
      const low = Math.min(nodes[a].minimum, nodes[b].minimum);
      const high = Math.max(nodes[a].minimum, nodes[b].minimum);
      const tie = low * width + high;
      const better = score > best.score + 1e-12;
      const equal = Math.abs(score - best.score) <= 1e-12;
      if (better || (equal && tie < best.tie))
        best = { left: a, right: b, score, tie };
    }
  }
  return best;
}

function mergeCluster(pair, active, nodes, scores) {
  const left = nodes[pair.left],
    right = nodes[pair.right];
  const first = left.minimum < right.minimum ? left : right;
  const second = first === left ? right : left;
  const merged = {
    size: left.size + right.size,
    minimum: Math.min(left.minimum, right.minimum),
    order: [...first.order, ...second.order],
  };
  const id = nodes.length;
  scores[id] = new Float64Array(scores.length);
  for (const other of active) {
    const score =
      (scores[pair.left][other] * left.size +
        scores[pair.right][other] * right.size) /
      merged.size;
    scores[id][other] = score;
    scores[other][id] = score;
  }
  nodes.push(merged);
  return [
    ...active.filter((other) => other !== pair.left && other !== pair.right),
    id,
  ];
}

export function groupedEraOrder(data) {
  const populated = [],
    empty = [];
  for (let index = 0; index < data.periods.length; index++) {
    (data.periods[index].plays ? populated : empty).push(index);
  }
  if (populated.length < 2) return [...populated, ...empty];
  const nodes = populated.map((index) => ({
    size: 1,
    minimum: index,
    order: [index],
  }));
  const scores = new Array(populated.length * 2);
  for (let left = 0; left < populated.length; left++) {
    scores[left] = new Float64Array(scores.length);
    for (let right = 0; right < populated.length; right++) {
      scores[left][right] =
        data.similarities[populated[left]][populated[right]] ?? 0;
    }
  }
  let active = populated.map((_index, id) => id);
  while (active.length > 1) {
    const pair = closestPair(active, nodes, scores, data.periods.length);
    active = mergeCluster(pair, active, nodes, scores);
  }
  return [...nodes[active[0]].order, ...empty];
}

export function eraCells(data, order, threshold) {
  const cells = [];
  for (let row = 0; row < order.length; row++) {
    for (let column = 0; column < order.length; column++) {
      const originalRow = order[row],
        originalColumn = order[column];
      const score = data.similarities[originalRow][originalColumn];
      const self = originalRow === originalColumn;
      const color =
        score === null ? "#15232a" : self ? "#727981" : eraBand(score).color;
      cells.push({
        value: [column, row, score],
        originalRow,
        originalColumn,
        itemStyle: {
          color,
          opacity: score === null || self || score >= threshold ? 1 : 0.16,
          borderColor: score === null ? "#34424a" : "transparent",
          borderWidth: score === null ? 0.4 : 0,
        },
      });
    }
  }
  return cells;
}

export function eraHighlight(score, self, threshold) {
  if (score === null) return "Not comparable";
  if (self) return "Self-comparison";
  return score >= threshold ? "Highlighted" : "Below highlight threshold";
}
