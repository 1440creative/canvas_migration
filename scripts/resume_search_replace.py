#!/usr/bin/env python3
"""
Print the --course-ids argument needed to resume a search_replace_html.py run.

Usage:
    python scripts/resume_search_replace.py [--log PATH]

Reads the log (default: logs/search_replace_20261008.log), finds the last
completed course, and prints all remaining course IDs as a comma-separated
string ready to paste into --course-ids.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Ordered master list extracted from the dry run (search_replace_dryrun_20261006.log).
# Preserves the exact processing order used by --account-id blueprint lookup.
MASTER_ORDER = [
    470,471,472,473,474,475,476,477,478,492,
    2925,2926,2927,2928,2929,2930,2931,2932,2933,2934,
    2953,2954,2955,2956,2957,2958,2961,2964,2965,2967,
    2972,2974,2975,2976,
    3031,3032,3033,3034,3035,3037,3038,3039,3040,3041,3043,3044,3045,
    3078,3083,3084,
    3142,3143,3144,3145,3146,3147,3148,3149,3150,3152,3153,
    3161,3162,3163,3164,3165,3166,
    3954,3955,3956,3957,3958,3961,3962,3963,3965,3967,3968,3969,3970,3971,
    3993,3998,
    4009,4013,4016,4020,4022,4026,4028,
    4032,4033,4046,4050,4051,4053,
    4146,4161,4162,4163,4164,4165,4170,4171,4172,4208,
    4339,4341,4343,4349,4352,4353,4358,4359,4360,4361,
    4371,4372,4373,4374,4376,4377,4380,4381,
    4402,4404,4405,4407,4408,4409,4410,
    4417,4419,4420,4422,4424,4425,4426,4431,
    4452,4453,4454,4455,4461,4462,4463,4469,
    4479,4481,4483,4485,4486,4489,4497,4498,4499,4500,4501,
    4512,4513,4514,
    4943,4944,5042,5183,
    5231,5238,5240,5445,
    5458,5459,5460,5461,
    5702,6055,6144,
    9104,9105,9106,9107,9108,9253,9438,
    12597,12804,13982,14076,14131,14178,14179,14243,
    14442,14477,14638,14824,
    16034,17683,17701,17702,17715,17958,17965,18202,19496,
]


def last_completed_course(log_path: Path) -> int | None:
    pattern = re.compile(r"course=(\d+).*search/replace complete")
    last: int | None = None
    with log_path.open() as fh:
        for line in fh:
            m = pattern.search(line)
            if m:
                last = int(m.group(1))
    return last


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--log",
        default=str(REPO_ROOT / "logs" / "search_replace_20261008.log"),
        help="Path to the in-progress log file.",
    )
    p.add_argument(
        "--include-last",
        action="store_true",
        help="Re-run the last completed course (useful if it may have been partial).",
    )
    args = p.parse_args(argv)

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"Log not found: {log_path}", file=sys.stderr)
        return 1

    last = last_completed_course(log_path)
    if last is None:
        print("No completed courses found in log — run from the beginning.", file=sys.stderr)
        print(",".join(str(c) for c in MASTER_ORDER))
        return 0

    if last not in MASTER_ORDER:
        print(
            f"Last completed course {last} not in master list — cannot determine resume point.",
            file=sys.stderr,
        )
        return 1

    idx = MASTER_ORDER.index(last)
    start = idx if args.include_last else idx + 1
    remaining = MASTER_ORDER[start:]

    completed = idx + 1
    total = len(MASTER_ORDER)
    print(
        f"Last completed: course {last} ({completed}/{total} done, {len(remaining)} remaining)",
        file=sys.stderr,
    )

    if not remaining:
        print("All courses complete — nothing to resume.", file=sys.stderr)
        return 0

    print(",".join(str(c) for c in remaining))
    return 0


if __name__ == "__main__":
    sys.exit(main())
