# Snapshot sources

The jevfetch code is MIT-licensed. The files in this directory are third-party content redistributed under
the licences named here. The sentences listed under [Passages copied elsewhere](#passages-copied-elsewhere)
are short quotations with their sources named, not copies of the pages.

Each file is the page body as served on the fetch date, saved unchanged; the HTML pages are gzipped. Fetched with jevfetch's own
fetcher (`jevfetch.web.fetch`, User-Agent `jevfetch/<version>`), 2026-10-09.

| file | source | license | notice |
|---|---|---|---|
| python-functools.html.gz | https://docs.python.org/3/library/functools.html | PSF License Version 2 | Copyright © 2001 Python Software Foundation; All Rights Reserved. License text: `LICENSE-PSF.txt` (from https://docs.python.org/3/license.html) |
| python-subprocess.html.gz | https://docs.python.org/3/library/subprocess.html | PSF License Version 2 | same as above |
| wiki-world-war-ii.html.gz | https://en.wikipedia.org/wiki/World_War_II | CC BY-SA 4.0 | Wikipedia contributors; https://creativecommons.org/licenses/by-sa/4.0/ |
| wiki-python.html.gz | https://en.wikipedia.org/wiki/Python_(programming_language) | CC BY-SA 4.0 | same as above |
| mdn-cache-control.html.gz | "Cache-Control", https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control | CC BY-SA 2.5 (prose), https://creativecommons.org/licenses/by-sa/2.5/ | Mozilla Contributors; MDN licence policy: https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Attrib_copyright_license |
| mdn-array-sort.html.gz | "Array.prototype.sort()", https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort | CC BY-SA 2.5 (prose), https://creativecommons.org/licenses/by-sa/2.5/; CC0 (code samples), https://creativecommons.org/publicdomain/zero/1.0/ | same as above |
| rfc9110.html.gz | https://www.rfc-editor.org/rfc/rfc9110.html | IETF Trust Legal Provisions (BCP 78) | Copyright (c) 2022 IETF Trust and the persons identified as the document authors. https://trustee.ietf.org/license-info |
| rfc8259.html.gz | https://www.rfc-editor.org/rfc/rfc8259.html | IETF Trust Legal Provisions (BCP 78) | Copyright (c) 2017 IETF Trust and the persons identified as the document authors |
| uv-readme.md | https://raw.githubusercontent.com/astral-sh/uv/main/README.md | MIT (of the Apache-2.0 OR MIT choice) | Copyright (c) 2025 Astral Software Inc.; licence text: `LICENSE-uv-MIT.txt` (from https://github.com/astral-sh/uv/blob/main/LICENSE-MIT) |
| nist-sp800-63b.html.gz | https://pages.nist.gov/800-63-3/sp800-63b.html | US Government work, public domain in the US | NIST Special Publication 800-63B |

Content hashes are recorded per case in `bench/baseline.json` (`snapshot_sha256`).

## Passages copied elsewhere

`bench/cases.json` (`facts`) and `bench/agents/questions.json` (`gold`) hold a few sentences quoted from
each page, used as grading keys. The `facts`
are quoted from the snapshots above and the `gold` sentences from the pages the agent questions point at.
The site each sentence comes from and the licence that site states for its pages:

| site | licence | source of the licence statement |
|---|---|---|
| docs.cloud.google.com | CC BY 4.0 | page footer |
| docs.github.com | CC BY 4.0 | https://github.com/github/docs/blob/main/LICENSE |
| kubernetes.io | CC BY 4.0 | https://github.com/kubernetes/website/blob/main/LICENSE |
| docs.npmjs.com | CC BY 4.0 | https://github.com/npm/documentation/blob/main/LICENSE |
| docs.docker.com | Apache-2.0 | https://github.com/docker/docs/blob/main/LICENSE |
| developer.mozilla.org | CC BY-SA 2.5 | see above |
| en.wikipedia.org, ko.wikipedia.org | CC BY-SA 4.0 | https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use |
| docs.python.org | PSF License Version 2 | `LICENSE-PSF.txt` |
| www.postgresql.org | PostgreSQL License | https://www.postgresql.org/about/licence/ |
| www.sqlite.org | public domain | https://www.sqlite.org/copyright.html |
| git-scm.com (git manual pages) | GPL-2.0 | https://github.com/git/git/blob/master/COPYING |
| www.rfc-editor.org | IETF Trust Legal Provisions (BCP 78) | see above |
| pages.nist.gov | US Government work | see above |
| redis.io | CC BY-SA 4.0: the four EXPIRE sentences are in the earlier redis-doc repository, which carries that licence; the current site states CC BY-NC-SA 4.0 for the rest | https://github.com/redis/redis-doc/blob/master/commands/expire.md and https://github.com/redis/redis-doc/blob/master/LICENSE; https://github.com/redis/docs/blob/main/LICENSE |
| nginx.org | BSD-2-Clause (the documentation source repository's licence) | https://github.com/nginx/nginx.org/blob/main/text/LICENSE |
| docs.stripe.com, docs.claude.com | no licence stated on the site | |

## Annotation

- Questions were written from each page's title and section headings before reading the body
  (`question_source: heading-list`), except the two `unrelated` negatives (`author`). No question was
  copied from body text. Section names can still appear in the question; Jev sees heading paths, so
  this is a known lexical clue.
- `facts` are copied from the page; `keys` are short values any correct answer must contain, with
  aliases where the page's literal form differs from a natural paraphrase. Keys match as whole
  tokens after SQuAD normalization, so a value glued to a unit or URL scheme (`86400s`,
  `https://astral.sh/...`) needs the literal form as an alias.
- Negatives: `unrelated` questions are off-topic; `near-topic` questions are about the page's subject
  but the page does not state the answer. Confirming that needs the page read in full.
- One annotator. Facts are verbatim spans, so correctness of a fact is an existence check, not a
  judgment. Whether a fact is the complete answer is a judgment and is not checked.
