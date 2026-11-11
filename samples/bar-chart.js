// 72-Hour base prices for Nov 8 (Yesterday), Nov 9 (Today), and Nov 10 (Tomorrow)
const hourlyPrices = [
	33.62, 33.51, 33.06, 29.29, 28.02, 28.32, 27.96, 28.34, 30.06, 30.57, 30.51, 30.01, 30.11, 29.73,
	39.33, 43.73, 47.54, 47.71, 47.55, 50.3, 50.21, 47.09, 24.86, 35.76,

	29.49, 34.97, 33.71, 32.68, 33.43, 33.41, 31.58, 41.29, 52.26, 55.39, 58.44, 53.07, 47.16, 54.37,
	58.44, 44.65, 70.56, 62.71, 76.73, 71.56, 66.55, 58.44, 47.24, 43.91,

	22.55, 32.96, 32.92, 32.76, 34.08, 38.46, 32.49, 43.25, 53.07, 49.95, 54.61, 49.33, 51.68, 54.33,
	47.92, 51.43, 78.06, 70.73, 77.42, 68.26, 67.93, 59.57, 46.31, 41.85,
];

const days = ["08 Nov", "09 Nov", "10 Nov"];
const periods = [];
const prices = [];

// Generate 288 distinct 15-minute blocks (3 days x 24 hrs x 4 blocks)
// Applies realistic micro-fluctuations to the hourly base price to simulate the 15-min market resolution
let hourIndex = 0;
for (let d = 0; d < days.length; d++) {
	for (let h = 0; h < 24; h++) {
		const base = hourlyPrices[hourIndex];
		prices.push(+(base - 0.2).toFixed(2));
		prices.push(+(base + 0.1).toFixed(2));
		prices.push(+(base + 0.5).toFixed(2));
		prices.push(+(base - 0.1).toFixed(2));

		for (let m = 0; m < 60; m += 15) {
			periods.push(`${days[d]} ${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`);
		}
		hourIndex++;
	}
}

// Simulating the exact current time marker
const currentPeriod = "09 Nov 14:30";

option = {
	backgroundColor: "#10141c",
	title: {
		text: "⚡ 72-Hour EV Charging Blocks",
		subtext: "Nord Pool 15-Min Resolution (cents/kWh)",
		left: "center",
		top: 15,
		textStyle: { color: "#ffffff", fontSize: 20, fontWeight: "600", fontFamily: "sans-serif" },
		subtextStyle: { color: "#8b9baf", fontSize: 13 },
	},
	tooltip: {
		trigger: "axis",
		axisPointer: {
			type: "shadow",
			shadowStyle: { color: "rgba(255, 255, 255, 0.05)" },
		},
		backgroundColor: "rgba(16, 20, 28, 0.95)",
		borderColor: "#2a3342",
		borderWidth: 1,
		padding: [12, 16],
		borderRadius: 8,
		textStyle: { color: "#fff" },
		formatter: function (params) {
			const startTime = params[0].name;
			const dayStr = startTime.slice(0, 6);
			const timeStr = startTime.slice(7);

			// Calculate the strict 15-minute window for the tooltip
			let [hr, mn] = timeStr.split(":").map(Number);
			mn += 15;
			if (mn === 60) {
				mn = 0;
				hr += 1;
			}
			if (hr === 24) {
				hr = 0;
			}
			const endStr = `${hr.toString().padStart(2, "0")}:${mn.toString().padStart(2, "0")}`;

			return `
        <div style="font-size: 12px; color: #8b9baf; margin-bottom: 4px;">${dayStr}</div>
        <div style="font-size: 16px; font-weight: bold; margin-bottom: 8px;">${timeStr} - ${endStr}</div>
        <div>${params[0].marker} <span style="color: #8b9baf;">Price:</span> <b style="font-size: 16px;">${params[0].value}</b> c/kWh</div>
      `;
		},
	},
	grid: { left: "3%", right: "10%", bottom: "10%", top: "22%", containLabel: true },
	xAxis: {
		type: "category",
		data: periods,
		axisLine: { show: false },
		axisTick: { show: false },
		axisLabel: {
			color: "#8b9baf",
			formatter: (value) => value.split(" ").join("\n"),
			interval: 15, // Shows label every 4 hours (16th block) so the 288 points don't overlap
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
		// Auto-zooms to show slightly before current time up to tomorrow morning
		{ type: "inside", start: 45, end: 80 },
		{
			type: "slider",
			bottom: 10,
			start: 45,
			end: 80,
			textStyle: { color: "#8b9baf" },
			borderColor: "#1f2937",
		},
	],
	visualMap: {
		top: 50,
		right: 10,
		textStyle: { color: "#8b9baf" },
		pieces: [
			{ lte: 30, color: "#10b981", label: "Cheap (<30c)" },
			{ gt: 30, lte: 45, color: "#f59e0b", label: "Normal (30-45c)" },
			{ gt: 45, lte: 60, color: "#f97316", label: "High (45-60c)" },
			{ gt: 60, color: "#ef4444", label: "Peak (>60c)" },
		],
		outOfRange: { color: "#999" },
	},
	series: [
		{
			name: "Price",
			type: "bar",
			barCategoryGap: "5%",
			itemStyle: {
				borderRadius: [2, 2, 0, 0],
			},
			data: prices,
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
						yAxis: 30,
						name: "Target",
						label: {
							position: "insideEndTop",
							formatter: "Charge Limit",
							color: "#10b981",
							fontWeight: "bold",
						},
					},
					{
						xAxis: currentPeriod,
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
						{ xAxis: currentPeriod },
					],
					[
						{
							name: "✨ Optimal Window",
							xAxis: "10 Nov 00:00",
							itemStyle: { color: "rgba(16, 185, 129, 0.1)" },
							label: {
								position: "insideTop",
								color: "#10b981",
								fontWeight: "bold",
								padding: [25, 0, 0, 0],
							},
						},
						{ xAxis: "10 Nov 05:00" },
					],
				],
			},
		},
	],
};
