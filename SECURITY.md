# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: open the **Security** tab of this
repository and choose **Report a vulnerability**. Please don't use public issues for this.

I aim to reply within 3 business days and to ship a fix or a workaround within 90 days.

## What counts

- A way for an app running inside DroidTrace to escape or reach the host with the default settings
- A crafted trace file that crashes or exploits the reader or the live viewer
- A problem in how releases or the Docker image are built

## Handling malware samples

Never attach a live sample to an issue or pull request. Share its SHA-256 hash and a link to a
reputable source (for example MalwareBazaar) instead.

## Supported versions

Security fixes go into the latest release.
