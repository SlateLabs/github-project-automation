#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.stage_map import MANUAL_STAGES, REQUESTED_STAGE, default_reason_codes, resolve_next_stage


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("manual-stages")
    sub.add_parser("valid-stages")

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--requested-stage", required=True)
    resolve.add_argument("--feedback-source", default="")
    resolve.add_argument("--feedback-no-progress", action="store_true")
    resolve.add_argument("--review-disposition", default="")
    resolve.add_argument("--review-next-stage", default="")

    reasons = sub.add_parser("reason-codes")
    reasons.add_argument("--next-stage", default="")

    args = parser.parse_args()
    if args.cmd == "manual-stages":
        print("\n".join(MANUAL_STAGES))
        return
    if args.cmd == "valid-stages":
        print("\n".join((REQUESTED_STAGE, *MANUAL_STAGES)))
        return
    if args.cmd == "reason-codes":
        print(json.dumps(default_reason_codes(args.next_stage)))
        return
    if args.cmd == "resolve":
        resolved = resolve_next_stage(
            requested_stage=args.requested_stage,
            feedback_source=args.feedback_source,
            feedback_no_progress=args.feedback_no_progress,
            review_disposition=args.review_disposition,
            review_next_stage=args.review_next_stage,
        )
        print(json.dumps(resolved))
        return
    raise SystemExit(1)


if __name__ == "__main__":
    main()
