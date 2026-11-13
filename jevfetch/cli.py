"""jevfetch URL QUESTION: print the parts of a web page that answer QUESTION, quoted verbatim."""

import argparse
import json
import sys

from jevfetch.jev import JevError
from jevfetch.pipeline import Config, fetch_relevant

NOTES = {
    "filtered": "blocks are quoted from the page; '##' lines are the page's heading path",
    "passthrough": "the page is short, so it is returned whole",
    "no_match": "no block passed the threshold; the highest-scoring blocks are returned. "
    "This does not mean the page lacks the answer",
    "empty": "no text could be extracted; the page may load its content in a separate request or an iframe",
    "fetch_error": "the page could not be fetched, or it is not an HTML or text page",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jevfetch", description=__doc__)
    ap.add_argument("url")
    ap.add_argument("question", help="the user's question, as a sentence")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--no-render", action="store_true", help="do not fall back to a headless browser")
    ap.add_argument("--model", default=Config.model, help="Jev model name (default: %(default)s)")
    ap.add_argument(
        "--no-notes",
        action="store_true",
        help="do not score note and warning boxes on pages too long to pass through, saving their Jev requests",
    )
    args = ap.parse_args(argv)
    try:
        res = fetch_relevant(
            args.url,
            args.question,
            Config(render_fallback=not args.no_render, model=args.model, score_notes=not args.no_notes),
        )
    except JevError as e:
        print(f"jevfetch: Jev error: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False))
    else:
        head = [f"# jevfetch: {res.url}", f"# status: {res.status} ({NOTES[res.status]})"]
        if res.status in ("filtered", "no_match", "passthrough"):
            head.append(
                f"# {res.blocks_kept}/{res.blocks_total} blocks, {res.out_tokens} of {res.doc_tokens} tokens"
                + (", rendered with a headless browser" if res.rendered else "")
            )
        if res.error:
            head.append(f"# error: {res.error}")
        if res.saved:
            head.append(f"# saved: {res.saved}")
        print("\n".join(head + ([res.text] if res.text else [])))
    return 1 if res.status == "fetch_error" else 0


if __name__ == "__main__":
    sys.exit(main())
