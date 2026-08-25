/**
 * ReClaim — Core Frontend Interaction Engine
 * Supports theme switching, live search & category chips, image drag & drop,
 * copy-to-clipboard, toast notifications, confirmation modals, and mobile navigation.
 */

(function () {
  'use strict';

  // ==========================================
  // 1. COOKIE & STORAGE HELPERS
  // ==========================================
  function setCookie(name, value, days) {
    let expires = "";
    if (days) {
      const date = new Date();
      date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
      expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + (value || "") + expires + "; path=/; SameSite=Lax";
  }

  function getCookie(name) {
    const nameEQ = name + "=";
    const ca = document.cookie.split(';');
    for (let i = 0; i < ca.length; i++) {
      let c = ca[i];
      while (c.charAt(0) === ' ') c = c.substring(1, c.length);
      if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
    }
    return null;
  }

  // ==========================================
  // 2. THEME TOGGLE (DARK / LIGHT)
  // ==========================================
  const themeToggleBtn = document.getElementById("theme-toggle");
  const currentTheme = getCookie("reclaim_theme") || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? "dark" : "light");

  function applyTheme(theme) {
    const isDark = theme === "dark";
    document.body.classList.toggle("theme-dark", isDark);
    document.body.classList.toggle("theme-light", !isDark);
    setCookie("reclaim_theme", theme, 365);

    if (themeToggleBtn) {
      const icon = themeToggleBtn.querySelector("i");
      if (icon) {
        icon.className = isDark ? "fa-solid fa-sun" : "fa-regular fa-moon";
      }
    }
  }

  // Initial sync
  applyTheme(currentTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", function () {
      const isCurrentlyDark = document.body.classList.contains("theme-dark");
      applyTheme(isCurrentlyDark ? "light" : "dark");
    });
  }

  // ==========================================
  // 3. MOBILE NAVIGATION DRAWER
  // ==========================================
  const mobileToggle = document.getElementById("mobile-toggle");
  const mobileClose = document.getElementById("mobile-close");
  const mobileDrawer = document.getElementById("mobile-drawer");

  function openMobileNav() {
    if (!mobileDrawer) return;
    mobileDrawer.classList.add("open");
    mobileDrawer.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeMobileNav() {
    if (!mobileDrawer) return;
    mobileDrawer.classList.remove("open");
    mobileDrawer.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  if (mobileToggle) mobileToggle.addEventListener("click", openMobileNav);
  if (mobileClose) mobileClose.addEventListener("click", closeMobileNav);
  if (mobileDrawer) {
    mobileDrawer.addEventListener("click", function (e) {
      if (e.target === mobileDrawer) closeMobileNav();
    });
  }

  // ==========================================
  // 4. TOAST NOTIFICATION STACK
  // ==========================================
  window.showToast = function (message, type = "info", duration = 4500) {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let iconClass = "fa-circle-info";
    if (type === "success") iconClass = "fa-circle-check";
    else if (type === "danger" || type === "error") iconClass = "fa-circle-exclamation";
    else if (type === "warning") iconClass = "fa-triangle-exclamation";

    toast.innerHTML = `
      <div class="toast-icon"><i class="fa-solid ${iconClass}"></i></div>
      <div class="toast-content">${message}</div>
      <button type="button" class="toast-close" aria-label="Close">&times;</button>
    `;

    const closeBtn = toast.querySelector(".toast-close");
    const removeToast = () => {
      toast.classList.add("toast-hiding");
      setTimeout(() => {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
      }, 250);
    };

    closeBtn.addEventListener("click", removeToast);
    container.appendChild(toast);

    if (duration > 0) {
      setTimeout(removeToast, duration);
    }
  };

  // Convert server flash messages to toasts
  document.querySelectorAll(".server-flash-item").forEach(function (el) {
    const msg = el.dataset.message;
    const type = el.dataset.category || "info";
    if (msg) window.showToast(msg, type);
  });

  // ==========================================
  // 5. GLOBAL CONFIRMATION MODAL
  // ==========================================
  const modalOverlay = document.getElementById("confirm-modal");
  const modalTitle = document.getElementById("modal-title");
  const modalBody = document.getElementById("modal-body");
  const modalOk = document.getElementById("modal-ok");
  const modalCancel = document.getElementById("modal-cancel");

  let pendingForm = null;

  window.openConfirmModal = function ({ title, message, okText = "Yes, continue", isDanger = true, onConfirm }) {
    if (!modalOverlay) return;
    if (modalTitle) modalTitle.textContent = title || "Confirm Action";
    if (modalBody) modalBody.textContent = message || "Are you sure you want to proceed?";
    if (modalOk) {
      modalOk.textContent = okText;
      modalOk.className = isDanger ? "btn btn-danger" : "btn btn-primary";
    }

    modalOverlay.classList.add("active");
    modalOverlay.setAttribute("aria-hidden", "false");

    const handleOk = function () {
      modalOverlay.classList.remove("active");
      modalOverlay.setAttribute("aria-hidden", "true");
      modalOk.removeEventListener("click", handleOk);
      if (typeof onConfirm === "function") onConfirm();
    };

    modalOk.onclick = handleOk;
  };

  if (modalCancel) {
    modalCancel.addEventListener("click", function () {
      if (modalOverlay) {
        modalOverlay.classList.remove("active");
        modalOverlay.setAttribute("aria-hidden", "true");
      }
    });
  }

  // Intercept forms with data-confirm
  document.addEventListener("submit", function (e) {
    const form = e.target;
    const confirmMsg = form.dataset.confirm;
    if (confirmMsg) {
      e.preventDefault();
      window.openConfirmModal({
        title: form.dataset.confirmTitle || "Confirm",
        message: confirmMsg,
        okText: form.dataset.confirmOk || "Yes, proceed",
        isDanger: form.dataset.confirmDanger !== "false",
        onConfirm: () => form.submit()
      });
    }
  });

  // ==========================================
  // 6. DRAG & DROP FILE UPLOAD WITH PREVIEW
  // ==========================================
  document.querySelectorAll(".dropzone-container").forEach(function (dropzone) {
    const fileInput = dropzone.querySelector("input[type='file']");
    const previewContainer = dropzone.querySelector(".dropzone-preview-wrap");
    const previewImg = dropzone.querySelector(".dropzone-preview-img");
    const removeBtn = dropzone.querySelector(".dropzone-remove-btn");
    const dropzonePrompt = dropzone.querySelector(".dropzone-prompt");

    if (!fileInput) return;

    function handleFile(file) {
      if (!file) return;
      const validTypes = ["image/jpeg", "image/png", "image/webp", "image/jpg"];
      if (!validTypes.includes(file.type)) {
        window.showToast("Please upload a PNG, JPG, or WEBP image.", "danger");
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        window.showToast("File size exceeds 5MB limit.", "danger");
        return;
      }

      const reader = new FileReader();
      reader.onload = function (e) {
        if (previewImg) previewImg.src = e.target.result;
        if (previewContainer) previewContainer.style.display = "inline-block";
        if (dropzonePrompt) dropzonePrompt.style.display = "none";
      };
      reader.readAsDataURL(file);
    }

    fileInput.addEventListener("change", function () {
      if (fileInput.files && fileInput.files[0]) {
        handleFile(fileInput.files[0]);
      }
    });

    dropzone.addEventListener("dragover", function (e) {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    });

    dropzone.addEventListener("dragleave", function () {
      dropzone.classList.remove("drag-over");
    });

    dropzone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        fileInput.files = e.dataTransfer.files;
        handleFile(e.dataTransfer.files[0]);
      }
    });

    if (removeBtn) {
      removeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        fileInput.value = "";
        if (previewContainer) previewContainer.style.display = "none";
        if (dropzonePrompt) dropzonePrompt.style.display = "block";
      });
    }
  });

  // ==========================================
  // 7. COPY TO CLIPBOARD
  // ==========================================
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      const textToCopy = btn.dataset.copy;
      if (!textToCopy) return;

      navigator.clipboard.writeText(textToCopy).then(function () {
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
        window.showToast("Copied to clipboard: " + textToCopy, "success");
        setTimeout(function () {
          btn.innerHTML = originalHtml;
        }, 2000);
      }).catch(function () {
        window.showToast("Could not copy text.", "danger");
      });
    });
  });

  // ==========================================
  // 8. CLIENT-SIDE LIVE SEARCH & FILTERING
  // ==========================================
  const liveSearchInput = document.getElementById("live-search-input");
  const categoryChips = document.querySelectorAll(".chip[data-category]");
  const tabButtons = document.querySelectorAll(".tab-btn[data-tab]");
  const itemCards = document.querySelectorAll(".filterable-item");

  let activeCategory = "all";
  let activeTab = "all";
  let searchQuery = "";

  function filterCards() {
    let visibleCount = 0;
    let lostVisible = 0;
    let foundVisible = 0;
    const query = (liveSearchInput ? liveSearchInput.value : "").toLowerCase().trim();

    itemCards.forEach(function (card) {
      const name = (card.dataset.name || "").toLowerCase();
      const desc = (card.dataset.desc || "").toLowerCase();
      const location = (card.dataset.location || "").toLowerCase();
      const category = (card.dataset.category || "").toLowerCase();
      const itemType = (card.dataset.type || "").toLowerCase(); // lost / found
      const status = (card.dataset.status || "").toLowerCase(); // active / returned

      const matchesText = !query || name.includes(query) || desc.includes(query) || location.includes(query) || category.includes(query);
      const matchesCategory = activeCategory === "all" || category === activeCategory.toLowerCase();
      
      let matchesTab = true;
      if (activeTab === "lost") matchesTab = itemType === "lost" && (status === "active" || status === "");
      else if (activeTab === "found") matchesTab = itemType === "found" && (status === "active" || status === "");
      else if (activeTab === "returned") matchesTab = status === "returned";

      const isVisible = matchesText && matchesCategory && matchesTab;
      card.style.display = isVisible ? "" : "none";
      if (isVisible) {
        visibleCount++;
        if (itemType === "lost") lostVisible++;
        if (itemType === "found") foundVisible++;
      }
    });

    // Toggle entire sections according to active tab
    const lostSection = document.getElementById("lost-section");
    const foundSection = document.getElementById("found-section");
    if (lostSection) {
      if (activeTab === "found") {
        lostSection.style.display = "none";
      } else {
        lostSection.style.display = (lostVisible === 0 && query) ? "none" : "";
      }
    }
    if (foundSection) {
      if (activeTab === "lost") {
        foundSection.style.display = "none";
      } else {
        foundSection.style.display = (foundVisible === 0 && query) ? "none" : "";
      }
    }

    // Update global empty notice if present
    const emptyNotice = document.getElementById("live-empty-state");
    if (emptyNotice) {
      emptyNotice.style.display = visibleCount === 0 ? "block" : "none";
    }
  }

  if (liveSearchInput) {
    liveSearchInput.addEventListener("input", filterCards);
  }

  categoryChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      categoryChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      activeCategory = chip.dataset.category;
      filterCards();
    });
  });

  tabButtons.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabButtons.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activeTab = tab.dataset.tab;
      filterCards();
    });
  });

  // ==========================================
  // 9. PASSWORD VISIBILITY TOGGLE
  // ==========================================
  document.querySelectorAll(".toggle-password-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const targetId = btn.dataset.target;
      const input = document.getElementById(targetId);
      if (!input) return;
      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      const icon = btn.querySelector("i");
      if (icon) {
        icon.className = isPassword ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
      }
    });
  });

})();