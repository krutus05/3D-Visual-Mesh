# Installer Assets

Best choice:

- `build_release_package.ps1` for a clean portable zip/share folder
- `build_windows_installer.ps1` for a compiled Windows installer when `Inno Setup 6` is installed

Why:

- the release package strips out logs, caches, local venvs, and downloaded model/runtime folders
- the Windows installer script keeps the packaging path repeatable

What to do next:

1. Run `build_release_package.ps1`
2. If you want a `Setup.exe`, install `Inno Setup 6`
3. Run `build_windows_installer.ps1`
