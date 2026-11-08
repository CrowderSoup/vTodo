(function () {
  var draggingColumnId = null;
  var draggingLaneKind = null;
  var draggingTaskId = null;
  var draggingCard = null;
  var draggingStatusId = null;
  var dropTargetCard = null;
  var dropPosition = null;
  var notesEditor = null;
  var commentEditor = null;
  var pendingConfirmAction = null;

  function getConfirmModalElements() {
    return {
      modal: document.getElementById("confirm-modal"),
      message: document.getElementById("confirm-modal-message"),
      confirmButton: document.getElementById("confirm-modal-confirm"),
      cancelButton: document.getElementById("confirm-modal-cancel"),
    };
  }

  function isConfirmModalOpen() {
    var modal = getConfirmModalElements().modal;
    return !!(modal && modal.open);
  }

  function resetConfirmModal() {
    var elements = getConfirmModalElements();
    if (elements.message) {
      elements.message.textContent = "";
    }
    if (elements.confirmButton) {
      elements.confirmButton.textContent = "Confirm";
      elements.confirmButton.classList.remove("btn-danger");
      elements.confirmButton.classList.add("btn-primary");
    }
    pendingConfirmAction = null;
    document.body.classList.remove("confirm-modal-open");
  }

  function closeConfirmModal() {
    var modal = getConfirmModalElements().modal;
    if (!modal) {
      resetConfirmModal();
      return;
    }

    if (modal.open) {
      modal.close();
      return;
    }

    resetConfirmModal();
  }

  function setConfirmButtonState(question) {
    var confirmButton = getConfirmModalElements().confirmButton;
    if (!confirmButton) {
      return;
    }

    var destructiveMatch = question.match(/^\s*(delete|archive|remove)\b/i);
    if (destructiveMatch) {
      confirmButton.textContent = destructiveMatch[1].charAt(0).toUpperCase() + destructiveMatch[1].slice(1);
      confirmButton.classList.remove("btn-primary");
      confirmButton.classList.add("btn-danger");
      return;
    }

    confirmButton.textContent = "Confirm";
    confirmButton.classList.remove("btn-danger");
    confirmButton.classList.add("btn-primary");
  }

  function openConfirmModal(question, onConfirm) {
    var elements = getConfirmModalElements();
    if (!elements.modal || !elements.message || typeof elements.modal.showModal !== "function") {
      return false;
    }

    if (elements.modal.open) {
      elements.modal.close();
    }

    elements.message.textContent = question;
    setConfirmButtonState(question);
    pendingConfirmAction = onConfirm;
    elements.modal.showModal();
    document.body.classList.add("confirm-modal-open");

    window.requestAnimationFrame(function () {
      if (elements.confirmButton) {
        elements.confirmButton.focus();
      }
    });

    return true;
  }

  function getCsrfToken() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
  }

  function restoreNode(parent, node, next) {
    if (!parent || !node) {
      return;
    }
    if (next && next.parentNode !== parent) {
      next = null;
    }
    parent.insertBefore(node, next);
  }

  function postJson(url, payload, undo) {
    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(payload),
    }).then(function (response) {
      if (!response.ok && undo) {
        undo();
      }
    }).catch(function () {
      if (undo) {
        undo();
      }
    });
  }

  function clearCardDropIndicators() {
    document.querySelectorAll(".task-card.drop-before, .task-card.drop-after").forEach(function (card) {
      card.classList.remove("drop-before", "drop-after");
    });
  }

  function destroyEditors() {
    if (notesEditor) {
      notesEditor.toTextArea();
      notesEditor = null;
    }
    if (commentEditor) {
      commentEditor.toTextArea();
      commentEditor = null;
    }
  }

  function initTaskEditors() {
    var notesTextarea = document.getElementById("task-notes-editor");
    if (notesTextarea && window.EasyMDE) {
      if (notesEditor) {
        notesEditor.toTextArea();
      }
      notesEditor = new window.EasyMDE({
        element: notesTextarea,
        spellChecker: false,
        status: false,
        autoDownloadFontAwesome: true,
        minHeight: "180px",
      });
      notesEditor.codemirror.on("change", function () {
        notesTextarea.value = notesEditor.value();
      });
      notesTextarea.value = notesEditor.value();
    }

    var commentTextarea = document.getElementById("task-comment-editor");
    if (commentTextarea && window.EasyMDE) {
      if (commentEditor) {
        commentEditor.toTextArea();
      }
      commentEditor = new window.EasyMDE({
        element: commentTextarea,
        spellChecker: false,
        status: false,
        autoDownloadFontAwesome: true,
        minHeight: "100px",
      });
      commentEditor.codemirror.on("change", function () {
        commentTextarea.value = commentEditor.value();
      });
      commentTextarea.value = commentEditor.value();
    }
  }

  function getTagInputElements(container) {
    return {
      container: container,
      chips: container.querySelector("[data-tag-chips]"),
      field: container.querySelector("[data-tag-field]"),
      suggestions: container.querySelector("[data-tag-suggestions]"),
      hiddenInput: document.getElementById(container.dataset.fieldId),
      knownTagsScript: document.getElementById(container.dataset.fieldId + "-known-tags"),
    };
  }

  function tagInputCurrentTags(els) {
    return Array.from(els.chips.querySelectorAll("[data-tag]")).map(function (chip) {
      return chip.dataset.tag;
    });
  }

  function tagInputSyncHidden(els) {
    els.hiddenInput.value = tagInputCurrentTags(els).join(", ");
  }

  function tagInputAddChip(els, rawValue) {
    var value = rawValue.trim();
    if (!value) {
      return;
    }
    var existing = tagInputCurrentTags(els).map(function (t) { return t.toLowerCase(); });
    if (existing.indexOf(value.toLowerCase()) !== -1) {
      return;
    }

    var chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.dataset.tag = value;

    var label = document.createElement("span");
    label.className = "tag-chip-label";
    label.textContent = value;

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "tag-chip-remove";
    remove.setAttribute("data-tag-remove", "");
    remove.setAttribute("aria-label", "Remove tag " + value);
    remove.textContent = "×";

    chip.appendChild(label);
    chip.appendChild(remove);
    els.chips.appendChild(chip);
    tagInputSyncHidden(els);
  }

  function tagInputRemoveLastChip(els) {
    var chips = els.chips.querySelectorAll("[data-tag]");
    if (!chips.length) {
      return;
    }
    chips[chips.length - 1].remove();
    tagInputSyncHidden(els);
  }

  function tagInputKnownTags(els) {
    if (!els.knownTagsScript) {
      return [];
    }
    try {
      return JSON.parse(els.knownTagsScript.textContent) || [];
    } catch (e) {
      return [];
    }
  }

  function tagInputHideSuggestions(els) {
    els.suggestions.hidden = true;
    els.suggestions.innerHTML = "";
  }

  function tagInputShowSuggestions(els) {
    var query = els.field.value.trim().toLowerCase();
    var current = tagInputCurrentTags(els).map(function (t) { return t.toLowerCase(); });
    var matches = tagInputKnownTags(els).filter(function (tag) {
      var lower = tag.toLowerCase();
      return current.indexOf(lower) === -1 && (!query || lower.indexOf(query) !== -1);
    }).slice(0, 8);

    if (!matches.length) {
      tagInputHideSuggestions(els);
      return;
    }

    els.suggestions.innerHTML = "";
    matches.forEach(function (tag) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "tag-input-suggestion";
      button.textContent = tag;
      // mousedown (not click) so preventDefault stops the field from
      // blurring first -- otherwise the suggestion list would already be
      // hidden by the blur handler before the click fires.
      button.addEventListener("mousedown", function (event) {
        event.preventDefault();
        tagInputAddChip(els, tag);
        els.field.value = "";
        tagInputHideSuggestions(els);
        els.field.focus();
      });
      item.appendChild(button);
      els.suggestions.appendChild(item);
    });
    els.suggestions.hidden = false;
  }

  function initTagInput(container) {
    if (container.dataset.tagInputInitialized) {
      return;
    }
    container.dataset.tagInputInitialized = "true";

    var els = getTagInputElements(container);
    if (!els.hiddenInput || !els.field || !els.chips) {
      return;
    }

    els.hiddenInput.value.split(",").map(function (t) { return t.trim(); }).filter(Boolean).forEach(function (tag) {
      tagInputAddChip(els, tag);
    });

    els.field.addEventListener("input", function () {
      tagInputShowSuggestions(els);
    });

    els.field.addEventListener("focus", function () {
      tagInputShowSuggestions(els);
    });

    els.field.addEventListener("blur", function () {
      tagInputHideSuggestions(els);
    });

    els.field.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        tagInputAddChip(els, els.field.value);
        els.field.value = "";
        tagInputHideSuggestions(els);
        return;
      }
      if (event.key === "Backspace" && !els.field.value) {
        tagInputRemoveLastChip(els);
        return;
      }
      if (event.key === "Escape") {
        tagInputHideSuggestions(els);
      }
    });

    els.chips.addEventListener("click", function (event) {
      var removeButton = event.target.closest("[data-tag-remove]");
      if (!removeButton) {
        return;
      }
      removeButton.closest("[data-tag]").remove();
      tagInputSyncHidden(els);
    });
  }

  function initTagInputs(root) {
    (root || document).querySelectorAll("[data-tag-input]").forEach(function (container) {
      initTagInput(container);
    });
  }

  // Assignee picker: a single-select combobox over the people and agents who
  // can be assigned in the workspace (rendered as JSON next to the field).
  function initAssigneePicker(container) {
    if (container.dataset.assigneePickerInitialized) {
      return;
    }
    container.dataset.assigneePickerInitialized = "true";

    var fieldId = container.dataset.fieldId;
    var hidden = document.getElementById(fieldId);
    var search = container.querySelector("[data-assignee-search]");
    var chipSlot = container.querySelector("[data-assignee-chip]");
    var list = container.querySelector("[data-assignee-options]");
    var optionsScript = document.getElementById(fieldId + "-options");
    if (!hidden || !search || !chipSlot || !list) {
      return;
    }

    var options = [];
    try {
      options = JSON.parse(optionsScript ? optionsScript.textContent : "[]") || [];
    } catch (e) {
      options = [];
    }
    var matches = [];
    var activeIndex = -1;

    function label(option) {
      return option.name + (option.me ? " (you)" : "");
    }

    function selected() {
      var id = parseInt(hidden.value, 10);
      return options.find(function (option) { return option.id === id; }) || null;
    }

    function renderChip() {
      chipSlot.innerHTML = "";
      var option = selected();
      if (!option) {
        if (hidden.value) {
          // Someone who can no longer be assigned here. Keep the value until
          // it is changed, but say so rather than showing nothing.
          var stale = document.createElement("span");
          stale.className = "field-help";
          stale.textContent = "Someone who has left this workspace";
          chipSlot.appendChild(stale);
        }
        search.placeholder = "Search people and agents…";
        return;
      }
      var chip = document.createElement("span");
      chip.className = "tag-chip";

      var text = document.createElement("span");
      text.className = "tag-chip-label";
      text.textContent = label(option);
      chip.appendChild(text);

      if (option.agent) {
        var badge = document.createElement("span");
        badge.className = "assignee-agent-badge";
        badge.textContent = "agent";
        chip.appendChild(badge);
      }

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tag-chip-remove";
      remove.setAttribute("aria-label", "Unassign " + option.name);
      remove.textContent = "×";
      remove.addEventListener("click", function () {
        choose(null);
        search.focus();
      });
      chip.appendChild(remove);
      chipSlot.appendChild(chip);
      search.placeholder = "Change…";
    }

    function close() {
      list.hidden = true;
      list.innerHTML = "";
      search.setAttribute("aria-expanded", "false");
      search.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    }

    function choose(option) {
      hidden.value = option ? String(option.id) : "";
      search.value = "";
      close();
      renderChip();
    }

    function highlight(index) {
      var items = list.querySelectorAll("[role=option]");
      if (!items.length) {
        return;
      }
      activeIndex = (index + items.length) % items.length;
      items.forEach(function (item, i) {
        var on = i === activeIndex;
        item.classList.toggle("is-active", on);
        item.setAttribute("aria-selected", on ? "true" : "false");
        if (on) {
          search.setAttribute("aria-activedescendant", item.id);
          item.scrollIntoView({ block: "nearest" });
        }
      });
    }

    function open() {
      var query = search.value.trim().toLowerCase();
      var current = selected();
      matches = options.filter(function (option) {
        if (current && option.id === current.id) {
          return false;
        }
        return !query || option.name.toLowerCase().indexOf(query) !== -1;
      });

      list.innerHTML = "";
      activeIndex = -1;
      if (!matches.length) {
        var empty = document.createElement("li");
        empty.className = "tag-input-suggestion assignee-picker-empty";
        empty.textContent = query ? "No one matches “" + search.value.trim() + "”" : "No one else can be assigned here";
        list.appendChild(empty);
      }
      matches.forEach(function (option, i) {
        var item = document.createElement("li");
        item.id = fieldId + "-option-" + option.id;
        item.className = "tag-input-suggestion assignee-picker-option";
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", "false");

        var name = document.createElement("span");
        name.textContent = label(option);
        item.appendChild(name);
        if (option.agent) {
          var badge = document.createElement("span");
          badge.className = "assignee-agent-badge";
          badge.textContent = "agent";
          item.appendChild(badge);
        }

        // mousedown so the field doesn't blur (and close the list) first.
        item.addEventListener("mousedown", function (event) {
          event.preventDefault();
          choose(option);
        });
        item.addEventListener("mousemove", function () {
          if (activeIndex !== i) {
            highlight(i);
          }
        });
        list.appendChild(item);
      });
      list.hidden = false;
      search.setAttribute("aria-expanded", "true");
      if (query && matches.length) {
        highlight(0);
      }
    }

    search.addEventListener("focus", open);
    search.addEventListener("input", open);
    search.addEventListener("blur", close);
    search.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) {
          open();
        }
        highlight(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
        return;
      }
      if (event.key === "Enter") {
        // Never submit the form from the search box.
        event.preventDefault();
        if (activeIndex >= 0 && matches[activeIndex]) {
          choose(matches[activeIndex]);
        }
        return;
      }
      if (event.key === "Escape" && !list.hidden) {
        event.stopPropagation();
        close();
        return;
      }
      if (event.key === "Backspace" && !search.value && hidden.value) {
        choose(null);
        open();
      }
    });

    renderChip();
  }

  function initAssigneePickers(root) {
    (root || document).querySelectorAll("[data-assignee-picker]").forEach(initAssigneePicker);
  }

  function flushTagInputFields(event) {
    document.querySelectorAll("[data-tag-input]").forEach(function (container) {
      var els = getTagInputElements(container);
      if (!els.hiddenInput || !els.field) {
        return;
      }
      // Whatever's still typed but not yet committed to a chip counts too --
      // the old plain comma-separated input never lost a trailing, un-punctuated
      // tag either, so Enter/comma shouldn't be required just to not lose it.
      if (els.field.value.trim()) {
        tagInputAddChip(els, els.field.value);
        els.field.value = "";
      }

      var requestElement = event && (event.detail.elt || event.target);
      if (!requestElement || !requestElement.closest) {
        return;
      }
      var form = requestElement.matches("form") ? requestElement : requestElement.closest("form");
      if (form && form.contains(els.hiddenInput)) {
        event.detail.parameters[els.hiddenInput.name] = els.hiddenInput.value;
      }
    });
  }

  function syncEditorValue(event, editor, textareaId, fieldName) {
    if (!editor) {
      return;
    }

    var textarea = document.getElementById(textareaId);
    if (!textarea) {
      return;
    }

    var value = editor.value();
    textarea.value = value;

    var requestElement = event.detail.elt || event.target;
    if (!requestElement || !requestElement.closest) {
      return;
    }

    var form = requestElement.matches("form") ? requestElement : requestElement.closest("form");
    if (form && form.contains(textarea)) {
      // HTMX has already collected form values at configRequest time,
      // so update the request payload directly as well as the hidden textarea.
      event.detail.parameters[fieldName] = value;
    }
  }

  function syncThemeLabel() {
    var label = document.getElementById("theme-label");
    if (!label) {
      return;
    }
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    label.textContent = isDark ? "Light" : "Dark";
  }

  function closeOpenDisclosures(exception) {
    document.querySelectorAll(".calendar-day-popover.open, .filter-bar-popover.open, .nav-collapsible-menu.open, .user-menu-popover.open").forEach(function (menu) {
      if (menu !== exception && !(exception && menu.contains(exception))) {
        menu.classList.remove("open");
      }
    });
  }

  function openTaskPanel() {
    var panel = document.getElementById("task-panel");
    var overlay = document.getElementById("task-panel-overlay");
    if (!panel || !overlay) {
      return;
    }
    panel.classList.add("open");
    overlay.classList.add("open");
    document.body.classList.add("panel-open");
  }

  function closeTaskPanel() {
    var panel = document.getElementById("task-panel");
    var overlay = document.getElementById("task-panel-overlay");
    if (!panel || !overlay) {
      return;
    }
    panel.classList.remove("open");
    overlay.classList.remove("open");
    document.body.classList.remove("panel-open");
    destroyEditors();
  }

  function vtodoToggleTheme() {
    var html = document.documentElement;
    var isDark = html.getAttribute("data-theme") === "dark";
    var nextTheme = isDark ? "light" : "dark";
    html.setAttribute("data-theme", nextTheme);
    localStorage.setItem("vtodo-theme", nextTheme);
    syncThemeLabel();
  }

  document.addEventListener("DOMContentLoaded", function () {
    syncThemeLabel();
    initAssigneePickers(document);

    var confirmElements = getConfirmModalElements();
    if (confirmElements.cancelButton) {
      confirmElements.cancelButton.addEventListener("click", function () {
        closeConfirmModal();
      });
    }
    if (confirmElements.confirmButton) {
      confirmElements.confirmButton.addEventListener("click", function () {
        var confirmAction = pendingConfirmAction;
        closeConfirmModal();
        if (confirmAction) {
          confirmAction();
        }
      });
    }
    if (confirmElements.modal) {
      confirmElements.modal.addEventListener("close", function () {
        resetConfirmModal();
      });
      confirmElements.modal.addEventListener("click", function (event) {
        var rect = confirmElements.modal.getBoundingClientRect();
        var isBackdropClick = (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        );
        if (isBackdropClick) {
          closeConfirmModal();
        }
      });
    }
  });

  document.addEventListener("click", function (event) {
    var disclosureToggle = event.target.closest("[data-disclosure-toggle]");
    if (disclosureToggle) {
      event.preventDefault();
      var disclosure = disclosureToggle.nextElementSibling;
      if (disclosure) {
        var isOpen = disclosure.classList.contains("open");
        closeOpenDisclosures(isOpen ? null : disclosure);
        disclosure.classList.toggle("open");
      }
      return;
    }

    var modalOpenTrigger = event.target.closest("[data-open-modal]");
    if (modalOpenTrigger) {
      var modal = document.getElementById(modalOpenTrigger.getAttribute("data-open-modal"));
      if (modal && typeof modal.showModal === "function") {
        closeOpenDisclosures(null);
        modal.showModal();
        var nameInput = modal.querySelector('input[type="text"]');
        if (nameInput) {
          window.requestAnimationFrame(function () {
            nameInput.focus();
          });
        }
      }
      return;
    }

    var modalCloseTrigger = event.target.closest("[data-close-modal]");
    if (modalCloseTrigger) {
      var closingModal = modalCloseTrigger.closest("dialog");
      if (closingModal) {
        closingModal.close();
      }
      return;
    }

    if (event.target.tagName === "DIALOG" && event.target.hasAttribute("data-close-on-backdrop")) {
      event.target.close();
      return;
    }

    if (
      !event.target.closest(".filter-bar-trigger-container") &&
      !event.target.closest(".nav-collapsible-wrap") &&
      !event.target.closest(".user-menu")
    ) {
      closeOpenDisclosures(null);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      if (isConfirmModalOpen()) {
        return;
      }
      closeTaskPanel();
      closeOpenDisclosures(null);
    }
  });

  document.addEventListener("dragstart", function (event) {
    var handle = event.target.closest(".col-drag-handle[draggable]");
    if (handle) {
      draggingColumnId = handle.dataset.columnId;
      var column = handle.closest(".board-column");
      draggingLaneKind = column ? column.dataset.laneKind : null;
      event.dataTransfer.setData("text/plain", "col:" + draggingColumnId);
      event.dataTransfer.effectAllowed = "move";
      setTimeout(function () {
        if (column) {
          column.classList.add("col-dragging");
        }
      }, 0);
      return;
    }

    var card = event.target.closest(".task-card[draggable]");
    if (!card) {
      return;
    }
    draggingTaskId = card.dataset.taskId;
    draggingCard = card;
    event.dataTransfer.setData("text/plain", card.dataset.taskId);
    event.dataTransfer.effectAllowed = "move";
    setTimeout(function () {
      card.classList.add("dragging");
    }, 0);
  });

  document.addEventListener("dragend", function (event) {
    if (draggingColumnId) {
      var draggedColumn = document.querySelector('.board-column[data-column-id="' + draggingColumnId + '"]');
      if (draggedColumn) {
        draggedColumn.classList.remove("col-dragging");
      }
      draggingColumnId = null;
      draggingLaneKind = null;
      document.querySelectorAll(".board-column.col-drag-over").forEach(function (column) {
        column.classList.remove("col-drag-over");
      });
      return;
    }

    var draggedCard = event.target.closest(".task-card[draggable]");
    if (draggedCard) {
      draggedCard.classList.remove("dragging");
    }
    document.querySelectorAll(".task-list.drag-over").forEach(function (list) {
      list.classList.remove("drag-over");
    });
    clearCardDropIndicators();
    draggingTaskId = null;
    draggingCard = null;
    dropTargetCard = null;
    dropPosition = null;
  });

  document.addEventListener("dragover", function (event) {
    if (draggingColumnId) {
      var column = event.target.closest(".board-column");
      if (!column || column.dataset.columnId === draggingColumnId || column.dataset.laneKind !== draggingLaneKind) {
        return;
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      document.querySelectorAll(".board-column.col-drag-over").forEach(function (candidate) {
        if (candidate !== column) {
          candidate.classList.remove("col-drag-over");
        }
      });
      column.classList.add("col-drag-over");
      return;
    }

    var list = event.target.closest(".task-list");
    if (!list) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".task-list.drag-over").forEach(function (candidate) {
      if (candidate !== list) {
        candidate.classList.remove("drag-over");
      }
    });
    list.classList.add("drag-over");

    var targetCard = event.target.closest(".task-card");
    if (targetCard && targetCard.dataset.taskId !== draggingTaskId) {
      var rect = targetCard.getBoundingClientRect();
      var nextPosition = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
      if (targetCard !== dropTargetCard || nextPosition !== dropPosition) {
        clearCardDropIndicators();
        dropTargetCard = targetCard;
        dropPosition = nextPosition;
        targetCard.classList.add(nextPosition === "before" ? "drop-before" : "drop-after");
      }
    } else if (!targetCard) {
      clearCardDropIndicators();
      dropTargetCard = null;
      dropPosition = null;
    }
  });

  document.addEventListener("dragleave", function (event) {
    if (draggingColumnId) {
      var column = event.target.closest(".board-column");
      if (column && !column.contains(event.relatedTarget)) {
        column.classList.remove("col-drag-over");
      }
      return;
    }

    var list = event.target.closest(".task-list");
    if (list && !list.contains(event.relatedTarget)) {
      list.classList.remove("drag-over");
      clearCardDropIndicators();
      dropTargetCard = null;
      dropPosition = null;
    }
  });

  document.addEventListener("drop", function (event) {
    if (draggingColumnId) {
      var targetColumn = event.target.closest(".board-column");
      if (!targetColumn || targetColumn.dataset.columnId === draggingColumnId || targetColumn.dataset.laneKind !== draggingLaneKind) {
        return;
      }
      event.preventDefault();
      targetColumn.classList.remove("col-drag-over");

      var board = document.getElementById("task-list-content");
      if (!board) {
        return;
      }
      var columns = Array.from(board.querySelectorAll(".board-column"));
      var draggedElement = board.querySelector('.board-column[data-column-id="' + draggingColumnId + '"]');
      var draggedIndex = columns.indexOf(draggedElement);
      var targetIndex = columns.indexOf(targetColumn);
      var laneHome = draggedElement ? draggedElement.parentNode : null;
      var laneNext = draggedElement ? draggedElement.nextSibling : null;

      if (draggedElement) {
        if (draggedIndex < targetIndex) {
          board.insertBefore(draggedElement, targetColumn.nextSibling);
        } else {
          board.insertBefore(draggedElement, targetColumn);
        }
      }

      // Status lanes and custom (column) lanes are independent order sequences --
      // custom lanes always render after status lanes, so only same-kind lanes are
      // ever reordered against each other (see the dragover/drop kind guards above).
      var order = Array.from(board.querySelectorAll('.board-column[data-lane-kind="' + draggingLaneKind + '"]')).map(function (column) {
        return parseInt(column.dataset.columnId.split(":")[1], 10);
      });
      var reorderUrl = draggingLaneKind === "status" ? "/board/statuses/reorder/" : "/board/columns/reorder/";

      postJson(reorderUrl, { order: order }, function () {
        restoreNode(laneHome, draggedElement, laneNext);
      });

      if (draggedElement) {
        draggedElement.classList.remove("col-dragging");
      }
      draggingColumnId = null;
      draggingLaneKind = null;
      return;
    }

    var list = event.target.closest(".task-list");
    if (!list) {
      return;
    }
    event.preventDefault();
    list.classList.remove("drag-over");
    clearCardDropIndicators();

    var taskId = event.dataTransfer.getData("text/plain");
    var card = draggingCard;

    if (card && card.closest(".task-list") === list) {
      var cardHome = card.parentNode;
      var cardNext = card.nextSibling;
      if (dropTargetCard && dropTargetCard !== card) {
        if (dropPosition === "before") {
          list.insertBefore(card, dropTargetCard);
        } else {
          list.insertBefore(card, dropTargetCard.nextSibling);
        }
      }
      var newOrder = Array.from(list.querySelectorAll(".task-card")).map(function (taskCard) {
        return parseInt(taskCard.dataset.taskId, 10);
      });
      postJson("/board/tasks/reorder/", { order: newOrder }, function () {
        restoreNode(cardHome, card, cardNext);
      });
    } else {
      window.htmx.ajax("POST", "/board/tasks/" + taskId + "/move/", {
        target: "body",
        swap: "none",
        values: { new_status: list.dataset.defaultStatus },
      });
    }

    dropTargetCard = null;
    dropPosition = null;
    draggingTaskId = null;
    draggingCard = null;
  });

  document.addEventListener("htmx:configRequest", function (event) {
    var csrfToken = getCsrfToken();
    if (csrfToken) {
      event.detail.headers["X-CSRFToken"] = csrfToken;
    }

    syncEditorValue(event, notesEditor, "task-notes-editor", "notes");
    syncEditorValue(event, commentEditor, "task-comment-editor", "body");
    flushTagInputFields(event);
  });

  // Preserving the search node keeps live text; moving it during an OOB swap
  // can still blur it, so restore its focus and selection before returning.
  document.addEventListener("htmx:oobBeforeSwap", function (event) {
    var input = document.getElementById("board-filter-q");
    if (event.detail.target.id === "board-filter" && input === document.activeElement) {
      event.detail.searchSelection = {
        start: input.selectionStart,
        end: input.selectionEnd,
        direction: input.selectionDirection,
      };
    }
  });

  document.addEventListener("htmx:oobAfterSwap", function (event) {
    var selection = event.detail.searchSelection;
    var input = document.getElementById("board-filter-q");
    if (selection && input) {
      input.focus({ preventScroll: true });
      input.setSelectionRange(selection.start, selection.end, selection.direction);
      delete event.detail.searchSelection;
    }
  });

  // Only Clear filters and saved-view loads replace the user's live search text.
  document.addEventListener("boardSearchSync", function (event) {
    var input = document.getElementById("board-filter-q");
    if (input) {
      input.value = event.detail.q;
    }
  });

  document.addEventListener("htmx:afterSettle", function (event) {
    initTagInputs(event.target);
    initAssigneePickers(event.target);

    if (event.target.id === "task-panel-content") {
      var panel = document.getElementById("task-panel");
      if (panel && panel.classList.contains("open")) {
        initTaskEditors();
      }
    }
  });

  document.addEventListener("click", function (event) {
    if (event.target.closest(".tag-input")) {
      return;
    }
    document.querySelectorAll(".tag-input-suggestions:not([hidden])").forEach(function (list) {
      list.hidden = true;
      list.innerHTML = "";
    });
  });

  document.addEventListener("htmx:afterRequest", function (event) {
    if (event.target.id === "task-comment-form" && event.detail.successful && commentEditor) {
      commentEditor.value("");
    }
  });

  // Settings > Board Setup: drag-reorder the status list (independent of the live
  // board's column/lane drag handling above -- different page, own state, posts to
  // StatusReorderView).
  document.addEventListener("dragstart", function (event) {
    var handle = event.target.closest(".status-drag-handle[draggable]");
    if (!handle) {
      return;
    }
    var row = handle.closest(".status-row");
    draggingStatusId = handle.dataset.statusId;
    event.dataTransfer.setData("text/plain", "status:" + draggingStatusId);
    event.dataTransfer.effectAllowed = "move";
    setTimeout(function () {
      if (row) {
        row.classList.add("status-dragging");
      }
    }, 0);
  });

  document.addEventListener("dragend", function (event) {
    if (!draggingStatusId) {
      return;
    }
    var draggedRow = document.querySelector('.status-row[data-status-id="' + draggingStatusId + '"]');
    if (draggedRow) {
      draggedRow.classList.remove("status-dragging");
    }
    draggingStatusId = null;
    document.querySelectorAll(".status-row.status-drag-over").forEach(function (row) {
      row.classList.remove("status-drag-over");
    });
  });

  document.addEventListener("dragover", function (event) {
    if (!draggingStatusId) {
      return;
    }
    var row = event.target.closest(".status-row");
    if (!row || row.dataset.statusId === draggingStatusId) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".status-row.status-drag-over").forEach(function (candidate) {
      if (candidate !== row) {
        candidate.classList.remove("status-drag-over");
      }
    });
    row.classList.add("status-drag-over");
  });

  document.addEventListener("dragleave", function (event) {
    if (!draggingStatusId) {
      return;
    }
    var row = event.target.closest(".status-row");
    if (row && !row.contains(event.relatedTarget)) {
      row.classList.remove("status-drag-over");
    }
  });

  document.addEventListener("drop", function (event) {
    if (!draggingStatusId) {
      return;
    }
    var targetRow = event.target.closest(".status-row");
    if (!targetRow || targetRow.dataset.statusId === draggingStatusId) {
      return;
    }
    event.preventDefault();
    targetRow.classList.remove("status-drag-over");

    var list = document.getElementById("status-list");
    if (!list) {
      return;
    }
    var rows = Array.from(list.querySelectorAll(".status-row"));
    var draggedRow = list.querySelector('.status-row[data-status-id="' + draggingStatusId + '"]');
    var draggedIndex = rows.indexOf(draggedRow);
    var targetIndex = rows.indexOf(targetRow);
    var statusHome = draggedRow ? draggedRow.parentNode : null;
    var statusNext = draggedRow ? draggedRow.nextSibling : null;

    if (draggedRow) {
      if (draggedIndex < targetIndex) {
        targetRow.parentElement.insertBefore(draggedRow, targetRow.nextSibling);
      } else {
        targetRow.parentElement.insertBefore(draggedRow, targetRow);
      }
    }

    var order = Array.from(list.querySelectorAll(".status-row")).map(function (row) {
      return parseInt(row.dataset.statusId, 10);
    });

    postJson("/board/statuses/reorder/", { order: order }, function () {
      restoreNode(statusHome, draggedRow, statusNext);
    });

    if (draggedRow) {
      draggedRow.classList.remove("status-dragging");
    }
    draggingStatusId = null;
  });

  // Calendar: drag a task card onto a day cell or the no-date pane to reschedule
  // it. Uses a distinct .calendar-drop-zone class (never .task-list) so this never
  // double-fires alongside the board's own .task-list drag handling above.
  document.addEventListener("dragover", function (event) {
    var zone = event.target.closest(".calendar-drop-zone");
    if (!zone) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".calendar-drop-zone.drag-over").forEach(function (candidate) {
      if (candidate !== zone) {
        candidate.classList.remove("drag-over");
      }
    });
    zone.classList.add("drag-over");
  });

  document.addEventListener("dragleave", function (event) {
    var zone = event.target.closest(".calendar-drop-zone");
    if (zone && !zone.contains(event.relatedTarget)) {
      zone.classList.remove("drag-over");
    }
  });

  document.addEventListener("dragend", function () {
    document.querySelectorAll(".calendar-drop-zone.drag-over").forEach(function (zone) {
      zone.classList.remove("drag-over");
    });
  });

  document.addEventListener("drop", function (event) {
    var zone = event.target.closest(".calendar-drop-zone");
    if (!zone) {
      return;
    }
    event.preventDefault();
    zone.classList.remove("drag-over");

    var taskId = event.dataTransfer.getData("text/plain");
    var card = document.getElementById("task-" + taskId);
    if (card && card.closest(".calendar-drop-zone") === zone) {
      return;
    }

    window.htmx.ajax("POST", "/calendar/tasks/" + taskId + "/reschedule/", {
      target: "#task-list-content",
      swap: "innerHTML",
      values: { due_date: zone.dataset.date || "" },
    });
  });

  document.addEventListener("htmx:confirm", function (event) {
    if (!event.detail.question) {
      return;
    }

    event.preventDefault();

    var didOpenModal = openConfirmModal(event.detail.question, function () {
      event.detail.issueRequest(true);
    });

    if (!didOpenModal && window.confirm(event.detail.question)) {
      event.detail.issueRequest(true);
    }
  });

  window.openTaskPanel = openTaskPanel;
  window.closeTaskPanel = closeTaskPanel;
  window.vtodoToggleTheme = vtodoToggleTheme;
})();
