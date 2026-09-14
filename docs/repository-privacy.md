# Repository privacy and credential checks

The repository is private. It contains selected portfolio material, including
the author's name and GitHub username. It excludes operational credentials,
payment records, private project logs and original local development history.

The September 13, 2026 review checked the 24 portfolio files and both commits
then reachable on the main branch, plus the initial replaced web commit.
Gitleaks 8.30.1 found no credentials. Supplemental checks found no real
passwords, payment-card or bank details, personal email in file content,
authenticated service URLs, wallet keys or local home-directory paths.

The `example.com` token in the monitoring test is a deliberately fake value
used to check that error output is sanitized. It is not a working credential.

## September 14 portfolio update

GitHub reported this repository as private, with only its owner listed as a
collaborator. The update adds selected marketplace implementation excerpts,
a generated video preview frame and project explanations. It excludes the
original application source tree, full project archives and operational data.
CV files, application responses and personal contact details are prepared
separately from this repository.

The local pre-upload review uses Gitleaks 8.30.1 for the working directory and
all reachable Git history, plus supplemental checks for private data and
tracked files that match ignore rules. The generated preview frame was
visually reviewed and contains no text or EXIF metadata chunks. The dated
review is a check of the upload contents, not a guarantee about future edits
or retained historical objects.

## Check future changes

GitHub Actions scans Git history with Gitleaks on pushes and pull requests.
The scanner version and download checksum are pinned; findings are redacted
in logs. This check runs after a push, so review changes before uploading them.

To run the same credential check locally with Gitleaks 8.30.1 installed:

```bash
gitleaks git . --log-opts="--all --full-history" --redact=100 --no-banner --ignore-gitleaks-allow
gitleaks dir . --redact=100 --no-banner --ignore-gitleaks-allow
```

The ignore file excludes common credential files, local configuration,
databases, archives and audit output. Ignore rules do not remove files already
committed. Neither ignore rules nor automated scans guarantee that arbitrary
personal information cannot be included in prose or an unknown file format.

## Historical metadata limitation

The first web commit used the account's personal email. That commit was
replaced; the current branch uses GitHub noreply addresses. Email privacy is
enabled for future web commits, and this checkout uses a noreply address.
The old commit remains retained by GitHub and is inaccessible without repository
access while the repository is private. Removing a branch reference does not
erase retained commit objects or copies previously obtained by others.

[GitHub's removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
describes requesting removal of retained sensitive data through GitHub Support.
No claim is made that the old email metadata has been erased from GitHub.
