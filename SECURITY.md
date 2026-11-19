# Security

If you find a security problem in Sleep Control, report it privately through [Report a vulnerability](https://github.com/Ghost-Hackers/sleep-control/security/advisories/new) on the repository's **Security** tab. Please don't open a public issue for it.

<p align="center"><a href="https://github.com/Ghost-Hackers/sleep-control/security/advisories/new"><img src="https://img.shields.io/badge/Report%20a%20vulnerability-d1242f?style=plastic&amp;logo=github" alt="Report a vulnerability"></a></p>

Include the version (`flatpak run io.github.ghost_hackers.sleep-control --version`), your distro and desktop, and the steps that show the problem.

## Contents

- [What to report](#what-to-report)
- [Verify a download](#verify-a-download)

## What to report

The app holds one sleep block through the Inhibit portal and listens on a socket in your runtime directory. Reports we want:

- A block that stays after you quit the app or after it crashes.
- The command line or the socket accepting input from another user.
- Flatpak permissions beyond the ones listed in the [README](README.md#how-it-works).

Fixes go into the latest release and the affected pre-release(s).

## Verify a download

Release files are built by GitHub Actions from the tag, with an attestation that names the commit and the workflow run. With the [GitHub CLI](https://cli.github.com/) installed:

```sh
gh attestation verify sleep-control-<version>.flatpak --repo Ghost-Hackers/sleep-control
```

The check passes only for the exact file the workflow built. To rule out a damaged download, compare it against the `.sha256` file attached to the same release:

```sh
sha256sum -c sleep-control-<version>.flatpak.sha256
```

The build is reproducible, so you can also rebuild a release from its tag and compare. The same tag gives the same bundle, byte for byte, as long as the SDK and BaseApp commits that [`tools/build.sh`](tools/build.sh) prints match the release build's:

```sh
git checkout v<version>
tools/build.sh
sha256sum dist/sleep-control-<version>.flatpak
```

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#security)
