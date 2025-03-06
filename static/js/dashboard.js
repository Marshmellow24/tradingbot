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
      .map(([key, value]) => createConfigItem(key, value, "order_settings"))
      .join("");
    document.getElementById("orderSettings").innerHTML = orderSettingsHtml;

    // Update Timeout Settings
    const timeouts = orderSettings.timeouts || {};
    const timeoutsHtml = Object.entries(timeouts)
      .map(([key, value]) =>
        createConfigItem(key, value, "order_settings.timeouts")
      )
      .join("");
    document.getElementById("timeoutSettings").innerHTML = timeoutsHtml;

    // Update Override Settings
    const overrides = orderSettings.overrides || {};
    const overridesHtml = Object.entries(overrides)
      .map(([key, value]) =>
        createConfigItem(key, value, "order_settings.overrides")
      )
      .join("");
    document.getElementById("overrideSettings").innerHTML = overridesHtml;
  } catch (error) {
    console.error("Error updating config:", error);
  }
}

function createConfigItem(key, value, path) {
  const isBoolean = typeof value === "boolean";
  const inputHtml = isBoolean
    ? createToggleSwitch(value)
    : createNumberInput(value);

  return `
        <div class="config-item" data-path="${path}.${key}">
            <span class="config-label">${formatKey(key)}</span>
            <div class="config-value">
                ${inputHtml}
                <button onclick="saveConfig(this)" title="Save changes">
                    <svg width="16" height="16" viewBox="0 0 16 16">
                        <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0z" fill="currentColor"/>
                    </svg>
                </button>
            </div>
        </div>
    `;
}

function createToggleSwitch(value) {
  return `
        <label class="toggle-switch">
            <input type="checkbox" ${
              value ? "checked" : ""
            } onchange="saveConfig(this)">
            <span class="toggle-slider"></span>
        </label>
    `;
}

function createNumberInput(value) {
  return `
        <input type="number" value="${value || ""}" 
               placeholder="Default" 
               step="any"
               onchange="saveConfig(this)">
    `;
}

async function saveConfig(element) {
  const configItem = element.closest(".config-item");
  const path = configItem.dataset.path;
  const input = configItem.querySelector("input");
  const value =
    input.type === "checkbox"
      ? input.checked
      : input.value === ""
      ? null
      : !isNaN(input.value)
      ? parseFloat(input.value)
      : input.value;

  try {
    const response = await fetch("/config/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [path]: value }),
    });

    if (!response.ok) throw new Error("Failed to update config");

    // Show success feedback
    const button = configItem.querySelector("button");
    button.style.color = "var(--success-color)";
    setTimeout(() => (button.style.color = ""), 1000);
  } catch (error) {
    console.error("Error saving config:", error);
    // Show error feedback
    input.style.borderColor = "var(--danger-color)";
    setTimeout(() => (input.style.borderColor = ""), 1000);
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
