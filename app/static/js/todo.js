(function () {
  "use strict";

  const MAX_TEXT_LENGTH = 140;

  const el = {
    postit: document.getElementById("todo-postit"),
    errorMsg: document.getElementById("todo-error"),
  };

  if (!el.postit) return;

  function playTodoCheckSound() {
    const pct = (window.FOCUS_STATE && window.FOCUS_STATE.volumeSystem !== undefined) ? window.FOCUS_STATE.volumeSystem : 100;
    const vol = Math.max(0, Math.min(1, pct / 100));
    const sound = new Audio("/static/sounds/riscar_lista.mp3");
    sound.volume = vol;
    sound.play().catch((err) => console.warn("[som] riscar_lista.mp3", err));
  }

  function showError(msg) {
    if (!el.errorMsg) return;
    el.errorMsg.textContent = msg;
    setTimeout(() => { el.errorMsg.textContent = ""; }, 6000);
  }

  async function apiFetch(url, opts) {
    let res;
    try {
      res = await fetch(url, opts);
    } catch (networkErr) {
      showError("Sem conexao com o servidor. Tente novamente.");
      return null;
    }
    if (!res.ok) {
      showError(`Erro no servidor (${res.status}). Tente novamente.`);
      return null;
    }
    try {
      return await res.json();
    } catch (parseErr) {
      showError("Resposta invalida do servidor.");
      return null;
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function rowTemplate(item, canAddMore) {
    const doneClass = item.done ? " done" : "";
    const disabledClass = canAddMore ? "" : " disabled";
    const text = escapeHtml(item.text);
    return `
      <div class="postit-row" data-id="${item.id}">
        <button class="todo-dot${doneClass}" type="button" aria-label="Alternar tarefa"></button>
        <input class="todo-text${doneClass}" type="text" value="${text}" maxlength="${MAX_TEXT_LENGTH}" data-original="${text}">
        <button class="todo-action remove" type="button" aria-label="Excluir tarefa">&times;</button>
        <button class="todo-action add${disabledClass}" type="button" aria-label="Adicionar tarefa">+</button>
      </div>`;
  }

  function emptyRowTemplate(canAddMore) {
    const disabledClass = canAddMore ? "" : " disabled";
    return `
      <div class="postit-row postit-row-empty">
        <button class="todo-dot" type="button" aria-label="Tarefa vazia" disabled></button>
        <input class="todo-text" type="text" value="" maxlength="${MAX_TEXT_LENGTH}" placeholder="Escreva..." data-empty-row="true">
        <button class="todo-action add${disabledClass}" type="button" aria-label="Adicionar tarefa">+</button>
      </div>`;
  }

  async function fetchAndRender(focusItemId) {
    const data = await apiFetch("/api/todos");
    if (!data) return null;

    el.postit.dataset.canAdd = data.can_add_more ? "true" : "false";
    if (data.items.length) {
      el.postit.innerHTML = data.items.map((item) => rowTemplate(item, data.can_add_more)).join("");
    } else {
      el.postit.innerHTML = emptyRowTemplate(data.can_add_more);
    }

    if (focusItemId) {
      const input = el.postit.querySelector(`.postit-row[data-id="${focusItemId}"] .todo-text`);
      if (input) {
        input.focus();
        const len = input.value.length;
        input.setSelectionRange(len, len);
      }
    }
    return data;
  }

  function canAddMore() {
    return el.postit.dataset.canAdd !== "false";
  }

  async function createItem(text, focusNew) {
    if (!canAddMore()) return null;
    const data = await apiFetch("/api/todos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text || "" }),
    });
    if (!data) return null;
    if (data.ok === false) {
      await fetchAndRender();
      return null;
    }
    await fetchAndRender(focusNew ? data.item.id : null);
    return data.item;
  }

  async function saveExistingInput(input) {
    const row = input.closest(".postit-row");
    if (!row || !row.dataset.id) return;

    const original = input.dataset.original || "";
    const text = input.value.trim().slice(0, MAX_TEXT_LENGTH);
    if (!text && original) {
      input.value = original;
      return;
    }
    if (text === original) return;

    const data = await apiFetch(`/api/todos/${row.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!data || data.ok === false) {
      input.value = original;
      return;
    }
    await fetchAndRender();
  }

  async function createFromEmptyInput(input) {
    const text = input.value.trim().slice(0, MAX_TEXT_LENGTH);
    if (!text) return;
    await createItem(text, false);
  }

  el.postit.addEventListener("click", async function (event) {
    const addButton = event.target.closest(".todo-action.add");
    if (addButton) {
      if (addButton.classList.contains("disabled")) return;
      await createItem("", true);
      return;
    }

    const removeButton = event.target.closest(".todo-action.remove");
    if (removeButton) {
      const row = removeButton.closest(".postit-row");
      if (!row || !row.dataset.id) return;
      const data = await apiFetch(`/api/todos/${row.dataset.id}`, { method: "DELETE" });
      if (!data || data.ok === false) return;
      await fetchAndRender();
      return;
    }

    const dot = event.target.closest(".todo-dot");
    if (dot && !dot.disabled) {
      playTodoCheckSound();
      const row = dot.closest(".postit-row");
      if (!row || !row.dataset.id) return;
      const done = !dot.classList.contains("done");

      // Aplica as classes imediatamente para a transição CSS disparar agora
      const input = row.querySelector(".todo-text");
      dot.classList.toggle("done", done);
      if (input) input.classList.toggle("done", done);

      const data = await apiFetch(`/api/todos/${row.dataset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ done }),
      });
      if (!data || data.ok === false) {
        // Reverte em caso de falha
        dot.classList.toggle("done", !done);
        if (input) input.classList.toggle("done", !done);
        return;
      }
      await fetchAndRender();
    }
  });

  el.postit.addEventListener("keydown", async function (event) {
    if (event.key !== "Enter") return;
    const input = event.target.closest(".todo-text");
    if (!input) return;

    event.preventDefault();
    input.dataset.ignoreFocusout = "true";

    const row = input.closest(".postit-row");

    if (event.shiftKey) {
      // Shift+Enter: apaga a linha atual e vai para a atividade de cima
      if (input.dataset.emptyRow === "true") {
        input.value = "";
        delete input.dataset.ignoreFocusout;
        return;
      }

      if (!row || !row.dataset.id) {
        delete input.dataset.ignoreFocusout;
        return;
      }

      const prevRow = row.previousElementSibling;
      const prevId = (prevRow && prevRow.dataset) ? prevRow.dataset.id : null;

      const data = await apiFetch(`/api/todos/${row.dataset.id}`, { method: "DELETE" });
      if (!data || data.ok === false) {
        delete input.dataset.ignoreFocusout;
        return;
      }

      if (prevId) {
        await fetchAndRender(prevId);
      } else {
        await fetchAndRender();
        const firstInput = el.postit.querySelector(".todo-text");
        if (firstInput) {
          firstInput.focus();
          const len = firstInput.value.length;
          firstInput.setSelectionRange(len, len);
        }
      }
      return;
    }

    // Enter (sem Shift): salva a linha atual e cria uma nova linha abaixo com o cursor nela
    if (input.dataset.emptyRow === "true") {
      const text = input.value.trim().slice(0, MAX_TEXT_LENGTH);
      if (!text) {
        delete input.dataset.ignoreFocusout;
        return;
      }
      const created = await createItem(text, false);
      if (created && canAddMore()) {
        await createItem("", true);
      } else if (created) {
        await fetchAndRender(created.id);
      } else {
        delete input.dataset.ignoreFocusout;
      }
      return;
    }

    if (row && row.dataset.id) {
      const text = input.value.trim().slice(0, MAX_TEXT_LENGTH);
      const original = input.dataset.original || "";

      if (text && text !== original) {
        await apiFetch(`/api/todos/${row.dataset.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
      } else if (!text && original) {
        input.value = original;
      }

      if (canAddMore()) {
        await createItem("", true);
      } else {
        await fetchAndRender(row.dataset.id);
      }
    }
  });

  el.postit.addEventListener("focusout", async function (event) {
    const input = event.target.closest(".todo-text");
    if (!input || input.dataset.ignoreFocusout === "true") return;

    if (input.dataset.emptyRow === "true") {
      await createFromEmptyInput(input);
      return;
    }
    await saveExistingInput(input);
  });
})();
