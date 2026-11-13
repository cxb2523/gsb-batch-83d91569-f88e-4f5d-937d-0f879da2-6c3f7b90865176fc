from dataclasses import dataclass

AGGREGATE_LIMIT = 1.10
CASE_LIMIT = 1.50


@dataclass
class Failure:
    rule: str
    case_id: str
    detail: str
    blocking: bool = True

    def __str__(self) -> str:
        return f"{self.rule}: {self.case_id}: {self.detail}"


def compare(baseline: dict, run: dict, update_baseline: bool = False) -> list[Failure]:
    out: list[Failure] = []
    regression_blocks = not update_baseline

    if run["model"]["resolved"] != baseline["model"]["resolved"]:
        out.append(Failure("model", "*", f"baseline {baseline['model']['resolved']}, run {run['model']['resolved']}"))
    if run.get("missing_recordings"):
        out.append(Failure("missing_recording", "*", ", ".join(run["missing_recordings"])))

    base_cases, cur_cases = baseline["cases"], run["cases"]
    common = [i for i in base_cases if i in cur_cases]
    for cid in base_cases:
        if cid not in cur_cases:
            out.append(Failure("missing_case", cid, "in baseline but not in this run", regression_blocks))
    for cid, c in cur_cases.items():
        if not c.get("missing_recording") and c["status"] != c["expected_status"]:
            out.append(Failure("status", cid, f"expected {c['expected_status']}, got {c['status']}", regression_blocks))
    for cid in common:
        b, c = base_cases[cid], cur_cases[cid]
        if c.get("missing_recording"):
            continue  # already reported once above; the case has no scores to compare
        if not update_baseline:
            for field in ("question", "snapshot_sha256"):
                if b.get(field) != c.get(field):
                    out.append(Failure("identity", cid, f"{field} changed; rerun with --update-baseline"))
        for kind, noun in (("facts", "fact"), ("keys", "key")):
            for h, passed in b.get(kind, {}).items():
                if h not in c.get(kind, {}):
                    out.append(Failure(f"removed_{noun}", cid, h, regression_blocks))
                elif passed and not c[kind][h]:
                    out.append(Failure(f"lost_{noun}", cid, h, regression_blocks))
        for h, passed in b.get("extraction", {}).items():
            if passed and not c.get("extraction", {}).get(h, False):
                out.append(Failure("extraction", cid, h, regression_blocks))
        for field in ("out_tokens", "workload"):
            if b.get(field, 0) and c.get(field, 0) > CASE_LIMIT * b[field]:
                out.append(Failure(f"case_{field}", cid, f"{b[field]} -> {c[field]}", regression_blocks))
    for field in ("out_tokens", "workload"):
        before = sum(base_cases[i].get(field, 0) for i in common)
        after = sum(cur_cases[i].get(field, 0) for i in common)
        if before and after > AGGREGATE_LIMIT * before:
            out.append(
                Failure(
                    f"aggregate_{field}", "*", f"{before} -> {after} over {len(common)} common cases", regression_blocks
                )
            )
    return out
