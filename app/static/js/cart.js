function readCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie.split(";").map((item) => item.trim());
    for (const part of parts) {
        if (part.startsWith(prefix)) {
            return decodeURIComponent(part.slice(prefix.length));
        }
    }
    return "";
}

function buildJsonHeaders() {
    const headers = { "Content-Type": "application/json" };
    const csrfToken = readCookie("csrf_token");
    if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
    }
    return headers;
}

function formatPrice(value) {
    return `${Math.round(Number(value))} ₽`;
}

function showToast(message, isError = false) {
    let toast = document.getElementById("app-toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "app-toast";
        toast.className = "toast";
        toast.setAttribute("role", "status");
        toast.setAttribute("aria-live", "polite");
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.toggle("toast-error", isError);
    toast.classList.add("toast-visible");

    window.clearTimeout(toast._hideTimer);
    toast._hideTimer = window.setTimeout(() => {
        toast.classList.remove("toast-visible");
    }, 2600);
}

document.addEventListener("DOMContentLoaded", () => {
    // Добавление в корзину из каталога и карточки товара
    document.querySelectorAll("[data-add-to-cart]").forEach((button) => {
        button.addEventListener("click", async () => {
            const productId = Number(button.dataset.addToCart);
            const originalText = button.textContent;
            button.disabled = true;
            button.textContent = "...";

            try {
                const response = await fetch("/cart/items", {
                    method: "POST",
                    headers: buildJsonHeaders(),
                    credentials: "same-origin",
                    body: JSON.stringify({ product_id: productId, quantity: 1 }),
                });

                if (response.status === 401) {
                    window.location.href = "/auth/login";
                    return;
                }

                const data = await response.json().catch(() => null);
                if (!response.ok) {
                    showToast((data && data.detail) || "Не удалось добавить товар", true);
                    return;
                }

                showToast(`Добавлено в корзину (всего: ${data.total_items})`);
            } catch {
                showToast("Ошибка сети. Попробуйте снова.", true);
            } finally {
                button.disabled = false;
                button.textContent = originalText;
            }
        });
    });

    // Интерактивная корзина (без перезагрузки)
    const cartContent = document.getElementById("cart-content");
    const cartEmpty = document.getElementById("cart-empty");
    const cartAlert = document.getElementById("cart-alert");
    const totalItemsEl = document.getElementById("cart-total-items");
    const totalPriceEl = document.getElementById("cart-total-price");

    const showCartError = (msg) => {
        if (!cartAlert) {
            return;
        }
        cartAlert.textContent = msg;
        cartAlert.hidden = false;
    };

    const hideCartError = () => {
        if (cartAlert) {
            cartAlert.hidden = true;
        }
    };

    const syncCartDom = (cartData) => {
        if (!cartContent || !cartEmpty) {
            return;
        }
        const itemsByProductId = new Map(
            cartData.items.map((item) => [item.product_id, item])
        );

        cartContent.querySelectorAll(".cart-item").forEach((row) => {
            const pid = Number(row.dataset.productId);
            const updated = itemsByProductId.get(pid);
            if (!updated) {
                row.remove();
                return;
            }
            const input = row.querySelector(".qty-input");
            const subtotalEl = row.querySelector("[data-item-subtotal]");
            if (input) {
                input.value = String(updated.quantity);
            }
            if (subtotalEl) {
                subtotalEl.textContent = formatPrice(updated.subtotal);
            }
        });

        if (totalItemsEl) {
            totalItemsEl.textContent = String(cartData.total_items);
        }
        if (totalPriceEl) {
            totalPriceEl.textContent = formatPrice(cartData.total);
        }

        if (cartData.items.length === 0) {
            cartContent.hidden = true;
            cartEmpty.hidden = false;
        }
    };

    const updateQuantity = async (productId, newQuantity) => {
        hideCartError();
        const response = await fetch(`/cart/items/${productId}`, {
            method: "PATCH",
            headers: buildJsonHeaders(),
            credentials: "same-origin",
            body: JSON.stringify({ quantity: Math.max(0, newQuantity) }),
        });
        const data = await response.json().catch(() => null);
        if (!response.ok) {
            showCartError((data && data.detail) || "Не удалось обновить количество");
            return false;
        }
        syncCartDom(data);
        return true;
    };

    if (cartContent) {
        cartContent.addEventListener("click", async (event) => {
            const row = event.target.closest(".cart-item");
            if (!row) {
                return;
            }
            const productId = Number(row.dataset.productId);
            const input = row.querySelector(".qty-input");

            const qtyBtn = event.target.closest("[data-qty-delta]");
            if (qtyBtn && input) {
                const delta = Number(qtyBtn.dataset.qtyDelta);
                const nextQty = Number(input.value || "1") + delta;
                qtyBtn.disabled = true;
                try {
                    await updateQuantity(productId, nextQty);
                } finally {
                    qtyBtn.disabled = false;
                }
                return;
            }

            const removeBtn = event.target.closest("[data-remove-item]");
            if (removeBtn) {
                hideCartError();
                removeBtn.disabled = true;
                try {
                    const response = await fetch(`/cart/items/${productId}`, {
                        method: "DELETE",
                        headers: buildJsonHeaders(),
                        credentials: "same-origin",
                    });
                    const data = await response.json().catch(() => null);
                    if (!response.ok) {
                        showCartError((data && data.detail) || "Не удалось удалить товар");
                        return;
                    }
                    syncCartDom(data);
                } finally {
                    removeBtn.disabled = false;
                }
            }
        });

        cartContent.addEventListener("change", async (event) => {
            const input = event.target.closest(".qty-input");
            if (!input) {
                return;
            }
            const row = input.closest(".cart-item");
            if (!row) {
                return;
            }
            const productId = Number(row.dataset.productId);
            const parsed = Number.parseInt(input.value, 10);
            if (Number.isNaN(parsed) || parsed < 0) {
                input.value = "1";
                return;
            }
            await updateQuantity(productId, parsed);
        });
    }

    const clearCartBtn = document.getElementById("clear-cart-btn");
    if (clearCartBtn) {
        clearCartBtn.addEventListener("click", async () => {
            hideCartError();
            clearCartBtn.disabled = true;
            try {
                const response = await fetch("/cart", {
                    method: "DELETE",
                    headers: buildJsonHeaders(),
                    credentials: "same-origin",
                });
                const data = await response.json().catch(() => null);
                if (!response.ok) {
                    showCartError((data && data.detail) || "Не удалось очистить корзину");
                    return;
                }
                syncCartDom(data);
            } finally {
                clearCartBtn.disabled = false;
            }
        });
    }

    // Подтверждение заказа на /orders/checkout
    const placeOrderBtn = document.getElementById("place-order-btn");
    const checkoutError = document.getElementById("checkout-error");
    const checkoutSuccess = document.getElementById("checkout-success");

    if (placeOrderBtn) {
        placeOrderBtn.addEventListener("click", async () => {
            if (checkoutError) {
                checkoutError.hidden = true;
            }
            if (checkoutSuccess) {
                checkoutSuccess.hidden = true;
            }

            placeOrderBtn.disabled = true;
            const originalLabel = placeOrderBtn.textContent;
            placeOrderBtn.textContent = "Оформляем...";

            try {
                const response = await fetch("/orders", {
                    method: "POST",
                    headers: buildJsonHeaders(),
                    credentials: "same-origin",
                });
                const data = await response.json().catch(() => null);
                if (!response.ok) {
                    if (checkoutError) {
                        checkoutError.textContent =
                            (data && data.detail) || "Не удалось оформить заказ.";
                        checkoutError.hidden = false;
                    }
                    return;
                }

                if (checkoutSuccess) {
                    checkoutSuccess.textContent = `Заказ №${data.id} успешно оформлен!`;
                    checkoutSuccess.hidden = false;
                }
                window.location.href = "/orders";
            } catch {
                if (checkoutError) {
                    checkoutError.textContent = "Ошибка сети. Попробуйте снова.";
                    checkoutError.hidden = false;
                }
            } finally {
                placeOrderBtn.disabled = false;
                placeOrderBtn.textContent = originalLabel;
            }
        });
    }
});
