/**
 * Minimal vanilla-JS frontend for the Coverage Q&A Service.
 * No build step - served directly by FastAPI as a static file (see app/main.py).
 */

const state = {
  orgId: null,
  lastInteractionId: null,
};

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body = null;
  try {
    body = await response.json();
  } catch (err) {
    body = null;
  }
  if (!response.ok) {
    const message = (body && body.detail) || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body;
}

function formatDate(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  return date.toLocaleString();
}

// --------------------------------------------------------------------------
// Organizations
// --------------------------------------------------------------------------

async function loadOrganizations() {
  const orgs = await api("/organizations");
  const select = el("org-select");
  select.innerHTML = "";

  if (orgs.length === 0) {
    el("no-org-message").hidden = false;
    el("app-main").hidden = true;
    return;
  }

  el("no-org-message").hidden = true;
  el("app-main").hidden = false;

  for (const org of orgs) {
    const option = document.createElement("option");
    option.value = org.id;
    option.textContent = org.name;
    select.appendChild(option);
  }

  state.orgId = select.value;
  select.addEventListener("change", () => {
    state.orgId = select.value;
    onOrgChanged();
  });

  await onOrgChanged();
}

async function onOrgChanged() {
  resetAnswerArea();
  await Promise.all([loadDocuments(), loadAnalytics()]);
}

// --------------------------------------------------------------------------
// Documents
// --------------------------------------------------------------------------

async function loadDocuments() {
  const container = el("documents-list");
  container.innerHTML = "<p class=\"empty-state\">Loading...</p>";

  try {
    const data = await api(`/documents?org_id=${encodeURIComponent(state.orgId)}`);
    renderDocuments(data.documents);
  } catch (err) {
    container.innerHTML = `<p class="empty-state">Failed to load documents: ${err.message}</p>`;
  }
}

function renderDocuments(documents) {
  const container = el("documents-list");
  container.innerHTML = "";

  if (documents.length === 0) {
    container.innerHTML = '<p class="empty-state">No documents yet - upload a coverage PDF to get started.</p>';
    return;
  }

  for (const doc of documents) {
    const row = document.createElement("div");
    row.className = "document-row";

    const info = document.createElement("div");
    info.className = "document-info";

    const filename = document.createElement("span");
    filename.className = "document-filename";
    filename.textContent = doc.filename;

    const meta = document.createElement("span");
    meta.className = "document-meta";
    const parts = [];
    if (doc.page_count) parts.push(`${doc.page_count} pages`);
    if (doc.chunk_count) parts.push(`${doc.chunk_count} chunks`);
    parts.push(formatDate(doc.uploaded_at));
    if (doc.status === "failed" && doc.failure_reason) {
      parts.push(doc.failure_reason);
    }
    meta.textContent = parts.join(" \u2022 ");

    info.appendChild(filename);
    info.appendChild(meta);

    const statusBadge = document.createElement("span");
    statusBadge.className = `doc-status ${doc.status}`;
    statusBadge.textContent = doc.status;

    const deleteButton = document.createElement("button");
    deleteButton.className = "icon-button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => deleteDocument(doc.id, doc.filename));

    row.appendChild(info);
    row.appendChild(statusBadge);
    row.appendChild(deleteButton);
    container.appendChild(row);
  }
}

async function deleteDocument(documentId, filename) {
  if (!confirm(`Delete "${filename}"? This removes it and its indexed content.`)) {
    return;
  }
  try {
    await api(`/documents/${documentId}?org_id=${encodeURIComponent(state.orgId)}`, { method: "DELETE" });
    await Promise.all([loadDocuments(), loadAnalytics()]);
  } catch (err) {
    alert(`Failed to delete document: ${err.message}`);
  }
}

async function handleUploadSubmit(event) {
  event.preventDefault();
  const fileInput = el("file-input");
  const file = fileInput.files[0];
  const statusLine = el("upload-status");
  const button = el("upload-button");

  if (!file) return;

  const formData = new FormData();
  formData.append("org_id", state.orgId);
  formData.append("file", file);

  button.disabled = true;
  statusLine.className = "status-line";
  statusLine.textContent = `Uploading and processing "${file.name}"...`;

  try {
    const document_ = await api("/documents", { method: "POST", body: formData });
    if (document_.status === "ready") {
      statusLine.className = "status-line success";
      statusLine.textContent = `"${document_.filename}" is ready (${document_.chunk_count} chunks indexed).`;
    } else {
      statusLine.className = "status-line error";
      statusLine.textContent = `"${document_.filename}" failed: ${document_.failure_reason || "unknown error"}`;
    }
    fileInput.value = "";
    await loadDocuments();
  } catch (err) {
    statusLine.className = "status-line error";
    statusLine.textContent = `Upload failed: ${err.message}`;
  } finally {
    button.disabled = false;
  }
}

// --------------------------------------------------------------------------
// Query
// --------------------------------------------------------------------------

function resetAnswerArea() {
  el("answer-area").hidden = true;
  el("feedback-status").textContent = "";
  el("feedback-up").classList.remove("selected");
  el("feedback-down").classList.remove("selected");
  state.lastInteractionId = null;
}

async function handleQuerySubmit(event) {
  event.preventDefault();
  const questionInput = el("question-input");
  const question = questionInput.value.trim();
  if (!question) return;

  const button = el("ask-button");
  button.disabled = true;
  button.textContent = "Thinking...";

  try {
    const result = await api("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org_id: state.orgId, question }),
    });
    renderAnswer(result);
    await loadAnalytics();
  } catch (err) {
    alert(`Query failed: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Ask";
  }
}

function renderAnswer(result) {
  state.lastInteractionId = result.interaction_id;

  el("answer-area").hidden = false;
  el("feedback-status").textContent = "";
  el("feedback-up").classList.remove("selected");
  el("feedback-down").classList.remove("selected");

  const confidenceBadge = el("confidence-badge");
  confidenceBadge.textContent = `Confidence: ${result.confidence}`;

  const reviewBadge = el("review-badge");
  reviewBadge.hidden = !result.needs_human_review;

  el("latency-note").textContent = `${result.latency_ms} ms`;
  el("answer-text").textContent = result.answer;

  const citationsContainer = el("citations");
  citationsContainer.innerHTML = "";
  if (result.citations.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No citations - this answer isn't grounded in a specific document.";
    citationsContainer.appendChild(empty);
  } else {
    for (const citation of result.citations) {
      const chip = document.createElement("div");
      chip.className = "citation-chip";
      const pageText = citation.page ? `, page ${citation.page}` : "";
      const sectionText = citation.section_heading ? ` \u2014 ${citation.section_heading}` : "";
      chip.innerHTML = `<strong>${citation.filename}</strong>${pageText}${sectionText}`;
      citationsContainer.appendChild(chip);
    }
  }
}

async function submitFeedback(vote) {
  if (!state.lastInteractionId) return;
  const statusLine = el("feedback-status");
  try {
    await api(`/interactions/${state.lastInteractionId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vote }),
    });
    el("feedback-up").classList.toggle("selected", vote === "up");
    el("feedback-down").classList.toggle("selected", vote === "down");
    statusLine.textContent = "Thanks for the feedback!";
  } catch (err) {
    statusLine.textContent = `Failed to record feedback: ${err.message}`;
  }
}

// --------------------------------------------------------------------------
// Analytics
// --------------------------------------------------------------------------

async function loadAnalytics() {
  try {
    const data = await api(`/analytics?org_id=${encodeURIComponent(state.orgId)}`);
    renderAnalytics(data);
  } catch (err) {
    console.error("Failed to load analytics", err);
  }
}

function renderAnalytics(data) {
  const topDocsBody = document.querySelector("#top-documents-table tbody");
  topDocsBody.innerHTML = "";
  if (data.top_documents.length === 0) {
    topDocsBody.innerHTML = '<tr><td colspan="2" class="empty-state">No queries yet</td></tr>';
  } else {
    for (const row of data.top_documents) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.filename}</td><td>${row.query_count}</td>`;
      topDocsBody.appendChild(tr);
    }
  }

  const topQuestionsBody = document.querySelector("#top-questions-table tbody");
  topQuestionsBody.innerHTML = "";
  if (data.top_questions.length === 0) {
    topQuestionsBody.innerHTML =
      '<tr><td colspan="2" class="empty-state">No question has been asked more than once yet</td></tr>';
  } else {
    for (const row of data.top_questions) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.question}</td><td>${row.count}</td>`;
      topQuestionsBody.appendChild(tr);
    }
  }

  const weeklyBody = document.querySelector("#weekly-usage-table tbody");
  weeklyBody.innerHTML = "";
  if (data.weekly_document_usage.length === 0) {
    weeklyBody.innerHTML = '<tr><td colspan="3" class="empty-state">No queries yet</td></tr>';
  } else {
    for (const row of data.weekly_document_usage) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.week_start}</td><td>${row.filename}</td><td>${row.query_count}</td>`;
      weeklyBody.appendChild(tr);
    }
  }
}

// --------------------------------------------------------------------------
// Wire up
// --------------------------------------------------------------------------

el("upload-form").addEventListener("submit", handleUploadSubmit);
el("query-form").addEventListener("submit", handleQuerySubmit);
el("feedback-up").addEventListener("click", () => submitFeedback("up"));
el("feedback-down").addEventListener("click", () => submitFeedback("down"));
el("refresh-analytics").addEventListener("click", loadAnalytics);

loadOrganizations().catch((err) => {
  el("no-org-message").hidden = false;
  el("no-org-message").textContent = `Failed to load organizations: ${err.message}`;
});
