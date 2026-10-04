# Releases and Home Assistant lifecycle

Verified on 2026-10-04 against official documentation, HACS 2.0.5 and current
upstream HACS source, and HA 2026.9.4 source. Recheck these assumptions if upstream
adds a supported mechanism; do not invent an integration-specific replacement.

## Versioned distribution

HACS [prefers GitHub releases](https://www.hacs.xyz/docs/publish/integration/#github-releases-optional).
Its [version rules](https://www.hacs.xyz/docs/publish/start/#versions) use the release
tag as the available version. A Git tag alone is insufficient. Without releases,
HACS falls back to a commit identifier; the integration manifest's version does
not change that behavior.

Use ordinary published GitHub releases with tags such as `0.6.2`, matching
`custom_components/vegvesen/manifest.json`. Keep root/minimum project versions
and their lockfile project metadata synchronized. Publish from the exact tested
commit after Checks and Validate pass. Include concise user-facing changes,
compatibility, restart instructions and material limitations in the release notes.
Use prereleases for deliberately experimental builds. Never move an existing
release tag to different code; corrections get a new version.

The standard `custom_components/vegvesen/` layout already supports release
installation. No `zip_release`, generated update entity, custom version sensor,
HACS storage edits or release asset is needed. The local ZIP remains a development
artifact. Default HACS listing is separate and remains deferred. Publishing a
release is an intentional maintainer action, not a side effect of every push.

A normal release can be published through GitHub's Releases UI: select the exact
validated commit, create its matching version tag, enter release notes and publish.
There is no custom release workflow to maintain. Before publishing, run the checks
in [validation.md](validation.md) and verify the version/tag/commit match. Afterward,
verify that the published release is not a draft or prerelease and its tag points
to that commit. Documentation-only work does not require a new runtime version.

Users previously on the default branch may initially see a commit-to-version
transition. HACS's [repository menu](https://www.hacs.xyz/docs/use/repositories/dashboard/)
provides **Update information** and **Redownload**; select the numbered release
if needed. Future release installations show numbered versions. Choosing `main`
continues to opt into development commits and can still show commit identifiers.
Do not rewrite HACS's stored installed-version state to hide this transition.

## Restart, reload and frontend refresh

For updates to an already installed Python integration, HACS
[marks a restart as required](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/repositories/integration.py#L40).
The inspected [current upstream implementation](https://github.com/hacs/integration/blob/main/custom_components/hacs/repositories/integration.py)
has the same behavior. Its exception is first installation of an integration with
a config flow: refreshing the discovery cache can make newly installed code
available without a restart. This is not a hot-upgrade contract for loaded code.

HA's [config-entry lifecycle](https://developers.home-assistant.io/docs/config_entries_index/)
supports unloading and setting up entries again. The
[reload implementation](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/config_entries.py)
uses that lifecycle; its [integration loader](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/loader.py)
caches imported components. Reloading configuration does not promise to replace
already imported Python modules. Vegvesen already supports entry reload/unload
for configuration changes and resource cleanup. It does not implement Python
module reloading or suppress HACS's restart repair.

| Action | Purpose |
| --- | --- |
| Reload the integration | Recreate its runtime using the loaded code and saved configuration |
| Restart Home Assistant | Load the upgraded backend code and dependencies |
| Refresh browser/app frontend | Load updated frontend resources and translations when cached |
| Reboot the host | Restart the operating system; unnecessary for this integration's normal updates |

HACS [update presentation](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/update.py)
distinguishes Python integrations (HA restart) from dashboard plugins (frontend
cache refresh). Themes and other repository categories also have different
lifecycles. That distinction can explain apparently restart-free HACS updates;
without inspecting a specific other integration, do not assume its mechanism.
