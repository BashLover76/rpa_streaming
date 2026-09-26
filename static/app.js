(() => {
  const input = document.querySelector("#series-search, #movie-search");
  const datalist = input ? document.querySelector(`#${input.getAttribute("list")}`) : null;
  if (!input || !datalist) return;
  const suggestUrl = input.dataset.suggestUrl || "/api/series/suggest";

  let requestTimer;
  input.addEventListener("input", () => {
    window.clearTimeout(requestTimer);
    const query = input.value.trim();
    if (query.length < 2) {
      datalist.replaceChildren();
      return;
    }

    requestTimer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `${suggestUrl}?q=${encodeURIComponent(query)}`
        );
        if (!response.ok) return;
        const suggestions = await response.json();
        datalist.replaceChildren(
          ...suggestions.map(({ titre, platform }) => {
            const option = document.createElement("option");
            option.value = titre;
            option.label = platform;
            return option;
          })
        );
      } catch (_error) {
        datalist.replaceChildren();
      }
    }, 180);
  });
})();

(() => {
  const layout = document.querySelector(".detail-layout");
  if (!layout) return;
  const columns = layout.querySelectorAll(":scope > .detail-column");
  if (columns.length !== 2) return;
  const articles = [...layout.querySelectorAll("article")];
  const articleNamed = (name) =>
    articles.find((article) => article.querySelector("summary")?.textContent.includes(name));
  const history = articleNamed("Historique récent");
  const local = articleNamed("Détails locaux");
  const upcoming = articleNamed("Prochaines sorties");
  const calendar = articleNamed("Calendrier complet connu");
  if (history && upcoming && local && calendar) {
    const sectionFor = (article) => {
      const section = document.createElement("section");
      section.className = "detail-grid";
      section.append(article);
      return section;
    };
    columns[0].replaceChildren(sectionFor(history), sectionFor(upcoming));
    columns[1].replaceChildren(sectionFor(local), sectionFor(calendar));
  }
})();

(() => {
  const form = document.querySelector(".calendar-filters");
  if (!form) return;
  const month = form.querySelector("#calendar-month");
  const search = form.querySelector("#calendar-search");
  let timer;
  const refresh = async () => {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month.value)) {
      month.setCustomValidity("Saisissez un mois au format AAAA-MM.");
      month.reportValidity();
      return;
    }
    month.setCustomValidity("");
    const params = new URLSearchParams(new FormData(form));
    form.querySelectorAll(".platform-filter.is-selected").forEach((button) => {
      params.append("platform", button.dataset.platform);
    });
    const response = await fetch(`/calendar?${params}`);
    if (!response.ok) return;
    const documentText = await response.text();
    document.open();
    document.write(documentText);
    document.close();
    window.history.replaceState({}, "", `/calendar?${params}`);
  };
  month.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, 350);
  });
  search.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, 350);
  });
  form.querySelectorAll("select").forEach((control) => {
    control.addEventListener("change", refresh);
  });
  form.querySelectorAll(".platform-filter").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = button.getAttribute("aria-pressed") === "true";
      button.setAttribute("aria-pressed", String(!selected));
      button.classList.toggle("is-selected", !selected);
      refresh();
    });
  });
})();

(() => {
  const live = document.querySelector(".admin-rpa-live");
  if (!live) return;
  const stateUrl = live.dataset.rpaStateUrl;
  const currentNode = document.querySelector("[data-rpa-current]");
  const queueNode = document.querySelector("[data-rpa-queue]");
  const logsNode = document.querySelector("[data-rpa-logs]");
  const refreshNode = document.querySelector("[data-rpa-refresh]");
  if (!stateUrl || !currentNode || !queueNode || !logsNode) return;

  const text = (value) => value == null || value === "" ? "?" : String(value);
  const mark = (platform, label) =>
    `<b class="platform-mark platform-${escapeHtml(platform || "unknown")}">${escapeHtml(label || platform || "?")}</b>`;

  const renderCurrent = (current) => {
    if (!current) {
      currentNode.innerHTML = `<p class="empty">Aucune ingestion RPA en cours.</p>`;
      return;
    }
    currentNode.innerHTML = `
      <article class="admin-rpa-current" data-current-log="${escapeHtml(current.log_name || "")}">
        <div>
          <span class="platform-label">${mark(current.platform, current.label)}</span>
          <p class="muted">Démarré : ${escapeHtml(text(current.started_at))} · Log : ${escapeHtml(text(current.log_name))}</p>
        </div>
        <pre>${escapeHtml(current.log_tail || "En attente des premières lignes de log...")}</pre>
      </article>
    `;
    const pre = currentNode.querySelector("pre");
    if (pre) pre.scrollTop = pre.scrollHeight;
  };

  const renderQueue = (queue) => {
    if (!queue || queue.length === 0) {
      queueNode.innerHTML = `<p class="empty">Aucun job en attente.</p>`;
      return;
    }
    queueNode.innerHTML = queue.map((job) => `
      <article class="admin-row">
        <div>
          <span class="platform-label">${mark(job.platform, job.label)}</span>
          <span>Demandé : ${escapeHtml(text(job.created_at))}</span>
        </div>
        <div class="row-meta"><span>${escapeHtml(text(job.log_name))}</span></div>
      </article>
    `).join("");
  };

  const renderLogs = (logs) => {
    if (!logs || logs.length === 0) {
      logsNode.innerHTML = `<p class="empty">Aucun log RPA admin trouvé.</p>`;
      return;
    }
    logsNode.innerHTML = logs.map((log) => `
      <article>
        <h3>${escapeHtml(text(log.name))}</h3>
        <p class="muted">Dernière mise à jour : ${escapeHtml(text(log.updated_at))}</p>
        <pre>${escapeHtml(log.content || "")}</pre>
      </article>
    `).join("");
  };

  const refresh = async () => {
    try {
      const response = await fetch(stateUrl, { headers: { "Accept": "application/json" } });
      if (!response.ok) return;
      const state = await response.json();
      renderCurrent(state.current);
      renderQueue(state.queue);
      renderLogs(state.recent_logs);
      if (refreshNode) {
        refreshNode.textContent = `Rafraîchi à ${new Date().toLocaleTimeString()} · mise à jour toutes les 5s`;
      }
    } catch (_error) {
      if (refreshNode) refreshNode.textContent = "Rafraîchissement automatique indisponible.";
    }
  };

  refresh();
  window.setInterval(refresh, 5000);

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }
})();
