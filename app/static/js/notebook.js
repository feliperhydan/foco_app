(function () {
  "use strict";

  const wrapperEl = document.querySelector("[data-date]") || document.getElementById("registro-editor");
  const refDate = wrapperEl ? wrapperEl.getAttribute("data-date") : "";

  const editorEl = document.getElementById("registro-editor");
  const isEditable = editorEl ? editorEl.getAttribute("data-editable") === "true" : false;
  const linesContainer = document.getElementById("registro-lines");

  let linesData = Array.isArray(window.NOTEBOOK_INITIAL_CONTENT) ? [...window.NOTEBOOK_INITIAL_CONTENT] : [];
  let activeLineId = null;
  let saveTimeout = null;

  // Garantir pelo menos 1 linha se estiver vazio e for editável
  if (linesContainer && linesData.length === 0 && isEditable) {
    linesData = [createNewEmptyLine()];
  }

  function buildFormattedInitialText(color = "default", size = "small", bold = false) {
    if (color === "default" && size === "small" && !bold) {
      return "";
    }

    let html = "\u200B";

    if (bold) {
      html = `<strong class="fmt-bold">${html}</strong>`;
    }

    if (size === "large") {
      html = `<span class="fs-inline fs-large" style="font-size: 25px;">${html}</span>`;
    } else if (size === "medium") {
      html = `<span class="fs-inline fs-medium" style="font-size: 20px;">${html}</span>`;
    } else if (size === "small") {
      html = `<span class="fs-inline fs-small" style="font-size: 16px;">${html}</span>`;
    }

    if (color && color !== "default") {
      html = `<span class="clr-${color}">${html}</span>`;
    }

    return html;
  }

  function createNewEmptyLine(type = "text", text = "", color = "default", bold = false, size = "small") {
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    return {
      id: "line-" + Math.random().toString(36).substring(2, 9),
      time: timeStr,
      text: text,
      type: type, // text, checkbox, bullet
      checked: false,
      bold: bold,
      color: color, // default, green, red, blue
      size: size, // small (pequeno), medium (médio), large (grande)
    };
  }

  function renderLines() {
    linesContainer.innerHTML = "";
    if (linesData.length === 0) {
      if (!isEditable) {
        linesContainer.innerHTML = '<div class="neutral-empty-text">Nenhuma anotação ainda hoje.</div>';
      }
      return;
    }

    linesData.forEach((line) => {
      const lineEl = document.createElement("div");
      lineEl.className = `registro-line type-${line.type} color-${line.color || "default"} size-${line.size || "small"} ${line.bold ? "is-bold" : ""}`;
      lineEl.setAttribute("data-line-id", line.id);

      // Tempo opcional (ex: 08:00)
      if (line.time) {
        const timeSpan = document.createElement("span");
        timeSpan.className = "line-time";
        timeSpan.textContent = line.time;
        lineEl.appendChild(timeSpan);
      }

      // Checkbox ou Bullet
      if (line.type === "checkbox") {
        const chkBtn = document.createElement("button");
        chkBtn.type = "button";
        chkBtn.className = `line-checkbox ${line.checked ? "checked" : ""}`;
        if (isEditable) {
          chkBtn.addEventListener("click", () => {
            line.checked = !line.checked;
            chkBtn.classList.toggle("checked", line.checked);
            triggerAutoSave();
          });
        }
        lineEl.appendChild(chkBtn);
      } else if (line.type === "bullet") {
        const bulletSpan = document.createElement("span");
        bulletSpan.className = "line-bullet";
        bulletSpan.textContent = "•";
        lineEl.appendChild(bulletSpan);
      }

      // Input de Texto Editable
      const inputDiv = document.createElement("div");
      inputDiv.className = "line-input";
      inputDiv.contentEditable = isEditable ? "true" : "false";
      inputDiv.innerHTML = line.text || "";

      if (isEditable) {
        inputDiv.addEventListener("focus", () => {
          activeLineId = line.id;
          updateActiveLineHighlight();
          updateToolbarState();
        });

        inputDiv.addEventListener("input", () => {
          line.text = inputDiv.innerHTML;
          triggerAutoSave();
        });

        inputDiv.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            if (e.shiftKey) {
              // Shift + Enter: Quebra de linha suave dentro da MESMA nota (mesmo horário)
              e.preventDefault();
              const sel = window.getSelection();
              if (sel && sel.rangeCount > 0) {
                const range = sel.getRangeAt(0);
                range.deleteContents();

                const br = document.createElement("br");
                range.insertNode(br);

                const zwsp = document.createTextNode("\u200B");
                range.setStartAfter(br);
                range.setEndAfter(br);
                range.insertNode(zwsp);

                const newRange = document.createRange();
                newRange.setStartAfter(zwsp);
                newRange.setEndAfter(zwsp);
                sel.removeAllRanges();
                sel.addRange(newRange);
              }
              line.text = inputDiv.innerHTML;
              triggerAutoSave();
              return;
            }

            // Enter normal: cria nova linha formal na agenda mantendo o contexto de texto da linha anterior
            e.preventDefault();
            line.text = inputDiv.innerHTML;

            const activeColor = getSelectionColor();
            const activeSize = getSelectionFontSize();
            const activeBold = getSelectionIsBold();
            const initialHtml = buildFormattedInitialText(activeColor, activeSize, activeBold);

            const idx = linesData.findIndex((l) => l.id === line.id);
            const newLine = createNewEmptyLine("text", initialHtml, activeColor, activeBold, activeSize);
            linesData.splice(idx + 1, 0, newLine);
            renderLines();
            focusLineInput(newLine.id);
            updateToolbarState();
            triggerAutoSave();
          } else if (e.key === "Backspace" && (inputDiv.textContent || "").trim() === "" && linesData.length > 1) {
            e.preventDefault();
            const idx = linesData.findIndex((l) => l.id === line.id);
            linesData.splice(idx, 1);
            renderLines();
            const prevIndex = Math.max(0, idx - 1);
            focusLineInput(linesData[prevIndex].id);
            updateToolbarState();
            triggerAutoSave();
          }
        });
      }

      lineEl.appendChild(inputDiv);
      linesContainer.appendChild(lineEl);
    });

    updateToolbarState();
  }

  function focusLineInput(lineId) {
    const el = linesContainer.querySelector(`[data-line-id="${lineId}"] .line-input`);
    if (el) {
      el.focus();
      // Mover cursor para o final
      const range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
  }

  function getActiveLine() {
    if (!activeLineId && linesData.length > 0) return linesData[0];
    return linesData.find((l) => l.id === activeLineId) || linesData[0];
  }

  function updateActiveLineHighlight() {
    linesContainer.querySelectorAll(".registro-line").forEach((el) => {
      if (el.getAttribute("data-line-id") === activeLineId) {
        el.classList.add("active-line");
      } else {
        el.classList.remove("active-line");
      }
    });
  }

  function getSelectionFontSize() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return "small";
    let node = sel.anchorNode;
    if (!node) return "small";
    if (node.nodeType === Node.TEXT_NODE) node = node.parentNode;

    const span = node.closest ? node.closest(".fs-inline") : null;
    if (span) {
      if (span.classList.contains("fs-large")) return "large";
      if (span.classList.contains("fs-medium")) return "medium";
      if (span.classList.contains("fs-small")) return "small";
    }

    const lineInput = node.closest ? node.closest(".line-input") : null;
    if (lineInput) {
      const style = window.getComputedStyle(node);
      const fontSize = parseFloat(style.fontSize);
      if (fontSize >= 23) return "large";
      if (fontSize >= 19) return "medium";
      return "small";
    }
    return "small";
  }

  function getSelectionColor() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return "default";
    let node = sel.anchorNode;
    if (!node) return "default";
    if (node.nodeType === Node.TEXT_NODE) node = node.parentNode;

    const span = node.closest ? node.closest(".clr-green, .clr-red, .clr-blue, .clr-default") : null;
    if (span) {
      if (span.classList.contains("clr-green")) return "green";
      if (span.classList.contains("clr-red")) return "red";
      if (span.classList.contains("clr-blue")) return "blue";
      if (span.classList.contains("clr-default")) return "default";
    }
    return "default";
  }

  function getSelectionIsBold() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return false;
    let node = sel.anchorNode;
    if (!node) return false;
    if (node.nodeType === Node.TEXT_NODE) node = node.parentNode;

    const boldEl = node.closest ? node.closest("strong, b, .fmt-bold") : null;
    if (boldEl) return true;

    const style = window.getComputedStyle(node);
    return parseInt(style.fontWeight, 10) >= 600 || style.fontWeight === "bold";
  }

  function updateFontSizeButtonUI() {
    const btnFontSize = document.getElementById("btn-font-size");
    if (!btnFontSize) return;
    const currentSize = getSelectionFontSize();

    btnFontSize.querySelectorAll(".fs-item").forEach((item) => {
      const isTarget = item.getAttribute("data-size") === currentSize;
      item.classList.toggle("active", isTarget);
    });
  }

  function updateColorPickerUI() {
    const curColor = getSelectionColor();
    document.querySelectorAll(".color-dot").forEach((dot) => {
      const isTarget = dot.getAttribute("data-color") === curColor;
      dot.classList.toggle("active", isTarget);
    });
  }

  function updateBoldButtonUI() {
    const btnBold = document.getElementById("tool-bold");
    if (!btnBold) return;
    const isBold = getSelectionIsBold();
    btnBold.classList.toggle("active", isBold);
  }

  function updateToolbarState() {
    updateFontSizeButtonUI();
    updateColorPickerUI();
    updateBoldButtonUI();
  }

  function applyInlineFontSize(targetSize) {
    const sel = window.getSelection();
    let lineInput = null;
    let range = null;

    if (sel && sel.rangeCount > 0) {
      range = sel.getRangeAt(0);
      let container = range.commonAncestorContainer;
      if (container.nodeType === Node.TEXT_NODE) container = container.parentNode;
      lineInput = container.closest ? container.closest(".line-input") : null;
    }

    if (!lineInput && activeLineId) {
      lineInput = linesContainer.querySelector(`[data-line-id="${activeLineId}"] .line-input`);
    }

    if (!lineInput) return;

    const sizePx = targetSize === "large" ? "25px" : targetSize === "medium" ? "20px" : "16px";

    if (range && !sel.isCollapsed && lineInput.contains(range.commonAncestorContainer)) {
      // 1. SE HOUVER TEXTO SELECIONADO: Altera apenas a seleção de texto
      try {
        const span = document.createElement("span");
        span.className = `fs-inline fs-${targetSize}`;
        span.style.fontSize = sizePx;
        span.appendChild(range.extractContents());
        range.insertNode(span);

        const newRange = document.createRange();
        newRange.selectNodeContents(span);
        sel.removeAllRanges();
        sel.addRange(newRange);
      } catch (e) {
        console.error("Erro ao aplicar estilo na seleção:", e);
      }
    } else {
      // 2. SE NÃO HOUVER SELEÇÃO (APENAS CURSOR NA LINHA):
      // Caracteres já inseridos NÃO alteram!
      // Cria um novo span para os PRÓXIMOS caracteres digitados no ponto do cursor.
      try {
        const span = document.createElement("span");
        span.className = `fs-inline fs-${targetSize}`;
        span.style.fontSize = sizePx;
        const zwsp = document.createTextNode("\u200B");
        span.appendChild(zwsp);

        if (range && lineInput.contains(range.commonAncestorContainer)) {
          range.insertNode(span);
        } else {
          lineInput.appendChild(span);
        }

        const newRange = document.createRange();
        newRange.setStart(zwsp, 1);
        newRange.setEnd(zwsp, 1);
        sel.removeAllRanges();
        sel.addRange(newRange);
      } catch (e) {
        console.error("Erro ao preparar span dinâmico de fonte:", e);
      }
    }

    const lineEl = lineInput.closest(".registro-line");
    if (lineEl) {
      const lineId = lineEl.getAttribute("data-line-id");
      const lineObj = linesData.find((l) => l.id === lineId);
      if (lineObj) {
        lineObj.text = lineInput.innerHTML;
      }
    }

    updateToolbarState();
    triggerAutoSave();
  }

  function applyInlineColor(targetColor) {
    const sel = window.getSelection();
    let lineInput = null;
    let range = null;

    if (sel && sel.rangeCount > 0) {
      range = sel.getRangeAt(0);
      let container = range.commonAncestorContainer;
      if (container.nodeType === Node.TEXT_NODE) container = container.parentNode;
      lineInput = container.closest ? container.closest(".line-input") : null;
    }

    if (!lineInput && activeLineId) {
      lineInput = linesContainer.querySelector(`[data-line-id="${activeLineId}"] .line-input`);
    }

    if (!lineInput) return;

    if (range && !sel.isCollapsed && lineInput.contains(range.commonAncestorContainer)) {
      // 1. SE HOUVER TEXTO SELECIONADO: Altera apenas a seleção de texto
      try {
        const span = document.createElement("span");
        span.className = `clr-${targetColor}`;
        span.appendChild(range.extractContents());
        range.insertNode(span);

        const newRange = document.createRange();
        newRange.selectNodeContents(span);
        sel.removeAllRanges();
        sel.addRange(newRange);
      } catch (e) {
        console.error("Erro ao aplicar cor na seleção:", e);
      }
    } else {
      // 2. SE NÃO HOUVER SELEÇÃO (APENAS CURSOR):
      // Caracteres já inseridos NÃO alteram!
      // Cria um novo span de cor para os próximos caracteres digitados no ponto do cursor.
      try {
        const span = document.createElement("span");
        span.className = `clr-${targetColor}`;
        const zwsp = document.createTextNode("\u200B");
        span.appendChild(zwsp);

        if (range && lineInput.contains(range.commonAncestorContainer)) {
          range.insertNode(span);
        } else {
          lineInput.appendChild(span);
        }

        const newRange = document.createRange();
        newRange.setStart(zwsp, 1);
        newRange.setEnd(zwsp, 1);
        sel.removeAllRanges();
        sel.addRange(newRange);
      } catch (e) {
        console.error("Erro ao preparar span dinâmico de cor:", e);
      }
    }

    const lineEl = lineInput.closest(".registro-line");
    if (lineEl) {
      const lineId = lineEl.getAttribute("data-line-id");
      const lineObj = linesData.find((l) => l.id === lineId);
      if (lineObj) {
        lineObj.text = lineInput.innerHTML;
      }
    }

    updateToolbarState();
    triggerAutoSave();
  }

  function applyInlineBold() {
    const sel = window.getSelection();
    let lineInput = null;
    let range = null;

    if (sel && sel.rangeCount > 0) {
      range = sel.getRangeAt(0);
      let container = range.commonAncestorContainer;
      if (container.nodeType === Node.TEXT_NODE) container = container.parentNode;
      lineInput = container.closest ? container.closest(".line-input") : null;
    }

    if (!lineInput && activeLineId) {
      lineInput = linesContainer.querySelector(`[data-line-id="${activeLineId}"] .line-input`);
    }

    if (!lineInput) return;

    const isCurrentlyBold = getSelectionIsBold();

    if (range && !sel.isCollapsed && lineInput.contains(range.commonAncestorContainer)) {
      // 1. Texto selecionado
      try {
        if (isCurrentlyBold) {
          document.execCommand("bold", false, null);
        } else {
          const strong = document.createElement("strong");
          strong.className = "fmt-bold";
          strong.appendChild(range.extractContents());
          range.insertNode(strong);

          const newRange = document.createRange();
          newRange.selectNodeContents(strong);
          sel.removeAllRanges();
          sel.addRange(newRange);
        }
      } catch (e) {
        console.error("Erro ao aplicar negrito na seleção:", e);
      }
    } else {
      // 2. Sem seleção (apenas cursor): Caracteres já inseridos NÃO alteram.
      try {
        let node = sel ? sel.anchorNode : null;
        if (node && node.nodeType === Node.TEXT_NODE) node = node.parentNode;
        const existingStrong = node && node.closest ? node.closest("strong, b, .fmt-bold") : null;

        if (existingStrong && lineInput.contains(existingStrong)) {
          // Desativar negrito para próximos caracteres
          const zwsp = document.createTextNode("\u200B");
          if (existingStrong.nextSibling) {
            existingStrong.parentNode.insertBefore(zwsp, existingStrong.nextSibling);
          } else {
            existingStrong.parentNode.appendChild(zwsp);
          }
          const newRange = document.createRange();
          newRange.setStart(zwsp, 1);
          newRange.setEnd(zwsp, 1);
          sel.removeAllRanges();
          sel.addRange(newRange);
        } else {
          // Ativar negrito para próximos caracteres
          const strong = document.createElement("strong");
          strong.className = "fmt-bold";
          const zwsp = document.createTextNode("\u200B");
          strong.appendChild(zwsp);

          if (range && lineInput.contains(range.commonAncestorContainer)) {
            range.insertNode(strong);
          } else {
            lineInput.appendChild(strong);
          }

          const newRange = document.createRange();
          newRange.setStart(zwsp, 1);
          newRange.setEnd(zwsp, 1);
          sel.removeAllRanges();
          sel.addRange(newRange);
        }
      } catch (e) {
        console.error("Erro ao preparar negrito dinâmico:", e);
      }
    }

    const lineEl = lineInput.closest(".registro-line");
    if (lineEl) {
      const lineId = lineEl.getAttribute("data-line-id");
      const lineObj = linesData.find((l) => l.id === lineId);
      if (lineObj) {
        lineObj.text = lineInput.innerHTML;
      }
    }

    updateToolbarState();
    triggerAutoSave();
  }

  function triggerAutoSave() {
    if (!isEditable) return;
    if (saveTimeout) clearTimeout(saveTimeout);
    saveTimeout = setTimeout(async () => {
      try {
        await fetch("/api/notebook/save_registro", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ date: refDate, content: linesData }),
        });
      } catch (err) {
        console.error("Erro ao salvar Registro Pessoal:", err);
      }
    }, 500);
  }

  // --- TOOLBAR EVENTS (SE FOR EDITÁVEL) ---
  if (isEditable) {
    const btnCheckbox = document.getElementById("tool-checkbox");
    if (btnCheckbox) {
      btnCheckbox.addEventListener("click", () => {
        const line = getActiveLine();
        if (line) {
          line.type = line.type === "checkbox" ? "text" : "checkbox";
          renderLines();
          focusLineInput(line.id);
          triggerAutoSave();
        }
      });
    }

    const btnBullet = document.getElementById("tool-bullet");
    if (btnBullet) {
      btnBullet.addEventListener("click", () => {
        const line = getActiveLine();
        if (line) {
          line.type = line.type === "bullet" ? "text" : "bullet";
          renderLines();
          focusLineInput(line.id);
          triggerAutoSave();
        }
      });
    }

    const btnBold = document.getElementById("tool-bold");
    if (btnBold) {
      btnBold.addEventListener("click", () => {
        applyInlineBold();
      });
    }

    const colorDots = document.querySelectorAll(".color-dot");
    colorDots.forEach((dot) => {
      dot.addEventListener("click", () => {
        const color = dot.getAttribute("data-color");
        applyInlineColor(color);
      });
    });

    const btnFontSize = document.getElementById("btn-font-size");
    if (btnFontSize) {
      btnFontSize.addEventListener("click", () => {
        const currentSize = getSelectionFontSize();
        const cycle = { small: "medium", medium: "large", large: "small" };
        const nextSize = cycle[currentSize] || "medium";
        applyInlineFontSize(nextSize);
      });
    }

    document.addEventListener("selectionchange", () => {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        let node = sel.anchorNode;
        if (node) {
          if (node.nodeType === Node.TEXT_NODE) node = node.parentNode;
          if (node && node.closest && node.closest("#registro-editor")) {
            updateToolbarState();
          }
        }
      }
    });
  }

  // --- BANNER PROGRAMAÇÃO (TOGGLE / OK / COPIAR) ---
  const btnToggleProg = document.getElementById("btn-toggle-programacao");
  const panelProg = document.getElementById("programacao-panel");

  if (btnToggleProg && panelProg) {
    btnToggleProg.addEventListener("click", () => {
      const isHidden = panelProg.style.display === "none" || window.getComputedStyle(panelProg).display === "none";
      panelProg.style.display = isHidden ? "block" : "none";
    });
  }

  const btnProgOk = document.getElementById("btn-programacao-ok");
  if (btnProgOk) {
    btnProgOk.addEventListener("click", async () => {
      if (panelProg) panelProg.style.display = "none";
      try {
        await fetch("/api/notebook/programacao/dismiss", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ date: refDate }),
        });
      } catch (e) { }
    });
  }

  const btnProgCopy = document.getElementById("btn-programacao-copy");
  if (btnProgCopy) {
    btnProgCopy.addEventListener("click", async () => {
      if (panelProg) panelProg.style.display = "none";
      try {
        const res = await fetch("/api/notebook/programacao/copy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ date: refDate }),
        });
        const data = await res.json();
        if (data.status === "ok" && Array.isArray(data.registro_content)) {
          linesData = data.registro_content;
          if (linesContainer) renderLines();
        }
      } catch (e) { }
    });
  }

  // --- RETRATO DO DIA: USER INPUTS (INÍCIO, FIM, CANSAÇO) ---
  const inputInicio = document.getElementById("input-inicio-estudos");
  const inputFim = document.getElementById("input-fim-estudos");
  const cansacoContainer = document.getElementById("cansaco-blocks");

  function saveRetratoUserFields() {
    if (!isEditable) return;
    const inicio = inputInicio ? inputInicio.value : "";
    const fim = inputFim ? inputFim.value : "";
    const cansaco = cansacoContainer ? parseInt(cansacoContainer.getAttribute("data-level") || "0", 10) : 0;

    fetch("/api/notebook/save_retrato", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: refDate,
        inicio_estudos: inicio,
        fim_estudos: fim,
        nivel_cansaco: cansaco,
      }),
    }).catch((err) => console.error("Erro ao salvar Retrato:", err));
  }

  if (isEditable) {
    if (inputInicio) inputInicio.addEventListener("change", saveRetratoUserFields);
    if (inputFim) inputFim.addEventListener("change", saveRetratoUserFields);

    if (cansacoContainer) {
      const blocks = cansacoContainer.querySelectorAll(".cansaco-block");
      blocks.forEach((blk) => {
        blk.addEventListener("click", () => {
          const lvl = parseInt(blk.getAttribute("data-level"), 10);
          cansacoContainer.setAttribute("data-level", lvl);
          blocks.forEach((b) => {
            const bLvl = parseInt(b.getAttribute("data-level"), 10);
            b.classList.toggle("active", bLvl <= lvl);
          });
          saveRetratoUserFields();
        });
      });
    }
  }

  // --- PROTOCOLOS: COPIAR ATIVIDADES E GERENCIAMENTO ---
  document.querySelectorAll(".btn-copy-protocol").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const protoId = parseInt(btn.getAttribute("data-protocol-id"), 10);
      if (!protoId) return;

      const protocols = window.NOTEBOOK_PROTOCOLS || [];
      const proto = protocols.find((p) => p.id === protoId);
      const protoTitle = proto ? proto.title : "Protocolo";

      try {
        const res = await fetch("/api/notebook/protocols/copy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ date: refDate, protocol_id: protoId }),
        });
        const data = await res.json();
        if (data.status === "ok" && Array.isArray(data.registro_content)) {
          linesData = data.registro_content;
          if (linesContainer) renderLines();
          alert(`Atividades do protocolo "${protoTitle}" copiadas para o Registro Pessoal com check-box!`);
        } else {
          alert(data.message || "Erro ao copiar atividades do protocolo.");
        }
      } catch (err) {
        console.error("Erro ao copiar protocolo:", err);
        alert("Erro de conexão ao copiar atividades.");
      }
    });
  });

  // --- PROTOCOLOS: PAINEL DE CRIAÇÃO, EDIÇÃO E EXCLUSÃO ---
  const btnOpenProtoPanel = document.getElementById("btn-open-protocol-panel");
  const btnCloseProtoPanel = document.getElementById("btn-close-protocol-panel");
  const btnCancelProto = document.getElementById("btn-cancel-protocol");
  const panelProto = document.getElementById("protocol-editor-panel");
  const formProto = document.getElementById("form-protocol");
  const titleProtoEditor = document.getElementById("protocol-editor-title");
  const inputProtoId = document.getElementById("protocol-id-input");
  const inputProtoTitle = document.getElementById("protocol-title-input");
  const inputProtoTime = document.getElementById("protocol-time-input");
  const inputProtoDuration = document.getElementById("protocol-duration-input");
  const inputProtoObjective = document.getElementById("protocol-objective-input");
  const inputProtoActivities = document.getElementById("protocol-activities-input");
  const btnDeleteProtoForm = document.getElementById("btn-delete-protocol-form");

  function openProtocolForm(proto = null) {
    if (!panelProto) return;
    panelProto.style.display = "block";
    if (proto) {
      if (titleProtoEditor) titleProtoEditor.textContent = "Editar Protocolo";
      if (inputProtoId) inputProtoId.value = proto.id;
      if (inputProtoTitle) inputProtoTitle.value = proto.title || "";
      if (inputProtoTime) inputProtoTime.value = proto.recommended_time || "";
      if (inputProtoDuration) inputProtoDuration.value = proto.avg_duration_minutes || 15;
      if (inputProtoObjective) inputProtoObjective.value = proto.objective || "";
      if (inputProtoActivities) inputProtoActivities.value = Array.isArray(proto.activities) ? proto.activities.join("\n") : "";
      if (btnDeleteProtoForm) btnDeleteProtoForm.style.display = "inline-block";
    } else {
      if (titleProtoEditor) titleProtoEditor.textContent = "Novo Protocolo";
      if (inputProtoId) inputProtoId.value = "";
      if (inputProtoTitle) inputProtoTitle.value = "";
      if (inputProtoTime) inputProtoTime.value = "";
      if (inputProtoDuration) inputProtoDuration.value = 15;
      if (inputProtoObjective) inputProtoObjective.value = "";
      if (inputProtoActivities) inputProtoActivities.value = "";
      if (btnDeleteProtoForm) btnDeleteProtoForm.style.display = "none";
    }
    panelProto.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closeProtocolForm() {
    if (panelProto) panelProto.style.display = "none";
  }

  if (btnOpenProtoPanel) {
    btnOpenProtoPanel.addEventListener("click", () => openProtocolForm(null));
  }
  if (btnCloseProtoPanel) {
    btnCloseProtoPanel.addEventListener("click", closeProtocolForm);
  }
  if (btnCancelProto) {
    btnCancelProto.addEventListener("click", closeProtocolForm);
  }

  if (formProto) {
    formProto.addEventListener("submit", async (e) => {
      e.preventDefault();
      const protoId = inputProtoId ? inputProtoId.value : "";
      const title = inputProtoTitle ? inputProtoTitle.value.trim() : "";
      const timeStr = inputProtoTime ? inputProtoTime.value.trim() : "";
      const duration = inputProtoDuration ? parseInt(inputProtoDuration.value, 10) || 15 : 15;
      const objective = inputProtoObjective ? inputProtoObjective.value.trim() : "";
      const activitiesRaw = inputProtoActivities ? inputProtoActivities.value : "";
      const activities = activitiesRaw.split("\n").map((a) => a.trim()).filter((a) => a.length > 0);

      if (!title || !objective) return;

      const endpoint = protoId ? "/api/notebook/protocols/update" : "/api/notebook/protocols/add";
      const payload = {
        title: title,
        objective: objective,
        activities: activities,
        avg_duration_minutes: duration,
        recommended_time: timeStr,
      };
      if (protoId) payload.id = parseInt(protoId, 10);

      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.status === "ok") {
          window.location.reload();
        } else {
          alert(data.message || "Erro ao salvar protocolo.");
        }
      } catch (err) {
        console.error("Erro ao salvar protocolo:", err);
      }
    });
  }

  async function deleteProtocolById(protoId) {
    if (!protoId) return;
    if (!confirm("Deseja realmente excluir este protocolo?")) return;
    try {
      const res = await fetch("/api/notebook/protocols/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: protoId }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        window.location.reload();
      } else {
        alert(data.message || "Erro ao excluir protocolo.");
      }
    } catch (err) {
      console.error("Erro ao excluir protocolo:", err);
    }
  }

  if (btnDeleteProtoForm) {
    btnDeleteProtoForm.addEventListener("click", () => {
      const protoId = inputProtoId ? parseInt(inputProtoId.value, 10) : null;
      if (protoId) deleteProtocolById(protoId);
    });
  }

  document.querySelectorAll(".btn-edit-protocol").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const protoId = parseInt(btn.getAttribute("data-protocol-id"), 10);
      const protocols = window.NOTEBOOK_PROTOCOLS || [];
      const proto = protocols.find((p) => p.id === protoId);
      if (proto) {
        openProtocolForm(proto);
      }
    });
  });

  document.querySelectorAll(".btn-delete-protocol").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const protoId = parseInt(btn.getAttribute("data-protocol-id"), 10);
      if (protoId) deleteProtocolById(protoId);
    });
  });

  // --- FORMULÁRIO PROGRAMAÇÃO POR DATA ---
  const formProg = document.getElementById("form-programacao");
  if (formProg) {
    formProg.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("prog-text-input");
      if (!input || !input.value) return;
      const text = input.value.trim();
      if (!text) return;

      try {
        const res = await fetch("/api/notebook/programacao/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_date: refDate, text: text }),
        });
        const data = await res.json();
        if (data.status === "ok") {
          window.location.reload();
        }
      } catch (err) {
        console.error("Erro ao salvar programação:", err);
      }
    });
  }

  // --- FORMULÁRIO PÓS-CICLO ---
  const formPosCiclo = document.getElementById("form-pos-ciclo");
  if (formPosCiclo) {
    formPosCiclo.addEventListener("submit", async (e) => {
      e.preventDefault();
      const formData = new FormData(formPosCiclo);
      const dateVal = formData.get("date") || refDate;
      const contentVal = (formData.get("content") || "").toString().trim();
      const categoryVal = (formData.get("category") || "lembrete").toString();
      if (!contentVal) return;

      try {
        const res = await fetch("/api/notebook/pos_ciclos/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            date: dateVal,
            content: contentVal,
            category: categoryVal,
          }),
        });
        const data = await res.json();
        if (data.status === "ok") {
          window.location.reload();
        }
      } catch (err) {
        console.error("Erro ao salvar nota pós-ciclo:", err);
      }
    });
  }

  document.querySelectorAll(".btn-toggle-note").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const noteId = parseInt(btn.getAttribute("data-note-id"), 10);
      try {
        const res = await fetch("/api/notebook/pos_ciclos/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note_id: noteId }),
        });
        const data = await res.json();
        if (data.status === "ok") {
          window.location.reload();
        }
      } catch (err) { }
    });
  });

  document.querySelectorAll(".btn-delete-note").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const noteId = parseInt(btn.getAttribute("data-note-id"), 10);
      if (!noteId) return;
      try {
        const res = await fetch("/api/notebook/pos_ciclos/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note_id: noteId }),
        });
        const data = await res.json();
        if (data.status === "ok") {
          const card = btn.closest(".note-card");
          if (card) {
            card.remove();
          } else {
            window.location.reload();
          }
        }
      } catch (err) {
        console.error("Erro ao excluir nota pós-ciclo:", err);
      }
    });
  });

  document.querySelectorAll(".btn-delete-prog").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const itemId = parseInt(btn.getAttribute("data-item-id"), 10);
      if (!itemId) return;
      try {
        const res = await fetch("/api/notebook/programacao/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ item_id: itemId }),
        });
        const data = await res.json();
        if (data.status === "ok") {
          const li = btn.closest(".prog-item");
          if (li) {
            li.remove();
          } else {
            window.location.reload();
          }
        }
      } catch (err) {
        console.error("Erro ao excluir item de programação:", err);
      }
    });
  });

  // Renderizar inicialmente se existir container de linhas
  if (linesContainer) {
    renderLines();
  }
})();
