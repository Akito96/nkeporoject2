function getAdminCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie.split(";").map((item) => item.trim());
    for (const part of parts) {
        if (part.startsWith(prefix)) {
            return decodeURIComponent(part.slice(prefix.length));
        }
    }
    return "";
}

function adminHeaders(isJson = true) {
    const headers = {};
    if (isJson) {
        headers["Content-Type"] = "application/json";
    }
    const csrf = getAdminCookie("csrf_token");
    if (csrf) {
        headers["X-CSRF-Token"] = csrf;
    }
    return headers;
}

function showAdminFlash(message, type = "success") {
    const box = document.getElementById("admin-flash");
    if (!box) {
        return;
    }
    box.textContent = message;
    box.classList.remove("alert-success", "alert-error");
    box.classList.add(type === "error" ? "alert-error" : "alert-success");
    box.hidden = false;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function reloadWithFlash(message, type = "success") {
    const url = new URL(window.location.href);
    url.searchParams.set("flash", message);
    url.searchParams.set("flash_type", type);
    window.location.href = url.toString();
}

function parseApiError(data, fallback) {
    if (!data) {
        return fallback;
    }
    if (typeof data.detail === "string") {
        return data.detail;
    }
    if (Array.isArray(data.detail) && data.detail.length > 0) {
        return data.detail.map((e) => e.msg || fallback).join(" ");
    }
    return fallback;
}

document.addEventListener("DOMContentLoaded", () => {
    // --- Категории ---
    const catForm = document.getElementById("admin-category-form");
    const catList = document.getElementById("admin-categories-list");
    const catReset = document.getElementById("cat-reset-btn");
    const catTitle = document.getElementById("cat-form-title");

    if (catForm) {
        const resetCatForm = () => {
            catForm.reset();
            catForm.elements.category_id.value = "";
            if (catTitle) {
                catTitle.textContent = "Новая категория";
            }
            if (catReset) {
                catReset.hidden = true;
            }
        };

        if (catReset) {
            catReset.addEventListener("click", resetCatForm);
        }

        catForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const id = catForm.elements.category_id.value.trim();
            const name = catForm.elements.name.value.trim();
            const slug = catForm.elements.slug.value.trim() || null;

            if (name.length < 2) {
                showAdminFlash("Название категории должно содержать минимум 2 символа.", "error");
                return;
            }

            const resp = await fetch(
                id ? `/admin/api/categories/${id}` : "/admin/api/categories",
                {
                    method: id ? "PATCH" : "POST",
                    headers: adminHeaders(true),
                    credentials: "same-origin",
                    body: JSON.stringify({ name, slug }),
                }
            );
            const data = await resp.json().catch(() => null);
            if (!resp.ok) {
                showAdminFlash(parseApiError(data, "Не удалось сохранить категорию."), "error");
                return;
            }
            reloadWithFlash(id ? "Категория обновлена." : "Категория создана.");
        });

        if (catList) {
            catList.addEventListener("click", async (event) => {
                const row = event.target.closest("[data-category-id]");
                if (!row) {
                    return;
                }
                const id = row.dataset.categoryId;

                if (event.target.closest("[data-edit-category]")) {
                    catForm.elements.category_id.value = id;
                    catForm.elements.name.value = row.dataset.name || "";
                    catForm.elements.slug.value = row.dataset.slug || "";
                    if (catTitle) {
                        catTitle.textContent = `Редактирование категории #${id}`;
                    }
                    if (catReset) {
                        catReset.hidden = false;
                    }
                    return;
                }

                if (event.target.closest("[data-delete-category]")) {
                    if (!window.confirm("Удалить категорию?")) {
                        return;
                    }
                    const resp = await fetch(`/admin/api/categories/${id}`, {
                        method: "DELETE",
                        headers: adminHeaders(false),
                        credentials: "same-origin",
                    });
                    if (!resp.ok) {
                        const data = await resp.json().catch(() => null);
                        showAdminFlash(parseApiError(data, "Не удалось удалить категорию."), "error");
                        return;
                    }
                    reloadWithFlash("Категория удалена.");
                }
            });
        }
    }

    // --- Товары и загрузка фото ---
    const prodForm = document.getElementById("admin-product-form");
    const prodList = document.getElementById("admin-products-list");
    const prodReset = document.getElementById("prod-reset-btn");
    const prodTitle = document.getElementById("product-form-title");
    const fileInput = document.getElementById("prod-image-file");

    if (fileInput && prodForm) {
        fileInput.addEventListener("change", async () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) {
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                showAdminFlash("Файл слишком большой (максимум 5 МБ).", "error");
                fileInput.value = "";
                return;
            }
            const formData = new FormData();
            formData.append("file", file);

            const resp = await fetch("/admin/api/uploads", {
                method: "POST",
                headers: adminHeaders(false),
                credentials: "same-origin",
                body: formData,
            });
            const data = await resp.json().catch(() => null);
            if (!resp.ok) {
                showAdminFlash(parseApiError(data, "Ошибка загрузки изображения."), "error");
                return;
            }
            prodForm.elements.image.value = data.url;
            showAdminFlash("Фото успешно загружено.");
        });
    }

    if (prodForm) {
        const resetProdForm = () => {
            prodForm.reset();
            prodForm.elements.product_id.value = "";
            prodForm.elements.is_active.checked = true;
            if (prodTitle) {
                prodTitle.textContent = "Новый товар";
            }
            if (prodReset) {
                prodReset.hidden = true;
            }
        };

        if (prodReset) {
            prodReset.addEventListener("click", resetProdForm);
        }

        prodForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const id = prodForm.elements.product_id.value.trim();
            const categoryId = Number(prodForm.elements.category_id.value);
            const name = prodForm.elements.name.value.trim();
            const price = prodForm.elements.price.value;
            const stock = Number(prodForm.elements.stock.value);

            if (!categoryId || name.length < 2 || price === "" || Number(price) < 0 || stock < 0) {
                showAdminFlash("Проверьте название, категорию, цену и остаток.", "error");
                return;
            }

            const payload = {
                category_id: categoryId,
                name,
                description: prodForm.elements.description.value.trim(),
                price,
                stock,
                image: prodForm.elements.image.value.trim() || null,
                is_active: prodForm.elements.is_active.checked,
            };

            const resp = await fetch(
                id ? `/admin/api/products/${id}` : "/admin/api/products",
                {
                    method: id ? "PATCH" : "POST",
                    headers: adminHeaders(true),
                    credentials: "same-origin",
                    body: JSON.stringify(payload),
                }
            );
            const data = await resp.json().catch(() => null);
            if (!resp.ok) {
                showAdminFlash(parseApiError(data, "Не удалось сохранить товар."), "error");
                return;
            }
            reloadWithFlash(id ? "Товар обновлён." : "Товар добавлен.");
        });

        if (prodList) {
            prodList.addEventListener("click", async (event) => {
                const row = event.target.closest("[data-product-id]");
                if (!row) {
                    return;
                }
                const id = row.dataset.productId;

                if (event.target.closest("[data-edit-product]")) {
                    prodForm.elements.product_id.value = id;
                    prodForm.elements.name.value = row.dataset.name || "";
                    prodForm.elements.category_id.value = row.dataset.categoryId || "";
                    prodForm.elements.price.value = row.dataset.price || "0";
                    prodForm.elements.stock.value = row.dataset.stock || "0";
                    prodForm.elements.description.value = row.dataset.description || "";
                    prodForm.elements.image.value = row.dataset.image || "";
                    prodForm.elements.is_active.checked = row.dataset.active === "true";
                    if (prodTitle) {
                        prodTitle.textContent = `Редактирование товара #${id}`;
                    }
                    if (prodReset) {
                        prodReset.hidden = false;
                    }
                    prodForm.scrollIntoView({ behavior: "smooth", block: "start" });
                    return;
                }

                if (event.target.closest("[data-delete-product]")) {
                    if (!window.confirm("Удалить этот товар?")) {
                        return;
                    }
                    const resp = await fetch(`/admin/api/products/${id}`, {
                        method: "DELETE",
                        headers: adminHeaders(false),
                        credentials: "same-origin",
                    });
                    if (!resp.ok) {
                        const data = await resp.json().catch(() => null);
                        showAdminFlash(parseApiError(data, "Не удалось удалить товар."), "error");
                        return;
                    }
                    reloadWithFlash("Товар удалён.");
                }
            });
        }
    }

    // --- Смена статуса заказов ---
    const ordersTable = document.getElementById("admin-orders-table");
    if (ordersTable) {
        ordersTable.addEventListener("click", async (event) => {
            const btn = event.target.closest("[data-save-order-status]");
            if (!btn) {
                return;
            }
            const row = btn.closest("[data-order-id]");
            const select = row && row.querySelector("[data-order-status-select]");
            if (!row || !select || !select.value) {
                showAdminFlash("Выберите новый статус заказа.", "error");
                return;
            }

            const orderId = row.dataset.orderId;
            btn.disabled = true;
            try {
                const resp = await fetch(`/orders/${orderId}/status`, {
                    method: "PATCH",
                    headers: adminHeaders(true),
                    credentials: "same-origin",
                    body: JSON.stringify({ status: select.value }),
                });
                const data = await resp.json().catch(() => null);
                if (!resp.ok) {
                    showAdminFlash(parseApiError(data, "Не удалось обновить статус."), "error");
                    return;
                }
                reloadWithFlash(`Статус заказа #${orderId} обновлён.`);
            } finally {
                btn.disabled = false;
            }
        });
    }
});
