function getBlogCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie.split(";").map((item) => item.trim());
    for (const part of parts) {
        if (part.startsWith(prefix)) {
            return decodeURIComponent(part.slice(prefix.length));
        }
    }
    return "";
}

function buildBlogHeaders() {
    const headers = { "Content-Type": "application/json" };
    const csrf = getBlogCookie("csrf_token");
    if (csrf) {
        headers["X-CSRF-Token"] = csrf;
    }
    return headers;
}

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("blog-post-form");
    const heading = document.getElementById("post-form-heading");
    const resetBtn = document.getElementById("blog-reset-btn");
    const submitBtn = document.getElementById("blog-submit-btn");
    const errorBox = document.getElementById("blog-admin-error");
    const successBox = document.getElementById("blog-admin-success");
    const listRoot = document.getElementById("admin-posts-list");

    if (!form) {
        return;
    }

    const showMessage = (box, text) => {
        if (errorBox) {
            errorBox.hidden = true;
        }
        if (successBox) {
            successBox.hidden = true;
        }
        if (box) {
            box.textContent = text;
            box.hidden = false;
        }
    };

    const resetForm = () => {
        form.reset();
        form.elements.post_id.value = "";
        if (heading) {
            heading.textContent = "Новый пост";
        }
        if (resetBtn) {
            resetBtn.hidden = true;
        }
    };

    if (resetBtn) {
        resetBtn.addEventListener("click", resetForm);
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const postId = form.elements.post_id.value.trim();
        const publishedAtRaw = form.elements.published_at.value.trim();

        const payload = {
            title: form.elements.title.value.trim(),
            slug: form.elements.slug.value.trim() || null,
            cover: form.elements.cover.value.trim() || null,
            body_md: form.elements.body_md.value,
            is_published: form.elements.is_published.checked,
            published_at: publishedAtRaw ? new Date(publishedAtRaw).toISOString() : null,
        };

        const url = postId ? `/blog/${postId}` : "/blog";
        const method = postId ? "PATCH" : "POST";

        if (submitBtn) {
            submitBtn.disabled = true;
        }
        try {
            const response = await fetch(url, {
                method,
                headers: buildBlogHeaders(),
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => null);
            if (!response.ok) {
                const detail =
                    (data && typeof data.detail === "string" && data.detail) ||
                    "Проверьте корректность полей формы.";
                showMessage(errorBox, detail);
                return;
            }
            showMessage(successBox, postId ? "Пост обновлён." : "Пост создан.");
            window.location.reload();
        } catch {
            showMessage(errorBox, "Ошибка сети. Попробуйте снова.");
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
            }
        }
    });

    if (listRoot) {
        listRoot.addEventListener("click", async (event) => {
            const row = event.target.closest(".admin-post-row");
            if (!row) {
                return;
            }
            const postId = row.dataset.postId;

            if (event.target.closest("[data-edit-post]")) {
                form.elements.post_id.value = postId;
                form.elements.title.value = row.dataset.title || "";
                form.elements.slug.value = row.dataset.slug || "";
                form.elements.cover.value = row.dataset.cover || "";
                form.elements.body_md.value = row.dataset.body || "";
                form.elements.is_published.checked = row.dataset.published === "true";
                form.elements.published_at.value = row.dataset.publishedAt || "";
                if (heading) {
                    heading.textContent = `Редактирование поста #${postId}`;
                }
                if (resetBtn) {
                    resetBtn.hidden = false;
                }
                form.scrollIntoView({ behavior: "smooth", block: "start" });
                return;
            }

            const deleteBtn = event.target.closest("[data-delete-post]");
            if (deleteBtn) {
                if (!window.confirm("Удалить этот пост без возможности восстановления?")) {
                    return;
                }
                deleteBtn.disabled = true;
                try {
                    const response = await fetch(`/blog/${postId}`, {
                        method: "DELETE",
                        headers: buildBlogHeaders(),
                        credentials: "same-origin",
                    });
                    if (!response.ok) {
                        const data = await response.json().catch(() => null);
                        showMessage(
                            errorBox,
                            (data && data.detail) || "Не удалось удалить пост."
                        );
                        return;
                    }
                    row.remove();
                    showMessage(successBox, "Пост удалён.");
                } finally {
                    deleteBtn.disabled = false;
                }
            }
        });
    }
});
