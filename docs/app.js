const RELEASE_VERSION_LABEL = "v0.1.1 Beta";

// Fill these once the v0.1.1 Beta assets are uploaded to GitHub Releases.
const DOWNLOAD_NVIDIA_FULL_OFFLINE_URL = "";
const DOWNLOAD_AMD_FULL_OFFLINE_URL = "";
const DOWNLOAD_ONLINE_INSTALLER_URL = "";
const DOWNLOAD_PORTABLE_SOURCE_URL =
  "https://github.com/krutus05/3D-Visual-Mesh/releases/download/v0.1.1/3DVisualMesh_0.1.1_Portable_Source.zip";

const PUBLIC_LINKS = {
  repo: "https://github.com/krutus05/3D-Visual-Mesh",
  releases: "https://github.com/krutus05/3D-Visual-Mesh/releases",
  downloadNvidiaFullOffline: DOWNLOAD_NVIDIA_FULL_OFFLINE_URL,
  downloadAmdFullOffline: DOWNLOAD_AMD_FULL_OFFLINE_URL,
  downloadInstaller: DOWNLOAD_ONLINE_INSTALLER_URL,
  downloadPortable: DOWNLOAD_PORTABLE_SOURCE_URL,
  issues: "https://github.com/krutus05/3D-Visual-Mesh/issues",
  donate: "https://ko-fi.com/3dvisualmesh",
};

const DOWNLOAD_NOTICES = {
  downloadNvidiaFullOffline:
    "The NVIDIA full offline package is still too large for the current GitHub release flow. Use the portable beta package plus the NVIDIA Install Hotfix Pack on the website for now.",
  downloadAmdFullOffline:
    "The AMD full offline package is still too large for the current GitHub release flow. Use the portable beta package plus the AMD Install Hotfix Pack on the website for now.",
  downloadInstaller:
    "The v0.1.1 online installer is not uploaded yet. Use the portable beta package first, and if dependency install fails, apply the matching GPU Install Hotfix Pack from the Downloads section.",
};

function showComingSoonMessage(downloadKey) {
  const message =
    DOWNLOAD_NOTICES[downloadKey] ||
    `${RELEASE_VERSION_LABEL} package is coming soon.`;
  window.alert(message);
}

function wireLinks() {
  for (const node of document.querySelectorAll("[data-link]")) {
    const key = node.getAttribute("data-link");
    const href = PUBLIC_LINKS[key];
    if (!href) {
      if (node.hasAttribute("data-coming-soon")) {
        node.setAttribute("href", "#");
      }
      continue;
    }

    node.setAttribute("href", href);
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noreferrer");
  }
}

function openDonationModal(downloadKey) {
  const targetHref = PUBLIC_LINKS[downloadKey];
  if (!targetHref) {
    showComingSoonMessage(downloadKey);
    return;
  }

  const modal = document.querySelector("#donation-modal");
  const continueLink = document.querySelector("#continue-download-link");
  if (!modal || !continueLink) {
    return;
  }

  continueLink.setAttribute("href", targetHref);
  continueLink.setAttribute("target", "_blank");
  continueLink.setAttribute("rel", "noreferrer");

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function closeDonationModal() {
  const modal = document.querySelector("#donation-modal");
  if (!modal) {
    return;
  }

  modal.classList.remove("is-open");
  modal.setAttribute("aria-hidden", "true");
}

function wireDonationModal() {
  const modal = document.querySelector("#donation-modal");
  if (!modal) {
    return;
  }

  for (const node of document.querySelectorAll("[data-download]")) {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      openDonationModal(node.getAttribute("data-link"));
    });
  }

  for (const node of document.querySelectorAll("[data-coming-soon]")) {
    node.addEventListener("click", (event) => {
      const key = node.getAttribute("data-link");
      if (PUBLIC_LINKS[key]) {
        return;
      }
      event.preventDefault();
      showComingSoonMessage(key);
    });
  }

  for (const node of document.querySelectorAll("[data-close-modal]")) {
    node.addEventListener("click", () => {
      closeDonationModal();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDonationModal();
    }
  });
}

wireLinks();
wireDonationModal();
