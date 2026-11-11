const hours = [
	"08 Nov 00:00",
	"08 Nov 01:00",
	"08 Nov 02:00",
	"08 Nov 03:00",
	"08 Nov 04:00",
	"08 Nov 05:00",
	"08 Nov 06:00",
	"08 Nov 07:00",
	"08 Nov 08:00",
	"08 Nov 09:00",
	"08 Nov 10:00",
	"08 Nov 11:00",
	"08 Nov 12:00",
	"08 Nov 13:00",
	"08 Nov 14:00",
	"08 Nov 15:00",
	"08 Nov 16:00",
	"08 Nov 17:00",
	"08 Nov 18:00",
	"08 Nov 19:00",
	"08 Nov 20:00",
	"08 Nov 21:00",
	"08 Nov 22:00",
	"08 Nov 23:00",
	"09 Nov 00:00",
	"09 Nov 01:00",
	"09 Nov 02:00",
	"09 Nov 03:00",
	"09 Nov 04:00",
	"09 Nov 05:00",
	"09 Nov 06:00",
	"09 Nov 07:00",
	"09 Nov 08:00",
	"09 Nov 09:00",
	"09 Nov 10:00",
	"09 Nov 11:00",
	"09 Nov 12:00",
	"09 Nov 13:00",
	"09 Nov 14:00",
	"09 Nov 15:00",
	"09 Nov 16:00",
	"09 Nov 17:00",
	"09 Nov 18:00",
	"09 Nov 19:00",
	"09 Nov 20:00",
	"09 Nov 21:00",
	"09 Nov 22:00",
	"09 Nov 23:00",
	"10 Nov 00:00",
	"10 Nov 01:00",
	"10 Nov 02:00",
	"10 Nov 03:00",
	"10 Nov 04:00",
	"10 Nov 05:00",
	"10 Nov 06:00",
	"10 Nov 07:00",
	"10 Nov 08:00",
	"10 Nov 09:00",
	"10 Nov 10:00",
	"10 Nov 11:00",
	"10 Nov 12:00",
	"10 Nov 13:00",
	"10 Nov 14:00",
	"10 Nov 15:00",
	"10 Nov 16:00",
	"10 Nov 17:00",
	"10 Nov 18:00",
	"10 Nov 19:00",
	"10 Nov 20:00",
	"10 Nov 21:00",
	"10 Nov 22:00",
	"10 Nov 23:00",
];

const prices = [
	// 08 Nov (Yesterday)
	33.62, 33.51, 33.06, 29.29, 28.02, 28.32, 27.96, 28.34, 30.06, 30.57, 30.51, 30.01, 30.11, 29.73,
	39.33, 43.73, 47.54, 47.71, 47.55, 50.3, 50.21, 47.09, 24.86, 35.76,
	// 09 Nov (Today)
	29.49, 34.97, 33.71, 32.68, 33.43, 33.41, 31.58, 41.29, 52.26, 55.39, 58.44, 53.07, 47.16, 54.37,
	58.44, 44.65, 70.56, 62.71, 76.73, 71.56, 66.55, 58.44, 47.24, 43.91,
	// 10 Nov (Tomorrow)
	22.55, 32.96, 32.92, 32.76, 34.08, 38.46, 32.49, 43.25, 53.07, 49.95, 54.61, 49.33, 51.68, 54.33,
	47.92, 51.43, 78.06, 70.73, 77.42, 68.26, 67.93, 59.57, 46.31, 41.85,
];

// Simulating the current live time
const currentHour = "09 Nov 14:00";

option = {
	backgroundColor: "#10141c",
	title: {
		text: "⚡ EV Smart Charge Tracker",
		subtext: "72-Hour Spot Prices (cents/kWh)",
		left: "center",
		top: 15,
		textStyle: { color: "#ffffff", fontSize: 20, fontWeight: "600", fontFamily: "sans-serif" },
		subtextStyle: { color: "#8b9baf", fontSize: 13 },
	},
	tooltip: {
		trigger: "axis",
		backgroundColor: "rgba(16, 20, 28, 0.9)",
		borderColor: "#2a3342",
		borderWidth: 1,
		padding: [12, 16],
		borderRadius: 8,
		textStyle: { color: "#fff" },
		formatter: function (params) {
			const idx = params[0].dataIndex;
			const nextHourStr = idx < hours.length - 1 ? hours[idx + 1].slice(7) : "24:00";
			const dayStr = hours[idx].slice(0, 6);
			const timeWindow = `${hours[idx].slice(7)} - ${nextHourStr}`;

			return `
        <div style="font-size: 12px; color: #8b9baf; margin-bottom: 4px;">${dayStr}</div>
        <div style="font-size: 16px; font-weight: bold; margin-bottom: 8px;">${timeWindow}</div>
        <div>${params[0].marker} <span style="color: #8b9baf;">Cost:</span> <b style="font-size: 16px;">${params[0].value}</b> c/kWh</div>
      `;
		},
	},
	grid: { left: "3%", right: "10%", bottom: "10%", top: "22%", containLabel: true },
	xAxis: {
		type: "category",
		boundaryGap: false,
		data: hours,
		axisLine: { show: false },
		axisTick: { show: false },
		axisLabel: {
			color: "#8b9baf",
			formatter: (value) => value.split(" ").join("\n"),
			padding: [10, 0, 0, 0],
		},
	},
	yAxis: {
		type: "value",
		name: "cents / kWh",
		nameTextStyle: { color: "#8b9baf", padding: [0, 0, 10, 0] },
		min: 20,
		axisLine: { show: false },
		axisTick: { show: false },
		axisLabel: { color: "#8b9baf" },
		splitLine: { lineStyle: { color: "#1f2937", type: "dashed" } },
	},
	dataZoom: [
		{ type: "inside", start: 30, end: 100 },
		{
			type: "slider",
			bottom: 10,
			start: 30,
			end: 100,
			textStyle: { color: "#8b9baf" },
			borderColor: "#1f2937",
		},
	],
	visualMap: {
		top: 50,
		right: 10,
		textStyle: { color: "#8b9baf" },
		pieces: [
			{ lte: 35, color: "#10b981", label: "Cheap (<35c)" },
			{ gt: 35, lte: 50, color: "#f59e0b", label: "Normal (35-50c)" },
			{ gt: 50, lte: 65, color: "#f97316", label: "High (50-65c)" },
			{ gt: 65, color: "#ef4444", label: "Peak (>65c)" },
		],
		outOfRange: { color: "#999" },
	},
	series: [
		{
			name: "Price",
			type: "line",
			step: "start",
			showSymbol: false,
			lineStyle: { width: 3, shadowColor: "rgba(0, 0, 0, 0.5)", shadowBlur: 10, shadowOffsetY: 6 },
			data: prices,
			areaStyle: { opacity: 0.1 },

			markPoint: {
				symbol: "pin",
				symbolSize: 45,
				label: { color: "#fff", fontSize: 10, fontWeight: "bold" },
				data: [
					{ type: "min", name: "Cheapest", itemStyle: { color: "#10b981" } },
					{ type: "max", name: "Peak", itemStyle: { color: "#ef4444" } },
				],
			},

			markLine: {
				symbol: ["none", "none"],
				data: [
					{
						yAxis: 35,
						name: "Target",
						label: {
							position: "insideEndTop",
							formatter: "Charge Limit",
							color: "#10b981",
							fontWeight: "bold",
						},
					},
					{
						xAxis: currentHour,
						label: {
							formatter: "Now",
							position: "insideStartTop",
							color: "#3b82f6",
							fontWeight: "bold",
						},
						lineStyle: { color: "#3b82f6", type: "solid", width: 2, opacity: 0.8 },
					},
				],
				lineStyle: { color: "#10b981", type: "dashed", width: 1.5, opacity: 0.8 },
			},

			markArea: {
				data: [
					[
						{
							name: "Past Data",
							xAxis: "08 Nov 00:00",
							itemStyle: { color: "rgba(0, 0, 0, 0.6)" },
							label: { position: "insideTopLeft", color: "#6b7280", padding: [25, 0, 0, 15] },
						},
						{ xAxis: currentHour },
					],
					[
						{
							name: "✨ Optimal Charge Window",
							xAxis: "10 Nov 00:00",
							itemStyle: { color: "rgba(16, 185, 129, 0.1)" },
							label: {
								position: "insideTop",
								color: "#10b981",
								fontWeight: "bold",
								padding: [25, 0, 0, 0],
							},
						},
						{ xAxis: "10 Nov 05:00" }, // Prices begin to climb after 05:00
					],
				],
			},
		},
	],
};
