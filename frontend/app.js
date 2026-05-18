import {
  API_BASE_URL,
  APP_OPTIONS,
  APP_BRAND,
  CATEGORY_COLORS
} from "./config.js";

const page = document.body?.dataset?.page || "";
const $ = (id) => document.getElementById(id);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const toast = $("toast");
const navLinks = $$(".tab-link");
const bottomLinks = [];
const topbar = document.querySelector(".topbar");
const mobileMenuBtn = null;
const menuScrim = null;
const menuBackBtn = null;
const brandName = null;
const brandSub = null;

const uploadInput = $("upload-input");
const uploadDrop = $("upload-drop");
const uploadName = $("upload-name");
const uploadSize = $("upload-size");
const uploadStatus = null; // removed in new UI
const startBtn = $("start-btn");
const progressBar = $("progress-bar");
const progressLabel = $("progress-label");
const statusFoot = $("status-foot");
const inferenceTime = $("inference-time");
const findingsList = $("findings-list");
const findingsMeta = $("findings-meta");
const copyFindingsBtn = $("copy-findings-btn");
const downloadFindingsBtn = $("download-findings-btn");
const toggleFindingsBtn = $("toggle-findings-btn");
const tamperedFlag = $("tampered-flag");
const tamperedValue = $("tampered-value");
const togglePreviewBtn = $("toggle-preview-btn");
const showAllOverlaysBtn = $("show-all-overlays-btn");
const previewCard = $("preview-card");
const previewViewer = $("preview-viewer");
const previewImage = $("preview-image");
const previewOverlay = $("preview-overlay");
const previewEmpty = $("preview-empty");
const previewScan = $("preview-scan");

const cropModal = $("crop-modal");
const cropImage = $("crop-image");
const cropMeta = $("crop-meta");
const cropCloseBtn = $("crop-close");
const showInDocumentBtn = $("show-in-document-btn");

const LAST_JOB_KEY = "forgensic_last_job";

let selectedFile = null;
let activeJobId = null;
let resultsPayload = null;
let resultCache = new Map();
let pageInitialized = false;
let pendingPreviewPage = null;
let previewLoaded = false;
let findingsTextCache = "";
let findingsFileNameCache = "";
let focusedFinding = null;
let selectedFinding = null;
let findingsAll = [];
let findingsShowAll = false;

const DEFAULT_FINDINGS_LIMIT = 5;

function showToast(message, variant = "info") {
  if (!toast) return;
  toast.textContent = message;
  toast.dataset.variant = variant;
  toast.classList.remove("hidden");
  clearTimeout(toast._timeoutId);
  toast._timeoutId = setTimeout(() => {
    toast.classList.add("hidden");
  }, 2800);
}

function updateBrand() {
  // Brand text is static in the new HTML; no dynamic update needed.
}

function setActiveNav() {
  navLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.tab === page);
  });
}

function setMobileMenuOpen(_open) { /* no-op: mobile menu removed in new UI */ }

function initMobileMenu() { /* no-op: mobile menu removed in new UI */ }

function setStatus(label, progress) {
  if (!progressLabel || !progressBar) return;
  progressLabel.textContent = label;
  progressBar.style.width = `${Math.max(0, Math.min(progress, 1)) * 100}%`;
}

function uploadWithProgress(formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/jobs`);
    xhr.upload.addEventListener("progress", (event) => {
      if (!onProgress) return;
      if (event.lengthComputable) {
        onProgress(event.loaded / event.total);
      } else {
        onProgress(null);
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (err) {
          reject(new Error("Invalid response"));
        }
        return;
      }
      reject(new Error(xhr.responseText || "Upload failed"));
    });
    xhr.addEventListener("error", () => reject(new Error("Upload failed")));
    xhr.send(formData);
  });
}

function setScanningState(active) {
  if (!previewCard) return;
  previewCard.classList.toggle("scanning", active);
  if (previewScan) previewScan.classList.toggle("active", active);
  if (previewEmpty) {
    previewEmpty.textContent = active ? "Processing preview..." : "No results yet.";
  }
  if (active) previewCard.classList.remove("hidden");
}

function formatBytes(bytes) {
  if (!bytes) return "0 MB";
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatSeconds(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  const precision = value < 10 ? 2 : 1;
  return `${value.toFixed(precision)} s`;
}

function setInferenceTime(totalSeconds, avgSeconds) {
  if (!inferenceTime) return;
  if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(totalSeconds)) {
    inferenceTime.textContent = "";
    return;
  }
  const hasAvg = avgSeconds !== null && avgSeconds !== undefined && !Number.isNaN(avgSeconds);
  const avgLabel = hasAvg ? ` (avg ${formatSeconds(avgSeconds)} / page)` : "";
  inferenceTime.textContent = `Inference time: ${formatSeconds(totalSeconds)}${avgLabel}`;
}

function getInferenceSeconds(job) {
  if (!job) return null;
  if (typeof job.inference_seconds === "number") return job.inference_seconds;
  if (typeof job.inference_ms === "number") return job.inference_ms / 1000;
  if (typeof job.result?.inference_seconds === "number") return job.result.inference_seconds;
  if (typeof job.result?.inference_ms === "number") return job.result.inference_ms / 1000;
  return null;
}

function getAvgInferenceSeconds(job) {
  if (!job) return null;
  if (typeof job.avg_inference_seconds === "number") return job.avg_inference_seconds;
  if (typeof job.result?.avg_inference_seconds === "number") return job.result.avg_inference_seconds;
  return null;
}

function positionOverlayToImage(targetImage, targetOverlay) {
  if (!targetImage || !targetOverlay) return;
  const viewer = targetImage.closest(".viewer");
  if (!viewer) return;
  const viewerRect = viewer.getBoundingClientRect();
  const imageRect = targetImage.getBoundingClientRect();
  if (!imageRect.width || !imageRect.height) return;
  const left = imageRect.left - viewerRect.left;
  const top = imageRect.top - viewerRect.top;
  targetOverlay.style.width = `${imageRect.width}px`;
  targetOverlay.style.height = `${imageRect.height}px`;
  targetOverlay.style.left = `${left}px`;
  targetOverlay.style.top = `${top}px`;
}

function setPreviewVisible(visible) {
  if (!previewViewer) return;
  previewViewer.classList.toggle("hidden", !visible);
  if (togglePreviewBtn) {
    togglePreviewBtn.textContent = visible ? "Hide rendered document" : "Show rendered document";
  }
  if (visible && pendingPreviewPage && !previewLoaded) {
    if (previewEmpty) {
      previewEmpty.textContent = "Loading preview...";
      previewEmpty.style.display = "block";
    }
    const previewUrl = getPreviewImageUrl(pendingPreviewPage);
    if (previewUrl) {
      loadPreviewImage(previewUrl);
    }
    renderPreviewOverlay(pendingPreviewPage);
    previewLoaded = true;
  }
}

function resetPreviewState(message) {
  pendingPreviewPage = null;
  previewLoaded = false;
  focusedFinding = null;
  selectedFinding = null;
  updateModalButtons();
  updateFocusButtons();
  if (previewImage) {
    previewImage.removeAttribute("src");
    previewImage.style.display = "none";
  }
  if (previewOverlay) previewOverlay.innerHTML = "";
  if (previewEmpty) {
    previewEmpty.textContent = message || "No rendered preview yet.";
    previewEmpty.style.display = "block";
  }
  setPreviewVisible(false);
}

function updateFocusButtons() {
  if (showAllOverlaysBtn) showAllOverlaysBtn.disabled = !focusedFinding;
}

function updateModalButtons() {
  if (showInDocumentBtn) showInDocumentBtn.disabled = !selectedFinding;
}

function getPreviewImageUrl(pageData) {
  if (!pageData) return null;
  return pageData.image_url || pageData.preview_url || null;
}

function getPageDataByNumber(pageNumber) {
  return (resultsPayload?.pages || []).find((page) => page.page_number === pageNumber);
}

function setFocusedFinding(finding) {
  focusedFinding = finding;
  updateFocusButtons();
  if (!resultsPayload) return;
  const pageData = getPageDataByNumber(finding.page);
  if (!pageData) {
    showToast("Preview not available for this finding", "error");
    return;
  }
  pendingPreviewPage = pageData;
  previewLoaded = false;
  setPreviewVisible(true);
  renderPreviewOverlay(pageData);
}

function clearFocusedFinding() {
  focusedFinding = null;
  updateFocusButtons();
  if (pendingPreviewPage) {
    renderPreviewOverlay(pendingPreviewPage);
  }
}

function buildCategorySummary(pages) {
  const counts = {};
  pages.forEach((pageItem) => {
    (pageItem.categories || []).forEach((cat) => {
      counts[cat] = (counts[cat] || 0) + 1;
    });
  });
  return counts;
}

function getCategorySummary(payload) {
  if (payload?.category_summary && Object.keys(payload.category_summary).length) {
    return payload.category_summary;
  }
  return buildCategorySummary(payload?.pages || []);
}

function updateTamperedFlag(summary) {
  if (!tamperedFlag || !tamperedValue) return;
  const keys = Object.keys(summary || {}).filter((key) => summary[key]);
  const isClean = keys.length === 0 || (keys.length === 1 && keys[0] === "C10");
  tamperedFlag.dataset.state = isClean ? "no" : "yes";
  tamperedValue.textContent = isClean ? "No" : "Yes";
  const icon = $("tampered-icon");
  if (icon) icon.textContent = isClean ? "✓" : "✗";
}

function buildFindingsText(payload) {
  const fileName = payload?.file_name || "document";
  const timestamp = new Date().toISOString();
  const findings = payload?.findings_summary?.findings_all || payload?.findings_summary?.findings || [];
  const summaryText = payload?.findings_summary?.summary_text || "No findings yet.";
  const lines = [
    `File: ${fileName}`,
    `Generated: ${timestamp}`,
    "",
    "Findings:",
  ];
  if (findings.length) {
    findings.forEach((item) => lines.push(`- ${item.summary || "Finding"}`));
  } else {
    lines.push(summaryText);
  }
  return lines.join("\n");
}

function setFindingsMeta(payload) {
  if (!findingsMeta) return;
  if (!payload) {
    findingsMeta.textContent = "No document processed yet.";
    return;
  }
  const fileName = payload.file_name || "Document";
  const updated = payload.updated_at ? `Updated ${payload.updated_at}` : "";
  findingsMeta.textContent = updated ? `${fileName} · ${updated}` : fileName;
}

function renderFindings(payload) {
  if (!findingsList) return;
  const summaryText = payload?.findings_summary?.summary_text || "No findings yet.";
  findingsAll = payload?.findings_summary?.findings_all || payload?.findings_summary?.findings || [];
  findingsShowAll = false;
  findingsList.innerHTML = "";
  if (!findingsAll.length) {
    findingsList.textContent = summaryText;
    updateFindingsToggle();
    return;
  }
  const initial = findingsAll.slice(0, DEFAULT_FINDINGS_LIMIT);
  renderFindingsList(initial);
  updateFindingsToggle();
}

function renderFindingsList(findings) {
  if (!findingsList) return;
  findingsList.innerHTML = "";
  findings.forEach((item) => {
    const row = document.createElement("div");
    row.className = "finding-item";
    const text = document.createElement("span");
    text.textContent = item.summary || "Finding";
    row.appendChild(text);
    if (item.box) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "finding-link";
      link.textContent = "View area";
      link.dataset.page = String(item.page || "");
      link.dataset.category = String(item.category_id || "");
      link.dataset.x = String(item.box.x ?? "");
      link.dataset.y = String(item.box.y ?? "");
      link.dataset.w = String(item.box.w ?? "");
      link.dataset.h = String(item.box.h ?? "");
      row.appendChild(link);
    }
    findingsList.appendChild(row);
  });
}

function updateFindingsToggle() {
  if (!toggleFindingsBtn) return;
  const hasMore = findingsAll.length > DEFAULT_FINDINGS_LIMIT;
  toggleFindingsBtn.style.display = hasMore ? "inline-flex" : "none";
  toggleFindingsBtn.textContent = findingsShowAll ? "Show top 5" : "View all";
}

function updateFindingsExport(payload) {
  findingsTextCache = buildFindingsText(payload);
  const rawName = payload?.file_name || "document";
  const baseName = rawName.replace(/\.[^/.]+$/, "");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  findingsFileNameCache = `${baseName}_findings_${stamp}.txt`;
}

function openCropModal(pageNumber, box) {
  if (!cropModal || !cropImage || !resultsPayload) return;
  const pageData = (resultsPayload.pages || []).find((page) => page.page_number === pageNumber);
  const imageUrl = pageData?.image_url || pageData?.preview_url;
  if (!imageUrl) {
    showToast("Preview not available for this finding", "error");
    return;
  }
  const resolvedUrl = imageUrl.startsWith("http") ? imageUrl : `${API_BASE_URL}${imageUrl}`;
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    const { x, y, w, h } = box;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(img, x, y, w, h, 0, 0, w, h);
    cropImage.src = canvas.toDataURL("image/png");
    if (cropMeta) {
      cropMeta.textContent = `Page ${pageNumber} · ${w}×${h}px`;
    }
    cropModal.classList.remove("hidden");
  };
  img.onerror = () => showToast("Failed to load preview", "error");
  img.src = resolvedUrl;
}

function closeCropModal() {
  if (!cropModal || !cropImage) return;
  cropImage.removeAttribute("src");
  cropModal.classList.add("hidden");
  selectedFinding = null;
  updateModalButtons();
}

function selectFile(file) {
  selectedFile = file;
  if (uploadName) uploadName.textContent = file ? file.name : "No file selected";
  if (uploadSize) uploadSize.textContent = file ? formatBytes(file.size) : "0 MB";
  if (uploadStatus) uploadStatus.textContent = file ? "Ready to analyze" : "Ready";
  resetPreviewState("No rendered preview yet.");
}

async function loadImageForTarget(imageUrl, targetImage, emptyEl) {
  if (!targetImage) return;
  const viewer = targetImage.closest(".viewer");
  const resolvedUrl = imageUrl.startsWith("http") ? imageUrl : `${API_BASE_URL}${imageUrl}`;
  targetImage.src = resolvedUrl;
  targetImage.style.display = "block";
  if (viewer) viewer.classList.add("has-image");
  if (emptyEl) emptyEl.style.display = "none";
}

async function loadPreviewImage(imageUrl) {
  return loadImageForTarget(imageUrl, previewImage, previewEmpty);
}

function renderPreviewOverlay(pageData) {
  if (!pageData || !previewImage || !previewOverlay) return;
  const renderBoxes = () => {
    const imgWidth = pageData.image_width || previewImage.naturalWidth;
    const imgHeight = pageData.image_height || previewImage.naturalHeight;
    if (!imgWidth || !imgHeight) return;
    positionOverlayToImage(previewImage, previewOverlay);
    previewOverlay.innerHTML = "";
    const focus =
      focusedFinding && focusedFinding.page === pageData.page_number
        ? focusedFinding
        : null;
    const renderBox = (boxData, categoryId, focusMode) => {
      const left = (boxData.x / imgWidth) * 100;
      const top = (boxData.y / imgHeight) * 100;
      const width = (boxData.w / imgWidth) * 100;
      const height = (boxData.h / imgHeight) * 100;
      const color = CATEGORY_COLORS[categoryId] || "#f97316";
      const box = document.createElement("div");
      box.className = focusMode ? "box focus" : "box";
      box.style.left = `${left}%`;
      box.style.top = `${top}%`;
      box.style.width = `${width}%`;
      box.style.height = `${height}%`;
      box.style.borderColor = color;
      box.style.backgroundColor = `${color}22`;
      previewOverlay.appendChild(box);
    };

    if (focus) {
      renderBox(focus.box, focus.categoryId || focus.category_id, true);
      return;
    }

    (pageData.regions || []).forEach((region) => {
      renderBox(region, region.category_id, false);
    });
  };
  previewImage.onload = () => requestAnimationFrame(renderBoxes);
  if (previewImage.complete) {
    requestAnimationFrame(renderBoxes);
  }
}

function renderDashboardPreview(pageData) {
  if (!previewCard || !previewOverlay || !previewImage || !pageData) return;
  previewCard.classList.remove("hidden");
  pendingPreviewPage = pageData;
  previewLoaded = false;
  if (previewEmpty) {
    previewEmpty.textContent = "Preview ready. Click show to view.";
    previewEmpty.style.display = "block";
  }
  if (previewOverlay) previewOverlay.innerHTML = "";
  if (previewImage) {
    previewImage.removeAttribute("src");
    previewImage.style.display = "none";
  }
  setPreviewVisible(false);
}

async function pollJob(jobId) {
  setStatus("Queued", 0.1);
  if (statusFoot) statusFoot.textContent = "Job queued";

  const interval = setInterval(async () => {
    const res = await fetch(`${API_BASE_URL}/jobs/${jobId}`);
    if (!res.ok) return;
    const data = await res.json();
    setStatus(data.status, data.progress || 0.2);
    if (statusFoot) statusFoot.textContent = data.status;

    if (data.status === "queued" || data.status === "processing") {
      setScanningState(true);
    }

    if (data.status === "complete") {
      clearInterval(interval);
      setStatus("Complete", 1);
      setScanningState(false);
      await loadResults(jobId);
    }
    if (data.status === "error") {
      clearInterval(interval);
      setScanningState(false);
      if (statusFoot) statusFoot.textContent = data.message || "Pipeline error";
    }
  }, 2000);
}

async function loadResults(jobId) {
  if (!jobId) return;
  activeJobId = jobId;

  const payload = await fetchJobResults(jobId);
  if (!payload) {
    if (statusFoot) statusFoot.textContent = "Failed to load results";
    showToast("No results found for this job", "error");
    return;
  }

  resultsPayload = payload;
  const hasPages = resultsPayload.pages && resultsPayload.pages.length;
  if (!hasPages) {
    if (statusFoot) statusFoot.textContent = "Summary ready";
    resetPreviewState("No rendered preview for this job.");
  }

  const totalInference = getInferenceSeconds(resultsPayload);
  const avgInference =
    resultsPayload.avg_inference_seconds ||
    (totalInference && resultsPayload.pages?.length
      ? totalInference / resultsPayload.pages.length
      : null);
  setInferenceTime(totalInference, avgInference);

  setScanningState(false);
  resultCache.set(jobId, resultsPayload);

  localStorage.setItem(LAST_JOB_KEY, jobId);
  focusedFinding = null;
  selectedFinding = null;
  updateModalButtons();
  updateFocusButtons();
  setFindingsMeta(resultsPayload);
  renderFindings(resultsPayload);
  updateFindingsExport(resultsPayload);
  updateTamperedFlag(getCategorySummary(resultsPayload));
  if (hasPages) {
    renderDashboardPreview(resultsPayload.pages[0]);
  }

  if (statusFoot) statusFoot.textContent = "Complete";
}

async function fetchJobResults(jobId) {
  if (!jobId) return null;
  if (resultCache.has(jobId)) return resultCache.get(jobId);
  const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/results`);
  if (!res.ok) return null;
  const payload = await res.json();
  payload.job_id = payload.job_id || jobId;
  resultCache.set(jobId, payload);
  return payload;
}

async function startAnalysis() {
  if (!selectedFile) {
    if (uploadStatus) uploadStatus.textContent = "Please select a file";
    return;
  }
  if (selectedFile.size > APP_OPTIONS.maxUploadBytes) {
    if (uploadStatus) uploadStatus.textContent = "File exceeds 25 MB limit";
    return;
  }

  resetPreviewState("No rendered preview yet.");

  setInferenceTime(null, null);

  if (uploadStatus) uploadStatus.textContent = "Uploading...";
  if (statusFoot) statusFoot.textContent = "Uploading file...";
  setStatus("Uploading", 0.02);

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("ocr_enabled", "true");

  let data;
  try {
    data = await uploadWithProgress(formData, (progress) => {
      if (progress === null) {
        setStatus("Uploading", 0.1);
        return;
      }
      const percent = Math.round(progress * 100);
      const scaled = Math.min(0.85, Math.max(0.05, progress * 0.85));
      setStatus(`Uploading ${percent}%`, scaled);
    });
  } catch (err) {
    if (uploadStatus) uploadStatus.textContent = "Upload failed";
    if (statusFoot) statusFoot.textContent = err?.message || "Upload failed";
    setStatus("Upload failed", 0);
    return;
  }
  activeJobId = data.job_id;
  if (uploadStatus) uploadStatus.textContent = "Processing started";
  setStatus("Queued", 0.9);
  localStorage.setItem(LAST_JOB_KEY, activeJobId);
  setScanningState(true);
  pollJob(activeJobId);
}

function initDashboard() {
  if (!uploadInput || !uploadDrop) return;

  uploadInput.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) selectFile(file);
  });

  uploadDrop.addEventListener("dragover", (event) => {
    event.preventDefault();
    uploadDrop.classList.add("dragover");
  });

  uploadDrop.addEventListener("dragleave", () => uploadDrop.classList.remove("dragover"));

  uploadDrop.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadDrop.classList.remove("dragover");
    const file = event.dataTransfer.files?.[0];
    if (file) selectFile(file);
  });

  setPreviewVisible(false);
  togglePreviewBtn?.addEventListener("click", () => {
    if (!previewViewer) return;
    setPreviewVisible(previewViewer.classList.contains("hidden"));
  });

  startBtn?.addEventListener("click", () => startAnalysis());

  setStatus("Idle", 0);
}

function initPage() {
  if (pageInitialized) return;
  pageInitialized = true;
  if (page === "dashboard") initDashboard();
}

function initCommon() {
  updateBrand();
  setActiveNav();
  initMobileMenu();

  copyFindingsBtn?.addEventListener("click", async () => {
    if (!findingsTextCache) return;
    try {
      await navigator.clipboard.writeText(findingsTextCache);
      showToast("Findings copied", "info");
    } catch (err) {
      showToast("Copy failed", "error");
    }
  });

  downloadFindingsBtn?.addEventListener("click", () => {
    if (!findingsTextCache) return;
    const blob = new Blob([findingsTextCache], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = findingsFileNameCache || "findings.txt";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  });

  findingsList?.addEventListener("click", (event) => {
    const target = event.target.closest(".finding-link");
    if (!target) return;
    const page = parseInt(target.dataset.page || "0", 10);
    const x = parseInt(target.dataset.x || "0", 10);
    const y = parseInt(target.dataset.y || "0", 10);
    const w = parseInt(target.dataset.w || "0", 10);
    const h = parseInt(target.dataset.h || "0", 10);
    const categoryId = target.dataset.category || "";
    if (!page || !w || !h) return;
    selectedFinding = { page, categoryId, box: { x, y, w, h } };
    updateModalButtons();
    openCropModal(page, { x, y, w, h });
  });

  cropCloseBtn?.addEventListener("click", closeCropModal);
  cropModal?.addEventListener("click", (event) => {
    if (event.target === cropModal) closeCropModal();
  });

  showAllOverlaysBtn?.addEventListener("click", () => {
    if (!focusedFinding) return;
    clearFocusedFinding();
    showToast("Showing all overlays", "info");
  });

  toggleFindingsBtn?.addEventListener("click", () => {
    if (!findingsAll.length) return;
    findingsShowAll = !findingsShowAll;
    const list = findingsShowAll ? findingsAll : findingsAll.slice(0, DEFAULT_FINDINGS_LIMIT);
    renderFindingsList(list);
    updateFindingsToggle();
  });

  showInDocumentBtn?.addEventListener("click", () => {
    if (!selectedFinding) return;
    setFocusedFinding(selectedFinding);
    closeCropModal();
    showToast("Showing selected area in document", "info");
  });
}

initCommon();
initPage();
