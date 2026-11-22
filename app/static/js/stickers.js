const STICKER_PALETTE = [
    ["#FFF3B0", "Лимонный"],
    ["#FFD6A5", "Персиковый"],
    ["#CAFFBF", "Мятный"],
    ["#BDE0FE", "Небесный"],
    ["#E4C1F9", "Лавандовый"],
];

function readStickerCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie.split(";").map((item) => item.trim());
    for (const part of parts) {
        if (part.startsWith(prefix)) {
            return decodeURIComponent(part.slice(prefix.length));
        }
    }
    return "";
}

function stickerHeaders() {
    const headers = { "Content-Type": "application/json" };
    const csrf = readStickerCookie("csrf_token");
    if (csrf) {
        headers["X-CSRF-Token"] = csrf;
    }
    return headers;
}

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), Math.max(min, max));
}

document.addEventListener("DOMContentLoaded", () => {
    const board = document.getElementById("sticker-board");
    const form = document.getElementById("sticker-create-form");
    const addBtn = document.getElementById("sticker-add-btn");
    const emptyHint = document.getElementById("sticker-board-hint");

    if (!board) {
        return;
    }

    let maxZ = Array.from(board.querySelectorAll(".sticker-note")).reduce(
        (acc, el) => Math.max(acc, Number(el.dataset.z || el.style.zIndex || 1)),
        1
    );

    const updateEmptyHint = () => {
        if (!emptyHint) {
            return;
        }
        emptyHint.hidden = board.querySelectorAll(".sticker-note").length > 0;
    };

    const patchSticker = async (stickerId, payload) => {
        const resp = await fetch(`/stickers/${stickerId}`, {
            method: "PATCH",
            headers: stickerHeaders(),
            credentials: "same-origin",
            body: JSON.stringify(payload),
        });
        if (!resp.ok && typeof window.showAdminFlash === "function") {
            const data = await resp.json().catch(() => null);
            window.showAdminFlash(
                (data && data.detail) || "Не удалось сохранить стикер.",
                "error"
            );
        }
        return resp.ok;
    };

    const bringToFront = (note) => {
        maxZ += 1;
        note.style.zIndex = String(maxZ);
        note.dataset.z = String(maxZ);
        return maxZ;
    };

    const clampNoteToBoard = (note, x, y) => {
        const maxX = board.clientWidth - note.offsetWidth;
        const maxY = board.clientHeight - note.offsetHeight;
        return {
            x: Math.round(clamp(x, 0, maxX)),
            y: Math.round(clamp(y, 0, maxY)),
        };
    };

    const bindSticker = (note) => {
        const stickerId = Number(note.dataset.stickerId);
        const handle = note.querySelector("[data-drag-handle]");
        const textarea = note.querySelector(".sticker-textarea");

        // Убедимся, что стикер в пределах доски при загрузке
        const initialPos = clampNoteToBoard(
            note,
            parseInt(note.style.left || "0", 10),
            parseInt(note.style.top || "0", 10)
        );
        note.style.left = `${initialPos.x}px`;
        note.style.top = `${initialPos.y}px`;

        // Поднятие стикера наверх при фокусе
        note.addEventListener("pointerdown", () => {
            bringToFront(note);
        });

        // Перетаскивание через Pointer Events (мышь + touch)
        if (handle) {
            let activePointerId = null;
            let startClientX = 0;
            let startClientY = 0;
            let startLeft = 0;
            let startTop = 0;
            let moved = false;

            handle.addEventListener("pointerdown", (event) => {
                if (event.target.closest("button")) {
                    return;
                }
                event.preventDefault();
                activePointerId = event.pointerId;
                handle.setPointerCapture(activePointerId);

                startClientX = event.clientX;
                startClientY = event.clientY;
                startLeft = parseInt(note.style.left || "0", 10);
                startTop = parseInt(note.style.top || "0", 10);
                moved = false;

                bringToFront(note);
                note.classList.add("is-dragging");
            });

            handle.addEventListener("pointermove", (event) => {
                if (activePointerId !== event.pointerId) {
                    return;
                }
                const dx = event.clientX - startClientX;
                const dy = event.clientY - startClientY;
                if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
                    moved = true;
                }
                const next = clampNoteToBoard(note, startLeft + dx, startTop + dy);
                note.style.left = `${next.x}px`;
                note.style.top = `${next.y}px`;
            });

            const finishDrag = async (event) => {
                if (activePointerId !== event.pointerId) {
                    return;
                }
                if (handle.hasPointerCapture(activePointerId)) {
                    handle.releasePointerCapture(activePointerId);
                }
                activePointerId = null;
                note.classList.remove("is-dragging");

                const finalX = parseInt(note.style.left || "0", 10);
                const finalY = parseInt(note.style.top || "0", 10);
                const finalZ = Number(note.dataset.z || maxZ);
                if (moved) {
                    await patchSticker(stickerId, { x: finalX, y: finalY, z: finalZ });
                } else {
                    await patchSticker(stickerId, { z: finalZ });
                }
            };

            handle.addEventListener("pointerup", finishDrag);
            handle.addEventListener("pointercancel", finishDrag);
        }

        // Редактирование текста (сохраняется на blur или Ctrl+Enter)
        if (textarea) {
            let lastSavedText = textarea.value;
            const saveText = async () => {
                const trimmed = textarea.value.trim();
                if (!trimmed) {
                    textarea.value = lastSavedText;
                    return;
                }
                if (trimmed === lastSavedText) {
                    return;
                }
                const ok = await patchSticker(stickerId, { text: trimmed });
                if (ok) {
                    lastSavedText = trimmed;
                }
            };
            textarea.addEventListener("blur", saveText);
            textarea.addEventListener("keydown", (event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                    textarea.blur();
                }
            });
        }

        // Смена цвета
        note.querySelectorAll("[data-set-color]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const color = btn.dataset.setColor;
                note.style.backgroundColor = color;
                note.dataset.color = color;
                await patchSticker(stickerId, { color });
            });
        });

        // Удаление стикера
        const deleteBtn = note.querySelector("[data-delete-sticker]");
        if (deleteBtn) {
            deleteBtn.addEventListener("click", async () => {
                deleteBtn.disabled = true;
                try {
                    const resp = await fetch(`/stickers/${stickerId}`, {
                        method: "DELETE",
                        headers: stickerHeaders(),
                        credentials: "same-origin",
                    });
                    if (resp.ok) {
                        note.remove();
                        updateEmptyHint();
                    }
                } finally {
                    deleteBtn.disabled = false;
                }
            });
        }
    };

    const createStickerElement = (sticker) => {
        const note = document.createElement("article");
        note.className = "sticker-note";
        note.dataset.stickerId = String(sticker.id);
        note.dataset.color = sticker.color;
        note.dataset.z = String(sticker.z);
        note.style.left = `${sticker.x}px`;
        note.style.top = `${sticker.y}px`;
        note.style.zIndex = String(sticker.z);
        note.style.backgroundColor = sticker.color;

        const colorButtons = STICKER_PALETTE.map(
            ([hex, label]) =>
                `<button type="button" class="sticker-color-btn" style="background-color: ${hex};" data-set-color="${hex}" aria-label="Цвет: ${label}" title="${label}"></button>`
        ).join("");

        note.innerHTML = `
            <header class="sticker-handle" data-drag-handle title="Перетащите стикер">
                <span class="sticker-grip" aria-hidden="true">⋮⋮</span>
                <div class="sticker-mini-actions">
                    ${colorButtons}
                    <button type="button" class="sticker-delete-btn" data-delete-sticker aria-label="Удалить стикер" title="Удалить">×</button>
                </div>
            </header>
            <textarea class="sticker-textarea" aria-label="Текст заметки" maxlength="500"></textarea>
        `;
        note.querySelector(".sticker-textarea").value = sticker.text;
        return note;
    };

    board.querySelectorAll(".sticker-note").forEach(bindSticker);

    // Создание нового стикера
    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const text = form.elements.text.value.trim();
            const color = form.elements.color.value || "#FFF3B0";
            if (!text) {
                return;
            }

            const count = board.querySelectorAll(".sticker-note").length;
            const offset = (count % 8) * 24;
            const x = clamp(24 + offset, 0, Math.max(0, board.clientWidth - 230));
            const y = clamp(24 + offset, 0, Math.max(0, board.clientHeight - 190));

            if (addBtn) {
                addBtn.disabled = true;
                addBtn.classList.add("is-loading");
            }
            try {
                const resp = await fetch("/stickers", {
                    method: "POST",
                    headers: stickerHeaders(),
                    credentials: "same-origin",
                    body: JSON.stringify({ text, color, x, y }),
                });
                const data = await resp.json().catch(() => null);
                if (!resp.ok) {
                    if (typeof window.showAdminFlash === "function") {
                        window.showAdminFlash(
                            (data && data.detail) || "Не удалось создать стикер.",
                            "error"
                        );
                    }
                    return;
                }

                maxZ = Math.max(maxZ, Number(data.z || 1));
                const note = createStickerElement(data);
                board.appendChild(note);
                bindSticker(note);
                updateEmptyHint();
                form.elements.text.value = "";
            } finally {
                if (addBtn) {
                    addBtn.disabled = false;
                    addBtn.classList.remove("is-loading");
                }
            }
        });
    }
});
