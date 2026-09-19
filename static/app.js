(() => {
  const input = document.querySelector("#series-search");
  const datalist = document.querySelector("#series-suggestions");
  if (!input || !datalist) return;

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
          `/api/series/suggest?q=${encodeURIComponent(query)}`
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
