// Replace these with your real public URLs when you upload the website.
// Best simple path:
// - repo: your GitHub project
// - releases: your GitHub Releases page
// - downloadInstaller: direct public URL to your installer .exe
// - downloadPortable: direct public URL to your portable .zip
// - issues: your bug report page
// - donate: your support page
const PUBLIC_LINKS = {
  repo: "https://github.com/krutus05/3D-Visual-Mesh",
  releases: "https://github.com/krutus05/3D-Visual-Mesh/releases",
  downloadInstaller: "https://github.com/krutus05/3D-Visual-Mesh/releases/download/v0.1.0/3DVisualMeshSetup_0.1.0.exe",
  downloadPortable: "https://github.com/krutus05/3D-Visual-Mesh/releases/download/v0.1.0/3DVisual.Mesh.Share.BETA.Version.0.1.0.zip",
  issues: "https://github.com/krutus05/3D-Visual-Mesh/issues",
  donate: "https://ko-fi.com/3dvisualmesh",
};

const LINKS = PUBLIC_LINKS;

const RELEASES = [
  {
    version: "0.1.0",
    status: "Current Beta",
    title: "Installer + portable package",
    text: "First clean share build with installer flow, Blender add-on bundle, release packaging, and Windows bootstrap paths.",
  },
  {
    version: "0.0.2",
    status: "Previous Internal",
    title: "UI + workflow groundwork",
    text: "Early build used for native app layout, preview experiments, plugin hooks, and mesh cleanup passes.",
  },
  {
    version: "0.0.1",
    status: "Prototype",
    title: "Concept validation",
    text: "Private prototype used to test AMD-first local image-to-mesh workflow ideas on Windows.",
  },
];

const PLUGINS = [
  {
    name: "Blender Cleanup Tools",
    author: "Yanis",
    status: "approved",
    category: "blender",
    tags: ["blender", "cleanup", "retopo"],
    version: "0.1.0",
    summary: "Open the result faster in Blender, inspect loose pieces, and start cleanup without hunting through files.",
  },
  {
    name: "Triangle Budget Advisor",
    author: "Core Team",
    status: "approved",
    category: "workflow",
    tags: ["workflow", "triangles", "game-ready"],
    version: "0.1.0",
    summary: "Shows practical triangle targets for props, hero assets, stylized builds, and dense showcase meshes.",
  },
  {
    name: "Mesh Export Pack",
    author: "Community Example",
    status: "approved",
    category: "export",
    tags: ["export", "glb", "fbx"],
    version: "0.0.4",
    summary: "Starter export helpers for teams that want cleaner naming and repeatable handoff steps after generation.",
  },
  {
    name: "Advanced Cleanup Pass",
    author: "Pending Creator",
    status: "pending",
    category: "cleanup",
    tags: ["cleanup", "mesh", "artifacts"],
    version: "0.0.1",
    summary: "Example pending plugin to show how user uploads stay hidden until approved by the owner.",
  },
];

function wireLinks() {
  for (const node of document.querySelectorAll("[data-link]")) {
    const key = node.getAttribute("data-link");
    const href = LINKS[key];
    if (!href) {
      continue;
    }
    node.setAttribute("href", href);
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noreferrer");
  }
}

function renderReleases() {
  const host = document.querySelector("#release-list");
  if (!host) {
    return;
  }

  host.innerHTML = RELEASES.map((release) => `
    <article class="shell-card release-card">
      <div class="card-topline">
        <span class="mini-pill">${release.status}</span>
        <span class="version-tag">v${release.version}</span>
      </div>
      <h3>${release.title}</h3>
      <p>${release.text}</p>
    </article>
  `).join("");
}

function pluginMatches(plugin, query, filter) {
  const loweredQuery = query.trim().toLowerCase();
  const haystack = [
    plugin.name,
    plugin.author,
    plugin.category,
    plugin.status,
    ...plugin.tags,
    plugin.summary,
  ].join(" ").toLowerCase();

  const queryOk = !loweredQuery || haystack.includes(loweredQuery);
  const filterOk =
    filter === "all" ||
    plugin.status === filter ||
    plugin.category === filter ||
    plugin.tags.includes(filter);

  return queryOk && filterOk;
}

function renderPlugins() {
  const host = document.querySelector("#plugin-list");
  const search = document.querySelector("#plugin-search");
  const filter = document.querySelector("#plugin-filter");
  if (!host || !search || !filter) {
    return;
  }

  const visiblePlugins = PLUGINS.filter((plugin) =>
    pluginMatches(plugin, search.value, filter.value)
  );

  if (!visiblePlugins.length) {
    host.innerHTML = `
      <article class="shell-card empty-card">
        <h3>No plugins match that filter.</h3>
        <p>Try a broader word or switch the filter back to All.</p>
      </article>
    `;
    return;
  }

  host.innerHTML = visiblePlugins.map((plugin) => `
    <article class="shell-card plugin-card ${plugin.status}">
      <div class="card-topline">
        <span class="mini-pill">${plugin.status}</span>
        <span class="version-tag">v${plugin.version}</span>
      </div>
      <h3>${plugin.name}</h3>
      <p>${plugin.summary}</p>
      <div class="plugin-meta">
        <span>By ${plugin.author}</span>
        <span>${plugin.category}</span>
      </div>
      <div class="tag-row">
        ${plugin.tags.map((tag) => `<span class="tag">${tag}</span>`).join("")}
      </div>
    </article>
  `).join("");
}

function wirePluginFilters() {
  const search = document.querySelector("#plugin-search");
  const filter = document.querySelector("#plugin-filter");
  if (!search || !filter) {
    return;
  }

  search.addEventListener("input", renderPlugins);
  filter.addEventListener("change", renderPlugins);
}

function openDonationModal(downloadKey) {
  const modal = document.querySelector("#donation-modal");
  const continueLink = document.querySelector("#continue-download-link");
  if (!modal || !continueLink) {
    return;
  }

  continueLink.setAttribute("href", LINKS[downloadKey] || LINKS.downloadInstaller);
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
      const key = node.getAttribute("data-link");
      openDonationModal(key);
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
renderReleases();
renderPlugins();
wirePluginFilters();
wireDonationModal();
