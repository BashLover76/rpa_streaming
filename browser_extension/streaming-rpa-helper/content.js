(() => {
  const TEXT_HINTS = [
    "Continuer",
    "Continue",
    "Reprendre",
    "Up Next",
    "À suivre",
    "History",
    "Historique"
  ];

  function textOf(node) {
    return (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
  }

  function cssPath(element) {
    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
      let selector = current.nodeName.toLowerCase();
      if (current.id) {
        selector += `#${CSS.escape(current.id)}`;
        parts.unshift(selector);
        break;
      }
      const testId = current.getAttribute("data-testid") || current.getAttribute("data-test");
      if (testId) {
        selector += `[data-testid="${CSS.escape(testId)}"]`;
        parts.unshift(selector);
        break;
      }
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((child) => child.nodeName === current.nodeName);
        if (siblings.length > 1) selector += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(selector);
      current = parent;
    }
    return parts.join(" > ");
  }

  function collectCandidates() {
    const candidates = [];
    const nodes = document.querySelectorAll("main, section, article, li, a, div");
    for (const node of nodes) {
      const text = textOf(node);
      if (!text || text.length > 500) continue;
      const hasHint = TEXT_HINTS.some((hint) => text.toLowerCase().includes(hint.toLowerCase()));
      const href = node.href || node.querySelector?.("a[href]")?.href || "";
      if (!hasHint && !/episode|series|show|watch|video/i.test(href)) continue;
      candidates.push({
        selector: cssPath(node),
        tag: node.tagName.toLowerCase(),
        href,
        text: text.slice(0, 300)
      });
      if (candidates.length >= 200) break;
    }
    return candidates;
  }

  window.__STREAMING_RPA_HELPER__ = {
    collectCandidates,
    version: "0.1.0"
  };
})();
