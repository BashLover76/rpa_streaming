chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const authHeader = (details.requestHeaders || []).find(
      (header) => header.name.toLowerCase() === "authorization"
    );
    if (!authHeader || !authHeader.value || !authHeader.value.startsWith("Basic ")) {
      return;
    }

    chrome.storage.local.set({
      crunchyrollAuthorization: authHeader.value,
      capturedAt: new Date().toISOString(),
      sourceUrl: details.url
    });
  },
  { urls: ["https://beta-api.crunchyroll.com/auth/v1/token*"] },
  ["requestHeaders", "extraHeaders"]
);
