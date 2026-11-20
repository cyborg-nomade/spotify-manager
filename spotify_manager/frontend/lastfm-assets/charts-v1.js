import { download, number, percent } from "./tables-v1.js?v=3";
import { eraBands, eraCells } from "./eras-v1.js?v=3";

const instances = new Map();
const palette = [
  "#8cddc5",
  "#efa78a",
  "#adc1ee",
  "#e9c178",
  "#c4aae0",
  "#91c6d8",
  "#dca7bc",
  "#b9cb8c",
];
const weekdayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function select(detail) {
  document.dispatchEvent(new CustomEvent("listening:select", { detail }));
}

function artistColors(series) {
  const available = new Set(palette);
  const colors = new Map([["other", "#62767d"]]);
  const keys = series
    .map((item) => item.key)
    .filter((key) => key !== "other")
    .sort();
  for (const key of keys) {
    const preferred = parseInt(key.slice(0, 8), 16) % palette.length;
    const ordered = [
      ...palette.slice(preferred),
      ...palette.slice(0, preferred),
    ];
    const color = ordered.find((value) => available.has(value));
    colors.set(key, color);
    available.delete(color);
  }
  return colors;
}

function base(title, context) {
  return {
    backgroundColor: "#14232a",
    color: palette,
    animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
    textStyle: {
      fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      color: "#a6b7bc",
    },
    title: {
      text: title,
      subtext: `${context.from} → ${context.to} · ${context.timezone}`,
      left: 0,
      top: 9,
      textStyle: { fontSize: 11, fontWeight: 400, color: "#c5d2d1" },
      subtextStyle: { fontSize: 9, color: "#839b9f" },
    },
    aria: {
      enabled: true,
      label: {
        description: `${title}. Date range ${context.from} through ${context.to}. Timezone ${context.timezone}. An equivalent data table is provided below the chart.`,
      },
      decal: { show: false },
    },
    tooltip: {
      trigger: "item",
      renderMode: "richText",
      backgroundColor: "#243a42",
      borderColor: "#476469",
      textStyle: { color: "#edf3ee", fontSize: 11 },
      confine: true,
    },
    graphic: [
      {
        type: "text",
        left: 0,
        bottom: 1,
        style: {
          text: `Source ${context.snapshot.slice(0, 16)}… · recorded scrobbles`,
          fill: "#789096",
          fontSize: 8,
        },
      },
    ],
  };
}

function axes() {
  return {
    axisLine: { lineStyle: { color: "#3a4c53" } },
    axisTick: { show: false },
    axisLabel: { color: "#94aab0", fontSize: 10 },
    splitLine: { lineStyle: { color: "#263a41" } },
  };
}

function chart(id, title, option, context, onClick) {
  const node = document.getElementById(`${id}-chart`);
  const previous = instances.get(id);
  if (previous) previous.dispose();
  const instance = window.echarts.init(node, null, { renderer: "canvas" });
  instance.setOption({ ...base(title, context), ...option });
  if (onClick) instance.on("click", onClick);
  instances.set(id, instance);
  return instance;
}

export function calendar(data, year, context) {
  const days = data.days.filter((item) => item.day.startsWith(String(year)));
  const maximum = Math.max(1, ...days.map((item) => item.plays));
  chart(
    "calendar",
    `Recorded plays · ${year}`,
    {
      calendar: {
        range: String(year),
        top: 72,
        left: 32,
        right: 10,
        bottom: 51,
        cellSize: ["auto", 15],
        dayLabel: { firstDay: 1, color: "#8ba2a8", fontSize: 9 },
        monthLabel: { color: "#8ba2a8", fontSize: 10 },
        yearLabel: { show: false },
        splitLine: { show: false },
        itemStyle: { color: "#27373e", borderColor: "#14232a", borderWidth: 2 },
      },
      visualMap: {
        min: 0,
        max: maximum,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 19,
        itemWidth: 8,
        itemHeight: 95,
        text: [number(maximum), "0"],
        textGap: 8,
        textStyle: { color: "#8ba2a8", fontSize: 9 },
        inRange: { color: ["#203933", "#3d7661", "#68ad8d", "#a0e2bf"] },
        outOfRange: { color: "#36444b" },
      },
      tooltip: {
        ...base("", context).tooltip,
        formatter: (event) =>
          `${event.data.value[0]}\n${event.data.covered ? `${number(event.data.value[1])} recorded plays` : "Outside observed range"}${event.data.partial ? "\nPartial source boundary day" : ""}`,
      },
      series: [
        {
          type: "heatmap",
          coordinateSystem: "calendar",
          data: days.map((item) => ({
            value: [item.day, item.covered ? item.plays : -1],
            covered: item.covered,
            partial: item.partial,
            itemStyle: item.partial
              ? { borderColor: "#e9c178", borderWidth: 1 }
              : undefined,
          })),
        },
      ],
    },
    context,
    (event) => {
      if (event.data.covered) select({ type: "day", day: event.data.value[0] });
    },
  );
}

export function rhythm(data, mode, context) {
  const average = mode === "average";
  const values = data.hours.map((item) => [
    item.hour,
    item.weekday,
    average ? item.average : item.plays,
  ]);
  chart(
    "rhythm",
    average
      ? "Recorded plays per covered hour"
      : "Recorded plays by local weekday/hour",
    {
      grid: { left: 33, right: 10, top: 61, bottom: 27 },
      xAxis: {
        ...axes(),
        type: "category",
        data: Array.from({ length: 24 }, (_, hour) =>
          String(hour).padStart(2, "0"),
        ),
        splitArea: { show: false },
        axisLabel: { fontSize: 8, interval: 3 },
      },
      yAxis: {
        ...axes(),
        type: "category",
        data: weekdayNames,
        inverse: true,
        splitArea: { show: false },
        axisLabel: { fontSize: 9 },
      },
      visualMap: {
        show: false,
        min: 0,
        max: Math.max(1, ...values.map((item) => item[2])),
        inRange: { color: ["#1e343a", "#397566", "#9adcc2"] },
      },
      tooltip: {
        ...base("", context).tooltip,
        formatter: (event) => {
          const [hour, weekday] = event.value;
          const item = data.hours[weekday * 24 + hour];
          return `${weekdayNames[weekday]} · ${String(hour).padStart(2, "0")}:00\n${number(item.plays)} recorded plays\n${item.occurrences.toFixed(2)} covered hours\n${item.average.toFixed(2)} plays / covered hour`;
        },
      },
      series: [
        {
          type: "heatmap",
          data: values,
          itemStyle: { borderColor: "#14232a", borderWidth: 2 },
          emphasis: { itemStyle: { borderColor: "#c8e9da", borderWidth: 1 } },
        },
      ],
    },
    context,
    (event) =>
      select({ type: "rhythm", hour: event.value[0], weekday: event.value[1] }),
  );
}

export function rankings(data, kind, context) {
  const items = data.items.slice(0, 12);
  const labelWidth = matchMedia("(max-width:700px)").matches ? 125 : 145;
  chart(
    "rankings",
    `Recorded plays · ${kind}s`,
    {
      grid: { left: labelWidth + 10, right: 38, top: 61, bottom: 27 },
      xAxis: { ...axes(), type: "value", axisLabel: { fontSize: 9 } },
      yAxis: {
        ...axes(),
        type: "category",
        inverse: true,
        data: items.map((item) => item.name),
        axisLabel: {
          fontSize: 10,
          width: labelWidth,
          overflow: "truncate",
          align: "right",
        },
        splitLine: { show: false },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 14,
          data: items.map((item) => ({
            value: item.plays,
            key: item.key,
            name: item.name,
          })),
          itemStyle: { color: "#8cddc5", borderRadius: [0, 3, 3, 0] },
          label: {
            show: true,
            position: "right",
            color: "#c5d2d1",
            fontSize: 9,
            formatter: (event) => number(event.value),
          },
        },
      ],
    },
    context,
    (event) => select({ type: "entity", kind, key: event.data.key }),
  );
}

export function evolution(data, mode, context) {
  const totals = data.buckets.map((_, index) =>
    data.series.reduce((sum, item) => sum + item.counts[index], 0),
  );
  const colors = artistColors(data.series);
  chart(
    "evolution",
    mode === "share"
      ? "Share of recorded artist plays"
      : "Recorded artist plays",
    {
      legend: {
        type: "scroll",
        top: 50,
        left: 0,
        right: 5,
        textStyle: { color: "#a6b7bc", fontSize: 10 },
      },
      grid: { left: 45, right: 15, top: 89, bottom: 60 },
      tooltip: { ...base("", context).tooltip, trigger: "axis" },
      xAxis: {
        ...axes(),
        type: "category",
        boundaryGap: false,
        data: data.buckets,
      },
      yAxis: {
        ...axes(),
        type: "value",
        max: mode === "share" ? 100 : undefined,
        axisLabel: {
          formatter: mode === "share" ? "{value}%" : undefined,
          fontSize: 10,
        },
      },
      dataZoom: [
        {
          type: "slider",
          bottom: 19,
          height: 15,
          borderColor: "#364a50",
          fillerColor: "#517e6c44",
          textStyle: { fontSize: 8, color: "#9bb1b6" },
        },
        { type: "inside" },
      ],
      series: data.series.map((item) => ({
        name: item.name,
        type: "line",
        stack: "plays",
        showSymbol: false,
        areaStyle: { opacity: 0.65 },
        lineStyle: { width: 1 },
        itemStyle: { color: colors.get(item.key) },
        data: item.counts.map((count, index) =>
          mode === "share"
            ? totals[index]
              ? (100 * count) / totals[index]
              : 0
            : count,
        ),
      })),
    },
    context,
    (event) => {
      const item = data.series[event.seriesIndex];
      if (item && item.key !== "other")
        select({ type: "entity", kind: "artist", key: item.key });
    },
  );
}

export function breadth(data, context) {
  chart(
    "breadth",
    "Recorded variety and top-artist share",
    {
      legend: {
        top: 48,
        left: 0,
        textStyle: { color: "#a6b7bc", fontSize: 10 },
      },
      grid: { left: 48, right: 44, top: 82, bottom: 35 },
      tooltip: { ...base("", context).tooltip, trigger: "axis" },
      xAxis: { ...axes(), type: "category", data: data.buckets },
      yAxis: [
        { ...axes(), type: "value" },
        {
          ...axes(),
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { formatter: "{value}%", fontSize: 9 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Artists",
          type: "line",
          showSymbol: false,
          data: data.breadth.map((item) => item.artists),
        },
        {
          name: "Tracks",
          type: "line",
          showSymbol: false,
          lineStyle: { type: "dashed" },
          data: data.breadth.map((item) => item.tracks),
        },
        {
          name: "Top-artist share %",
          type: "line",
          showSymbol: false,
          yAxisIndex: 1,
          data: data.breadth.map((item) => 100 * item.top_artist_share),
        },
      ],
    },
    context,
  );
}

export function comparison(data, context) {
  const items = data.items.slice(0, 10);
  chart(
    "comparison",
    "Artist listening share · equal-length periods",
    {
      legend: {
        top: 49,
        left: 0,
        textStyle: { color: "#a6b7bc", fontSize: 10 },
      },
      grid: { left: 150, right: 40, top: 83, bottom: 30 },
      xAxis: {
        ...axes(),
        type: "value",
        axisLabel: { formatter: "{value}%", fontSize: 9 },
      },
      yAxis: {
        ...axes(),
        type: "category",
        inverse: true,
        data: items.map((item) => item.name),
        axisLabel: {
          width: 140,
          overflow: "truncate",
          fontSize: 10,
          align: "right",
        },
      },
      series: [
        {
          name: "Previous period",
          type: "bar",
          barMaxWidth: 10,
          itemStyle: { color: "#69848e" },
          data: items.map((item) => 100 * item.previous_share),
        },
        {
          name: "Selected period",
          type: "bar",
          barMaxWidth: 10,
          itemStyle: { color: "#8cddc5" },
          data: items.map((item) => 100 * item.current_share),
        },
      ],
    },
    context,
    (event) =>
      select({
        type: "entity",
        kind: "artist",
        key: items[event.dataIndex].key,
      }),
  );
}

export function discoveries(data, context) {
  const windows = [7, 30, 90];
  chart(
    "discovery",
    "First-observed artists and observed return rates",
    {
      legend: {
        type: "scroll",
        top: 48,
        left: 0,
        textStyle: { color: "#a6b7bc", fontSize: 10 },
      },
      grid: { left: 45, right: 45, top: 85, bottom: 46 },
      tooltip: { ...base("", context).tooltip, trigger: "axis" },
      xAxis: {
        ...axes(),
        type: "category",
        data: data.cohorts.map((item) => item.month),
      },
      yAxis: [
        { ...axes(), type: "value" },
        {
          ...axes(),
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { formatter: "{value}%", fontSize: 9 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "First observed",
          type: "bar",
          barMaxWidth: 25,
          itemStyle: { color: "#557d74" },
          data: data.cohorts.map((item) => item.artists),
        },
        ...windows.map((window, index) => ({
          name: `${window}-day return %`,
          type: "line",
          yAxisIndex: 1,
          connectNulls: false,
          showSymbol: data.cohorts.length < 30,
          itemStyle: { color: palette[index] },
          data: data.cohorts.map((item) =>
            item[`eligible_${window}`]
              ? (100 * item[`returned_${window}`]) / item[`eligible_${window}`]
              : null,
          ),
        })),
      ],
    },
    context,
  );
}

export function rediscovery(data, kind, context) {
  chart(
    "rediscovery",
    `Historical ${kind} favorites · analysis date ${data.as_of}`,
    {
      grid: { left: 67, right: 22, top: 70, bottom: 56 },
      xAxis: {
        ...axes(),
        type: "value",
        name: "Days since last recorded play",
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { fontSize: 10 },
      },
      yAxis: {
        ...axes(),
        type: "log",
        name: "Recorded plays (log)",
        nameTextStyle: { fontSize: 9 },
        min: 1,
      },
      tooltip: {
        ...base("", context).tooltip,
        formatter: (event) =>
          `${event.data.name}\n${event.data.artist}\n${number(event.value[1])} recorded plays\n${number(event.value[0])} days since last play`,
      },
      series: [
        {
          type: "scatter",
          data: data.items.map((item) => ({
            value: [item.days_since_last, item.entity.plays],
            name: item.entity.name,
            artist: item.entity.artist,
            key: item.entity.key,
          })),
          symbolSize: (value) => Math.min(25, 8 + Math.log10(value[1] + 1) * 3),
          itemStyle: {
            color: "#8cddc5",
            opacity: 0.7,
            borderColor: "#c4f0de",
            borderWidth: 0.5,
          },
        },
      ],
    },
    context,
    (event) => select({ type: "entity", kind, key: event.data.key }),
  );
}

export function detail(data, context) {
  chart(
    "detail",
    "Recorded plays in the selected period",
    {
      grid: { left: 40, right: 12, top: 62, bottom: 35 },
      tooltip: { ...base("", context).tooltip, trigger: "axis" },
      xAxis: {
        ...axes(),
        type: "category",
        data: data.days.map((item) => item.day),
      },
      yAxis: { ...axes(), type: "value", minInterval: 1 },
      series: [
        {
          type: "line",
          showSymbol: false,
          lineStyle: { width: 1.5 },
          areaStyle: { opacity: 0.12 },
          data: data.days.map((item) => item.plays),
        },
      ],
    },
    context,
  );
}

export function anniversaries(data, context) {
  chart(
    "anniversaries",
    `On this day · ${data.as_of.slice(5)} · earlier years`,
    {
      grid: { left: 55, right: 20, top: 75, bottom: 55 },
      xAxis: {
        ...axes(),
        type: "category",
        data: data.days.map((item) => item.day.slice(0, 4)),
      },
      yAxis: {
        ...axes(),
        type: "value",
        minInterval: 1,
        name: "Recorded plays",
      },
      series: [
        {
          type: "bar",
          data: data.days.map((item) => ({
            value: item.covered ? item.plays : null,
            itemStyle: { color: item.partial ? "#e9c178" : "#8cddc5" },
          })),
          barMaxWidth: 32,
        },
      ],
      tooltip: {
        backgroundColor: "#243a42",
        borderColor: "#476469",
        textStyle: { color: "#edf3ee", fontSize: 11 },
        trigger: "item",
        renderMode: "richText",
        confine: true,
        formatter: (params) => {
          const item = data.days[params.dataIndex];
          return `${item.day}\n${number(item.plays)} recorded plays · ${number(item.artists)} artists${item.partial ? "\nPartial source boundary day" : ""}`;
        },
      },
    },
    context,
    (params) => {
      const item = data.days[params.dataIndex];
      if (item?.covered) select({ type: "day", day: item.day });
    },
  );
}

export function eras(data, context, view) {
  const cells = eraCells(data, view.order, view.threshold);
  const comparable = cells.filter(
    (item) =>
      item.value[2] !== null && item.originalRow !== item.originalColumn,
  );
  const diagonal = cells.filter(
    (item) =>
      item.value[2] !== null && item.originalRow === item.originalColumn,
  );
  const labels = view.order.map((index) => data.periods[index].label);
  const zoom =
    data.periods.length > 36
      ? [
          {
            type: "slider",
            xAxisIndex: 0,
            bottom: 30,
            height: 15,
            start: 0,
            end: 100,
          },
          {
            type: "slider",
            yAxisIndex: 0,
            right: 4,
            width: 15,
            start: 0,
            end: 100,
          },
          { type: "inside", xAxisIndex: 0, filterMode: "none" },
        ]
      : [];
  const title = `Musical eras · ${view.grouped ? "grouped" : "chronological"} ${data.grain === "month" ? "months" : "years"} · ≥${Math.round(view.threshold * 100)}%`;
  chart(
    "eras",
    title,
    {
      animation: false,
      grid: { left: 72, right: 35, top: 75, bottom: 170 },
      xAxis: {
        ...axes(),
        type: "category",
        data: labels,
        axisLabel: { ...axes().axisLabel, rotate: 45 },
        splitArea: { show: true, areaStyle: { color: ["#15232a"] } },
      },
      yAxis: {
        ...axes(),
        type: "category",
        data: labels,
        splitArea: { show: true, areaStyle: { color: ["#15232a"] } },
      },
      visualMap: {
        type: "piecewise",
        seriesIndex: 0,
        dimension: 2,
        pieces: eraBands,
        selectedMode: false,
        orient: "horizontal",
        left: "center",
        bottom: 70,
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 7,
        textStyle: { color: "#c5d2d1", fontSize: 9 },
      },
      graphic: [
        ...base(title, context).graphic,
        {
          type: "text",
          left: "center",
          bottom: 104,
          style: {
            text: "Gray diagonal: self · Blank: no recorded plays",
            fill: "#a6b7bc",
            fontSize: 9,
          },
        },
      ],
      dataZoom: zoom,
      tooltip: {
        backgroundColor: "#243a42",
        borderColor: "#476469",
        textStyle: { color: "#edf3ee", fontSize: 11 },
        trigger: "item",
        renderMode: "richText",
        confine: true,
        formatter: (params) => {
          const item = params.data;
          const left = data.periods[item.originalColumn],
            right = data.periods[item.originalRow];
          const score = item.value[2];
          const self = item.originalColumn === item.originalRow;
          return `${left.label} ↔ ${right.label}\n${percent(score)} artist-share similarity${self ? "\nSelf-comparison · shown in gray" : score < view.threshold ? "\nBelow highlight threshold" : ""}\n${number(left.plays)} / ${number(right.plays)} recorded plays${left.partial || right.partial ? "\nIncludes a partial boundary period" : ""}`;
        },
      },
      series: [
        {
          type: "heatmap",
          data: comparable,
          progressive: 0,
          emphasis: { itemStyle: { borderColor: "#edf3ee", borderWidth: 1 } },
        },
        {
          type: "heatmap",
          data: diagonal,
          progressive: 0,
          itemStyle: { color: "#727981" },
          emphasis: { itemStyle: { borderColor: "#edf3ee", borderWidth: 1 } },
        },
      ],
    },
    context,
    (params) => {
      if (params.data && params.data.value[2] !== null)
        select({
          type: "era",
          reference: params.data.originalColumn,
          comparison: params.data.originalRow,
        });
    },
  );
}

export function library(data, context) {
  const names = {
    name_match: "One exact name",
    unmatched: "No exact name",
    ambiguous: "Multiple candidates",
    unavailable: "Unavailable",
  };
  const colors = {
    name_match: "#6caed6",
    unmatched: "#f0d783",
    ambiguous: "#efa78a",
    unavailable: "#89959c",
  };
  chart(
    "library",
    "Historical entities · current collection name evidence",
    {
      grid: { top: 80, bottom: 55, left: 145, right: 24 },
      xAxis: { ...axes(), type: "value", minInterval: 1 },
      yAxis: {
        ...axes(),
        type: "category",
        inverse: true,
        data: data.coverage.map((item) => names[item.status]),
      },
      series: [
        {
          type: "bar",
          data: data.coverage.map((item) => ({
            value: item.entities,
            status: item.status,
            itemStyle: { color: colors[item.status] },
          })),
          label: { show: true, position: "right", color: "#edf3ee" },
        },
      ],
      graphic: [
        {
          type: "text",
          left: 0,
          bottom: 2,
          style: {
            text: `Collection published ${data.source.published_at || "unknown"}\n${data.source.state} · name evidence; membership is not historical`,
            fill: "#a6b7bc",
            fontSize: 11,
          },
        },
      ],
    },
    context,
    (params) => select({ type: "library-status", status: params.data.status }),
  );
}

export function exportChart(id, context) {
  const instance = instances.get(id);
  if (!instance) return;
  const dataURL = instance.getDataURL({
    type: "png",
    pixelRatio: 2,
    backgroundColor: "#14232a",
  });
  fetch(dataURL)
    .then((response) => response.blob())
    .then((blob) =>
      download(`listening-${id}-${context.from}-${context.to}.png`, blob),
    );
}

export function resizeCharts() {
  for (const instance of instances.values()) {
    if (!instance.isDisposed()) instance.resize();
  }
}

export function clearCharts() {
  for (const instance of instances.values()) instance.dispose();
  instances.clear();
}
