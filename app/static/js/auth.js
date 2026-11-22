function getCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie.split(";").map((item) => item.trim());
    for (const part of parts) {
        if (part.startsWith(prefix)) {
            return decodeURIComponent(part.slice(prefix.length));
        }
    }
    return "";
}

function extractErrorMessage(data, fallback) {
    if (!data) {
        return fallback;
    }
    if (typeof data.detail === "string") {
        return data.detail;
    }
    if (Array.isArray(data.detail) && data.detail.length > 0) {
        return data.detail.map((err) => err.msg || fallback).join(" ");
    }
    return fallback;
}

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("auth-form");
    const errorBox = document.getElementById("auth-error");
    const successBox = document.getElementById("auth-success");
    const submitBtn = document.getElementById("auth-submit");

    if (form && errorBox && successBox && submitBtn) {
        const defaultLabel = submitBtn.textContent;

        const showError = (message) => {
            successBox.hidden = true;
            errorBox.textContent = message;
            errorBox.hidden = false;
        };

        const showSuccess = (message) => {
            errorBox.hidden = true;
            successBox.textContent = message;
            successBox.hidden = false;
        };

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            errorBox.hidden = true;
            successBox.hidden = true;

            const mode = form.dataset.mode;
            const endpoint = form.dataset.endpoint;
            const email = form.elements.email.value.trim();
            const password = form.elements.password.value;

            if (!email) {
                showError("Введите адрес электронной почты.");
                return;
            }
            if (mode === "register") {
                if (password.length < 8) {
                    showError("Пароль должен содержать минимум 8 символов.");
                    return;
                }
                const confirm = form.elements.password_confirm.value;
                if (password !== confirm) {
                    showError("Пароли не совпадают.");
                    return;
                }
            } else if (!password) {
                showError("Введите пароль.");
                return;
            }

            submitBtn.disabled = true;
            submitBtn.textContent = "Подождите...";

            try {
                const headers = { "Content-Type": "application/json" };
                const csrfToken = getCookie("csrf_token");
                if (csrfToken) {
                    headers["X-CSRF-Token"] = csrfToken;
                }

                const response = await fetch(endpoint, {
                    method: "POST",
                    headers,
                    credentials: "same-origin",
                    body: JSON.stringify({ email, password }),
                });

                const data = await response.json().catch(() => null);
                if (!response.ok) {
                    showError(extractErrorMessage(data, "Не удалось выполнить запрос."));
                    return;
                }

                showSuccess(
                    mode === "register"
                        ? "Аккаунт создан! Перенаправляем..."
                        : "Вы успешно вошли! Перенаправляем..."
                );
                window.location.href =
                    data && data.role === "admin" ? "/admin" : "/products";
            } catch {
                showError("Ошибка сети. Проверьте подключение и попробуйте снова.");
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = defaultLabel;
            }
        });
    }

    document.querySelectorAll("[data-demo-email]").forEach((btn) => {
        btn.addEventListener("click", () => {
            if (!form) {
                return;
            }
            form.elements.email.value = btn.dataset.demoEmail || "";
            form.elements.password.value = btn.dataset.demoPassword || "";
            form.requestSubmit();
        });
    });

    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
            const headers = {};
            const csrfToken = getCookie("csrf_token");
            if (csrfToken) {
                headers["X-CSRF-Token"] = csrfToken;
            }
            await fetch("/auth/logout", {
                method: "POST",
                headers,
                credentials: "same-origin",
            });
            window.location.href = "/auth/login";
        });
    }
});
