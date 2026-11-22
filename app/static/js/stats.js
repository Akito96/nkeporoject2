const STATUS_TITLES = {
    new: "Новый",
    paid: "Оплачен",
    done: "Выполнен",
    cancelled: "Отменён",
};

const COFFEE_PALETTE = [
    "#8c4a27",
    "#c27d38",
    "#5c3a21",
    "#d4a373",
    "#3d2b1f",
    "#a47148",
    "#7f5539",
];

let revenueChart = null;
let topProductsChart = null;
let categoryChart = null;

let currentTopProducts = [];
let currentStatuses = [];

function formatRub(value) {
    return `${Number(value || 0).toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })} ₽`;
}

function renderTableRows(tableId, rows, columns) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    if (!tbody) {
        return;
    }
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="${columns.length}">Нет данных за выбранный период.</td></tr>`;
        return;
    }
    tbody.innerHTML = rows
        .map(
            (row) =>
                `<tr>${columns.map((col) => `<td>${col.render(row)}</td>`).join("")}</tr>`
        )
        .join("");
}

function attachTableSorting(tableId, getData, columns) {
    const table = document.getElementById(tableId);
    if (!table) {
        return;
    }
    const headers = table.querySelectorAll("th[data-sort-key]");
    headers.forEach((th) => {
        const handleSort = () => {
            const key = th.dataset.sortKey;
            const type = th.dataset.sortType;
            const nextDir = th.dataset.sortDir === "asc" ? "desc" : "asc";

            headers.forEach((h) => {
                delete h.dataset.sortDir;
                h.classList.remove("sort-asc", "sort-desc");
            });
            th.dataset.sortDir = nextDir;
            th.classList.add(nextDir === "asc" ? "sort-asc" : "sort-desc");

            const sorted = [...getData()].sort((a, b) => {
                if (type === "num") {
                    const diff = Number(a[key]) - Number(b[key]);
                    return nextDir === "asc" ? diff : -diff;
                }
                const cmp = String(a[key]).localeCompare(String(b[key]), "ru");
                return nextDir === "asc" ? cmp : -cmp;
            });
            renderTableRows(tableId, sorted, columns);
        };

        th.addEventListener("click", handleSort);
        th.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                handleSort();
            }
        });
    });
}

function renderCharts(data) {
    if (typeof window.Chart === "undefined") {
        return;
    }

    const dayCtx = document.getElementById("chart-revenue-day");
    if (dayCtx) {
        if (revenueChart) {
            revenueChart.destroy();
        }
        revenueChart = new window.Chart(dayCtx, {
            type: "line",
            data: {
                labels: data.revenue_by_day.map((d) => d.day),
                datasets: [
                    {
                        label: "Выручка (₽)",
                        data: data.revenue_by_day.map((d) => Number(d.revenue)),
                        borderColor: "#8c4a27",
                        backgroundColor: "rgba(140, 74, 39, 0.14)",
                        fill: true,
                        tension: 0.25,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        });
    }

    const prodCtx = document.getElementById("chart-top-products");
    if (prodCtx) {
        if (topProductsChart) {
            topProductsChart.destroy();
        }
        topProductsChart = new window.Chart(prodCtx, {
            type: "bar",
            data: {
                labels: data.top_products.map((p) => p.product_name),
                datasets: [
                    {
                        label: "Выручка (₽)",
                        data: data.top_products.map((p) => Number(p.revenue)),
                        backgroundColor: "#8c4a27",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            },
        });
    }

    const catCtx = document.getElementById("chart-revenue-category");
    if (catCtx) {
        if (categoryChart) {
            categoryChart.destroy();
        }
        categoryChart = new window.Chart(catCtx, {
            type: "doughnut",
            data: {
                labels: data.revenue_by_category.map((c) => c.category_name),
                datasets: [
                    {
                        data: data.revenue_by_category.map((c) => Number(c.revenue)),
                        backgroundColor: COFFEE_PALETTE,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
            },
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const exportLink = document.getElementById("stats-export-csv");
    const periodLabel = document.getElementById("stats-period-label");
    const dateFromInput = document.getElementById("stats-date-from");
    const dateToInput = document.getElementById("stats-date-to");
    const rangeForm = document.getElementById("stats-range-form");
    const presetButtons = document.querySelectorAll("[data-stats-days]");

    const productColumns = [
        { render: (row) => row.product_name },
        { render: (row) => String(row.quantity_sold) },
        { render: (row) => `<strong>${formatRub(row.revenue)}</strong>` },
    ];
    const statusColumns = [
        {
            render: (row) =>
                `<span class="status-badge status-${row.status}">${row.status_label}</span>`,
        },
        { render: (row) => String(row.orders_count) },
        { render: (row) => `<strong>${formatRub(row.revenue)}</strong>` },
    ];

    attachTableSorting("table-top-products", () => currentTopProducts, productColumns);
    attachTableSorting("table-orders-status", () => currentStatuses, statusColumns);

    const loadStats = async (params) => {
        const query = new URLSearchParams(params).toString();
        if (exportLink) {
            exportLink.href = `/admin/api/stats/export.csv?${query}`;
        }

        const resp = await fetch(`/admin/api/stats/summary?${query}`, {
            credentials: "same-origin",
        });
        const data = await resp.json().catch(() => null);
        if (!resp.ok) {
            if (typeof window.showAdminFlash === "function") {
                window.showAdminFlash(
                    (data && data.detail) || "Не удалось загрузить статистику.",
                    "error"
                );
            }
            return;
        }

        if (periodLabel) {
            periodLabel.textContent = `Период: ${data.date_from} — ${data.date_to}`;
        }
        if (dateFromInput) {
            dateFromInput.value = data.date_from;
        }
        if (dateToInput) {
            dateToInput.value = data.date_to;
        }

        document.getElementById("kpi-revenue").textContent = formatRub(data.total_revenue);
        document.getElementById("kpi-orders").textContent = String(data.total_orders);
        document.getElementById("kpi-avg-check").textContent = formatRub(data.average_check);
        document.getElementById("kpi-active-orders").textContent = String(
            data.paid_or_active_orders
        );

        currentTopProducts = data.top_products;
        currentStatuses = data.orders_by_status.map((item) => ({
            ...item,
            status_label: STATUS_TITLES[item.status] || item.status,
        }));

        renderTableRows("table-top-products", currentTopProducts, productColumns);
        renderTableRows("table-orders-status", currentStatuses, statusColumns);
        renderCharts(data);
    };

    presetButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            presetButtons.forEach((b) => b.classList.remove("chip-active"));
            btn.classList.add("chip-active");
            loadStats({ days: btn.dataset.statsDays });
        });
    });

    if (rangeForm) {
        rangeForm.addEventListener("submit", (event) => {
            event.preventDefault();
            const fromVal = dateFromInput && dateFromInput.value;
            const toVal = dateToInput && dateToInput.value;
            if (!fromVal || !toVal) {
                return;
            }
            presetButtons.forEach((b) => b.classList.remove("chip-active"));
            loadStats({ date_from: fromVal, date_to: toVal });
        });
    }

    loadStats({ days: "30" });
});
