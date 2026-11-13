# Security

## Reporting a vulnerability

Report vulnerabilities privately, not in a public issue. Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability"), or email deukwoong.woo@a2sys.ai.

Include the jevfetch version you installed (`uv tool list` or `pip show jevfetch` shows it), the command you ran, and what you observed. Fixes are released as a new version on PyPI.

## Scope

jevfetch fetches any URL it is given, follows redirects, and sends the page text and the question to the TypeSafe API. These are documented behaviors (see "Privacy and security" in README.md), not vulnerabilities. A report is in scope when it shows a way to make jevfetch do something with security impact beyond these behaviors, such as reading a local file it did not download, writing files other than its caches and saved downloads, running code, or sending data anywhere other than the page it was given (including its redirects and, when rendered in Chrome, the resources the page loads), the TypeSafe API, and tiktoken's one-time encoding download.
