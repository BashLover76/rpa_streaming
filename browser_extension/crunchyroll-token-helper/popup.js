const status = document.getElementById("status");
const token = document.getElementById("token");
const copy = document.getElementById("copy");

chrome.storage.local.get(["crunchyrollAuthorization", "capturedAt"], (data) => {
  if (!data.crunchyrollAuthorization) {
    status.textContent = "Connecte-toi à Crunchyroll puis relance une page du site.";
    token.value = "";
    return;
  }

  status.textContent = `Capture locale: ${data.capturedAt || "date inconnue"}`;
  token.value = `CRUNCHYROLL_AUTHORIZATION=${data.crunchyrollAuthorization}`;
});

copy.addEventListener("click", async () => {
  await navigator.clipboard.writeText(token.value);
  status.textContent = "Copie dans le presse-papiers.";
});
