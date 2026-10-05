# Lutris Integration for Playlite

Import, register, launch, and detect Lutris games, with playtime tracking.

This repository contains only this plugin. Playlite itself lives in
[swolfgang-dev/Playlite](https://github.com/swolfgang-dev/Playlite).
Requires Playlite 0.2.11 or later, plugin API 1.

## Installation

Authenticate to GitHub with `gh auth login` (repositories are private), then:

```sh
playlite-plugins install swolfgang-dev/playlite-plugin-lutris
```

Or choose Settings → Plugins → Installed → Install / update from GitHub.
Restart Playlite after installation or updating. Settings and game data remain in
Playlite's existing user-data folders. 

## Default folders

In Settings → Plugins → Installation → Lutris Integration, set the default installation
parent folder and Wine prefix parent folder. Add to Lutris and Lutris play-action
folder selectors open at the field’s own path when filled, or at its configured
default when empty. New prefix paths open at their nearest existing parent. When adding a game beneath the installation parent,
its first folder under that parent prefills the metadata name and a kebab-case
prefix path under the prefix parent. For example, `The Witcher 3/bin/game.exe`
prefills `The Witcher 3` and `<prefix parent>/the-witcher-3`. Custom names and
prefix paths are preserved. Installation paths beneath the default parent are
trimmed to the first game folder, removing nested executable folders. Prefix
folder creation is checked by default. The default Wine runner is `ge-proton`,
Lutris’s identifier for GE-Proton (Latest). Older `GE-Proton` input is normalized
on registration; explicit versioned runner names are preserved. Clear a default to restore normal browsing.

## Releases

Push a `v1.1.0`-style tag to run the release workflow. Each release
contains `plugin.zip` and `SHA256SUMS`. The archive has `manifest.json` and
`plugin.py` at its root; it never includes the base application.

Build locally with `python3 tools/build_release.py`.
The manifest declares any additional Python dependencies, installed into the
same environment as Playlite.

## Tests

Plugin integration tests live in `tests/`. Install Playlite and the optional
plugins required by a test, then run:

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -q
```

Tests requiring absent plugins are skipped. The release workflow checks Python
syntax and builds the standalone archive; integration tests run locally with
Playlite installed. Native executables are not bundled in the SteamAutoCrack
plugin; its separate tool installer downloads/builds them when requested.

## Distribution

Packages are published separately to `swolfgang-dev/playlite-plugin-lutris-releases`. Its visibility controls anonymous browsing and downloads independently of this private development repository.

After updating the manifest version, publish with `python3 tools/publish_distribution.py vVERSION` using your authenticated GitHub CLI. For automatic publishing on version tags, configure the repository Actions secret `PLUGIN_DISTRIBUTION_TOKEN` with a fine-grained token granting Contents read/write access to the distribution repository. The workflow never changes repository visibility.
