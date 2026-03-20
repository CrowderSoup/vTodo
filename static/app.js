(function () {
  var draggingColumnId = null;
  var draggingTaskId = null;
  var dropTargetCard = null;
  var dropPosition = null;
  var notesEditor = null;
  var commentEditor = null;

  function getCsrfToken() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
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
    document.querySelectorAll(".col-actions-menu.open, .save-filter-popover.open").forEach(function (menu) {
      if (menu !== exception) {
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

  function switchTab(name) {
    ["indieweb", "email"].forEach(function (tabName) {
      var tab = document.getElementById("tab-" + tabName);
      var panel = document.getElementById("panel-" + tabName);
      if (!tab || !panel) {
        return;
      }
      var isActive = tabName === name;
      tab.setAttribute("aria-selected", String(isActive));
      panel.hidden = !isActive;
    });
    if (window.location.hash !== "#" + name) {
      history.replaceState(null, "", "#" + name);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    syncThemeLabel();
    if (document.getElementById("tab-indieweb")) {
      var activeTab = window.location.hash.replace("#", "") === "email" ? "email" : "indieweb";
      switchTab(activeTab);
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

    if (!event.target.closest(".column-actions") && !event.target.closest(".save-filter-container")) {
      closeOpenDisclosures(null);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeTaskPanel();
      closeOpenDisclosures(null);
    }
  });

  document.addEventListener("dragstart", function (event) {
    var handle = event.target.closest(".col-drag-handle[draggable]");
    if (handle) {
      draggingColumnId = handle.dataset.columnId;
      event.dataTransfer.setData("text/plain", "col:" + draggingColumnId);
      event.dataTransfer.effectAllowed = "move";
      var column = handle.closest(".board-column");
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
    dropTargetCard = null;
    dropPosition = null;
  });

  document.addEventListener("dragover", function (event) {
    if (draggingColumnId) {
      var column = event.target.closest(".board-column");
      if (!column || column.dataset.columnId === draggingColumnId) {
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
      if (!targetColumn || targetColumn.dataset.columnId === draggingColumnId) {
        return;
      }
      event.preventDefault();
      targetColumn.classList.remove("col-drag-over");

      var board = document.getElementById("board-content");
      if (!board) {
        return;
      }
      var columns = Array.from(board.querySelectorAll(".board-column"));
      var draggedElement = board.querySelector('.board-column[data-column-id="' + draggingColumnId + '"]');
      var draggedIndex = columns.indexOf(draggedElement);
      var targetIndex = columns.indexOf(targetColumn);

      if (draggedElement) {
        if (draggedIndex < targetIndex) {
          board.insertBefore(draggedElement, targetColumn.nextSibling);
        } else {
          board.insertBefore(draggedElement, targetColumn);
        }
      }

      var order = Array.from(board.querySelectorAll(".board-column")).map(function (column) {
        return parseInt(column.dataset.columnId, 10);
      });

      fetch("/board/columns/reorder/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({ order: order }),
      });

      if (draggedElement) {
        draggedElement.classList.remove("col-dragging");
      }
      draggingColumnId = null;
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
    var card = document.getElementById("task-" + taskId);

    if (card && card.closest(".task-list") === list) {
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
      fetch("/board/tasks/reorder/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({ order: newOrder }),
      });
    } else {
      window.htmx.ajax("POST", "/board/tasks/" + taskId + "/move/", {
        target: "#board-content",
        swap: "innerHTML",
        values: { new_status: list.dataset.defaultStatus },
      });
    }

    dropTargetCard = null;
    dropPosition = null;
    draggingTaskId = null;
  });

  document.addEventListener("htmx:configRequest", function (event) {
    var csrfToken = getCsrfToken();
    if (csrfToken) {
      event.detail.headers["X-CSRFToken"] = csrfToken;
    }

    if (notesEditor) {
      var notesTextarea = document.getElementById("task-notes-editor");
      if (notesTextarea) {
        notesTextarea.value = notesEditor.value();
      }
    }

    if (commentEditor) {
      var commentTextarea = document.getElementById("task-comment-editor");
      if (commentTextarea) {
        commentTextarea.value = commentEditor.value();
      }
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id === "task-panel-content") {
      initTaskEditors();
    }
  });

  document.addEventListener("htmx:afterRequest", function (event) {
    if (event.target.id === "task-comment-form" && event.detail.successful && commentEditor) {
      commentEditor.value("");
    }
  });

  window.openTaskPanel = openTaskPanel;
  window.closeTaskPanel = closeTaskPanel;
  window.vtodoToggleTheme = vtodoToggleTheme;
  window.switchTab = switchTab;
})();
