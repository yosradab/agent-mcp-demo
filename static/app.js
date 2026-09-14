/* Frontend Support Desk - parle a l'API FastAPI via fetch. */
"use strict";

const state = { status: "", priority: "", search: "" };

const $ = (id) => document.getElementById(id);

const STATUS_LABEL = { open: "Open", in_progress: "In progress", closed: "Closed" };
const PRIORITY_LABEL = { low: "Low", medium: "Medium", high: "High" };

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-FR") + " " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function badge(klass, label) {
  return `<span class="badge ${escapeHtml(klass)}">${escapeHtml(label)}</span>`;
}

/* ---------- fallback d'erreur HTTP propre ---------- */
async function api(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = `Erreur HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* corps non-JSON */ }
    throw new Error(detail);
  }
  return resp.json();
}

function toast(message, type = "success") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${type}`;
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => { el.className = "toast hidden"; }, 3000);
}

/* ---------- stats ---------- */
async function loadStats() {
  try {
    const s = await api("/api/tickets/stats/summary");
    $("stat-total").textContent = s.total ?? 0;
    $("stat-open").textContent = s.by_status?.open ?? 0;
    $("stat-inprogress").textContent = s.by_status?.in_progress ?? 0;
    $("stat-closed").textContent = s.by_status?.closed ?? 0;
    $("stat-high").textContent = s.by_priority?.high ?? 0;
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ---------- liste ---------- */
async function loadTickets() {
  const params = new URLSearchParams();
  if (state.status) params.set("status", state.status);
  if (state.priority) params.set("priority", state.priority);
  params.set("limit", "100");

  const tbody = $("tbody");
  try {
    let tickets = await api(`/api/tickets?${params.toString()}`);
    const q = state.search.trim().toLowerCase();
    if (q) {
      tickets = tickets.filter((t) =>
        `${t.id} ${t.title} ${t.assignee}`.toLowerCase().includes(q)
      );
    }

    if (!tickets.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">Aucun ticket ne correspond.</td></tr>`;
      return;
    }

    tbody.innerHTML = tickets.map((t) => `
      <tr>
        <td class="cell-nowrap"><strong>#${t.id}</strong></td>
        <td>
          <div>${escapeHtml(t.title)}</div>
          ${t.description ? `<div class="muted" style="font-size:.8rem">${escapeHtml(t.description.slice(0, 80))}</div>` : ""}
        </td>
        <td>${badge(t.status, STATUS_LABEL[t.status] || t.status)}</td>
        <td>${badge(t.priority, PRIORITY_LABEL[t.priority] || t.priority)}</td>
        <td>${escapeHtml(t.assignee || "-")}</td>
        <td class="cell-nowrap">${formatDate(t.created_at)}</td>
        <td class="cell-nowrap">
          <div class="row-actions">
            <button class="btn-ghost" data-action="edit" data-id="${t.id}" title="Modifier">Modifier</button>
            <button class="btn-ghost btn-danger" data-action="delete" data-id="${t.id}" title="Supprimer">Supprimer</button>
          </div>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted">Impossible de charger les tickets : ${escapeHtml(err.message)}</td></tr>`;
  }
}

function refreshAll() {
  loadStats();
  loadTickets();
}

/* ---------- modal creation / edition ---------- */
function openModal(ticket = null) {
  $("modal-title").textContent = ticket ? `Modifier le ticket #${ticket.id}` : "Nouveau ticket";
  $("field-id").value = ticket ? ticket.id : "";
  $("field-title").value = ticket ? ticket.title : "";
  $("field-description").value = ticket ? (ticket.description || "") : "";
  $("field-priority").value = ticket ? ticket.priority : "medium";
  $("field-status").value = ticket ? ticket.status : "open";
  $("field-assignee").value = ticket ? (ticket.assignee || "") : "";
  $("form-error").classList.add("hidden");
  $("modal").classList.remove("hidden");
  $("field-title").focus();
}

function closeModal() {
  $("modal").classList.add("hidden");
}

async function onFormSubmit(event) {
  event.preventDefault();
  const id = $("field-id").value;
  const errorBox = $("form-error");

  const title = $("field-title").value.trim();
  if (title.length < 3) {
    errorBox.textContent = "Le titre doit contenir au moins 3 caracteres.";
    errorBox.classList.remove("hidden");
    return;
  }

  const payload = {
    title,
    description: $("field-description").value.trim(),
    priority: $("field-priority").value,
    status: $("field-status").value,
    assignee: $("field-assignee").value.trim(),
  };

  try {
    if (id) {
      await api(`/api/tickets/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: payload.status, priority: payload.priority, assignee: payload.assignee }),
      });
      toast("Ticket #" + id + " mis a jour.");
    } else {
      const created = await api("/api/tickets", { method: "POST", body: JSON.stringify(payload) });
      toast("Ticket #" + created.id + " cree.");
    }
    closeModal();
    refreshAll();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  }
}

async function onDelete(id) {
  if (!confirm(`Supprimer le ticket #${id} ?`)) return;
  try {
    await api(`/api/tickets/${id}`, { method: "DELETE" });
    toast(`Ticket #${id} supprime.`);
    refreshAll();
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ---------- evenements ---------- */
$("btn-new").addEventListener("click", () => openModal());
$("modal-close").addEventListener("click", closeModal);
$("btn-cancel").addEventListener("click", closeModal);
$("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

$("ticket-form").addEventListener("submit", onFormSubmit);

$("filter-status").addEventListener("change", (e) => { state.status = e.target.value; loadTickets(); });
$("filter-priority").addEventListener("change", (e) => { state.priority = e.target.value; loadTickets(); });
$("search").addEventListener("input", (e) => { state.search = e.target.value; loadTickets(); });
$("btn-refresh").addEventListener("click", refreshAll);

$("tbody").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const id = Number(btn.dataset.id);
  if (btn.dataset.action === "edit") {
    try {
      const ticket = await api(`/api/tickets/${id}`);
      openModal(ticket);
    } catch (err) {
      toast(err.message, "error");
    }
  } else if (btn.dataset.action === "delete") {
    await onDelete(id);
  }
});

refreshAll();