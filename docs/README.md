# 3DVisual Mesh Hub Website

This folder now acts as a static MVP prototype for the future `3DVisual Mesh Hub`.

## Best choice

Use this version as the public concept site for:

- official app downloads
- plugin discovery
- upload/review workflow explanation
- backend structure planning
- simple install guidance for AMD and NVIDIA users

## Why

- it gives you a clean public direction now
- it keeps official releases separate from community plugins
- it makes the future account/upload site easier to build without guessing

## Support

- support is optional
- donation page: `https://ko-fi.com/3dvisualmesh`
- the website already includes a support button and an optional donation popup before download

## Included files

- `index.html`
  marketplace-style landing page for the hub idea
- `app.js`
  starter data and plugin search/filter behavior
- `styles.css`
  dark visual style for the hub prototype
- `MVP_STRUCTURE.md`
  exact feature and page plan
- `supabase_schema.sql`
  starter database schema for accounts, official releases, plugins, versions, and review state

## Best real stack later

- `Next.js` for the app/site
- `Supabase` for auth, database, and storage
- `Cloudflare R2` later if downloads get large

## What to do next

1. Upload your app files somewhere public
2. Replace the URLs in `app.js`
3. Open `MVP_STRUCTURE.md`
4. Review `supabase_schema.sql`
5. If you like the direction, next step is building the real Next.js + Supabase version

## Easy link setup

Open `website/app.js`.

At the top you will see:

```js
const PUBLIC_LINKS = {
  repo: "...",
  releases: "...",
  downloadInstaller: "...",
  downloadPortable: "...",
  issues: "...",
  donate: "https://ko-fi.com/3dvisualmesh",
};
```

Replace these with your real links:

- `repo`
  your GitHub repository page
- `releases`
  your GitHub Releases page
- `downloadInstaller`
  direct public URL to `3DVisualMeshSetup_0.1.0.exe`
- `downloadPortable`
  direct public URL to `3DVisual Mesh Share (BETA) (Version 0.1.0).zip`
- `issues`
  your GitHub Issues page
- `donate`
  your Ko-fi page

## Best simple public hosting path

1. Create a GitHub repo
2. Upload the website folder
3. Create a GitHub Release
4. Upload:
   - `3DVisualMeshSetup_0.1.0.exe`
   - `3DVisual Mesh Share (BETA) (Version 0.1.0).zip`
5. Copy the public file URLs from that release
6. Paste those URLs into `website/app.js`
7. Deploy the `website/` folder

## GPU support note

The current desktop app release path is designed for:

- Windows + AMD Radeon
- Windows + NVIDIA

The launcher detects the GPU family on first setup and installs the matching path.

## Important note

The current website already handles:

- optional donation popup before download
- continue to download without donating
- direct support button

So once your real public URLs are pasted into `PUBLIC_LINKS`, the site is ready to use without extra code changes.
