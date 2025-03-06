let profitChart;

async function updateDashboard() {
  try {
    // Update connection status
    const connStatus = await fetch("/connection_status");
    const connData = await connStatus.json();
    updateConnectionStatus(connData.connected);

    // Update trade logs
    const response = await fetch("/trade_logs");
    const data = await response.json();
    updateStats(data.trade_logs);
    updateTradeTable(data.trade_logs);
    updateProfitChart(data.trade_logs);

    // Update config
    await updateConfig();
  } catch (error) {
    console.error("Error updating dashboard:", error);
  }
}

function updateConnectionStatus(connected) {
  const statusDot = document.querySelector(".status-dot");
  const statusText = document.querySelector(".status-text");

  if (connected) {
    statusDot.classList.add("connected");
    statusText.textContent = "Connected";
  } else {
    statusDot.classList.remove("connected");
    statusText.textContent = "Disconnected";
  }
}

function updateStats(trades) {
  const totalTrades = trades.length;
  const profitableTrades = trades.filter((t) => t.result === "Profit").length;
  const totalProfit = trades.reduce((sum, t) => sum + t.profit, 0);
  const winRate = totalTrades
    ? ((profitableTrades / totalTrades) * 100).toFixed(1)
    : 0;

  document.getElementById("totalTrades").textContent = totalTrades;
  document.getElementById("winRate").textContent = `${winRate}%`;
  document.getElementById("totalProfit").textContent = `$${totalProfit.toFixed(
    2
  )}`;
}

function updateTradeTable(trades) {
  const tbody = document.getElementById("tradeTable");
  tbody.innerHTML = "";

  trades
    .slice(-6)
    .reverse()
    .forEach((trade) => {
      const row = tbody.insertRow();
      const time = new Date(trade.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });

      row.innerHTML = `
            <td>${time}</td>
            <td>${trade.symbol}</td>
            <td>${trade.parentFillPrice.toFixed(
              2
            )} → ${trade.childFillPrice.toFixed(2)}</td>
            <td>${trade.timeframe}</td>
            <td class="${trade.profit >= 0 ? "profit" : "loss"}">
                ${trade.profit >= 0 ? "+" : ""}$${trade.profit.toFixed(2)}
            </td>
        `;
    });
}
function updateProfitChart(trades) {
  const ctx = document.getElementById("profitCanvas");

  if (!profitChart) {
    profitChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Cumulative Profit",
            data: [],
            borderColor: "#34C759",
            backgroundColor: "rgba(52, 199, 89, 0.1)",
            fill: true,
            tension: 0.4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false, // This is crucial
        interaction: {
          intersect: false,
          mode: "index",
        },
        plugins: {
          legend: {
            position: "top",
          },
          tooltip: {
            backgroundColor: "rgba(255, 255, 255, 0.9)",
            titleColor: "#1D1D1F",
            bodyColor: "#1D1D1F",
            borderColor: "#E5E5E5",
            borderWidth: 1,
            padding: 10,
            displayColors: false,
            callbacks: {
              label: (context) => `Profit: $${context.parsed.y.toFixed(2)}`,
            },
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: {
              color: "rgba(0, 0, 0, 0.05)",
            },
          },
          x: {
            grid: {
              display: false,
            },
          },
        },
      },
    });
  }

  let cumulative = 0;
  const data = trades.map((t) => {
    cumulative += t.profit;
    return cumulative;
  });

  const labels = trades.map((t) => new Date(t.timestamp).toLocaleTimeString());

  profitChart.data.labels = labels;
  profitChart.data.datasets[0].data = data;
  profitChart.update();
}

async function updateConfig() {
  try {
    const response = await fetch("/config");
    const data = await response.json();
    const config = data.config;

    // Update Order Settings
    const orderSettings = config.order_settings || {};
    const orderSettingsHtml = Object.entries(orderSettings)
      .filter(([key]) => !["overrides", "timeouts"].includes(key))
      .map(
        ([key, value]) => `
        <div class="config-item">
          <span class="config-label">${formatKey(key)}</span>
          <span class="config-value ${
            value === true ? "enabled" : value === false ? "disabled" : ""
          }">${value}</span>
        </div>
      `
      )
      .join("");
    document.getElementById("orderSettings").innerHTML = orderSettingsHtml;

    // Update Timeout Settings
    const timeouts = orderSettings.timeouts || {};
    const timeoutsHtml = Object.entries(timeouts)
      .map(
        ([key, value]) => `
        <div class="config-item">
          <span class="config-label">${formatKey(key)}</span>
          <span class="config-value">${value}s</span>
        </div>
      `
      )
      .join("");
    document.getElementById("timeoutSettings").innerHTML = timeoutsHtml;

    // Update Override Settings
    const overrides = orderSettings.overrides || {};
    const overridesHtml = Object.entries(overrides)
      .map(
        ([key, value]) => `
        <div class="config-item">
          <span class="config-label">${formatKey(key)}</span>
          <span class="config-value">${value ?? "Default"}</span>
        </div>
      `
      )
      .join("");
    document.getElementById("overrideSettings").innerHTML = overridesHtml;
  } catch (error) {
    console.error("Error updating config:", error);
  }
}

function formatKey(key) {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Update dashboard every 5 seconds
setInterval(updateDashboard, 5000);
updateDashboard();
