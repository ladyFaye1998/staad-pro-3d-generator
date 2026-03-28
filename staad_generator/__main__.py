"""CLI: batch-convert competition JSON files in ./data -> ./output .std files."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from staad_generator._version import __version__
from staad_generator.geometry import build_frame
from staad_generator.logutil import configure_logging
from staad_generator.spec import format_spec_summary, spec_from_json_path
from staad_generator.validate import FrameValidationError
from staad_generator.writer import batch_convert, build_std_text, json_file_to_std


def main() -> None:
    p = argparse.ArgumentParser(
        prog="staad_generator",
        description="Generate STAAD .std command files from QRF JSON (PEB pipeline).",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    p.add_argument(
        "--data",
        type=Path,
        default=Path("data"),
        help="Directory containing *.json (default: ./data)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directory for *.std (default: ./output)",
    )
    p.add_argument(
        "--one",
        type=Path,
        default=None,
        metavar="FILE.json",
        help="Convert one JSON to <stem>.std under --output (default: ./output)",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Parse and validate only; do not write .std files",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print parsed spec summary for each input",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress per-file lines (batch summary still prints unless dry-run)",
    )
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging level (default: INFO if -v, ERROR if -q, else WARNING)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Always write .std (overrides --skip-fresher)",
    )
    p.add_argument(
        "--skip-fresher",
        action="store_true",
        help="Skip conversion when output .std exists and is newer than input JSON",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="Run PyNite FEA verification (simplified portal frame, iterative section optimizer)",
    )
    args = p.parse_args()

    log_level = args.log_level
    if log_level is None:
        if args.quiet:
            log_level = "ERROR"
        elif args.verbose:
            log_level = "INFO"
        else:
            log_level = "WARNING"
    configure_logging(log_level)

    try:
        if args.one:
            t0 = time.perf_counter()
            if not args.dry_run:
                args.output.mkdir(parents=True, exist_ok=True)
            dest = args.output / f"{args.one.stem}.std"
            if (
                args.skip_fresher
                and not args.force
                and not args.dry_run
                and dest.exists()
            ):
                try:
                    if dest.stat().st_mtime >= args.one.stat().st_mtime:
                        if not args.quiet:
                            print(f"{dest}  (skipped, output newer than input)")
                        return
                except OSError:
                    pass
            spec = spec_from_json_path(args.one)
            fm = build_frame(spec)
            if args.verbose and not args.quiet:
                logger.info(
                    "%s",
                    format_spec_summary(
                        spec,
                        n_joints=len(fm.joint_coords),
                        n_members=len(fm.members),
                    ),
                )
            text = build_std_text(spec, fm)
            if args.dry_run:
                if not args.quiet:
                    print(f"[dry-run] OK: {args.one.name} -> would write {dest}")
                return
            out = json_file_to_std(
                args.one,
                dest,
                text=text,
                force=args.force,
                skip_if_fresher=False,
            )
            if args.quiet:
                print(out)
            else:
                dt = time.perf_counter() - t0
                print(f"{out}  ({len(fm.joint_coords)} joints, {len(fm.members)} members, {dt:.2f}s)")
            if args.verify:
                from staad_generator.fea_verify import verify_portal_frame

                result = verify_portal_frame(spec)
                print(f"\n{result.summary}")
            return

        t0 = time.perf_counter()
        paths = batch_convert(
            args.data,
            args.output,
            dry_run=args.dry_run,
            verbose=args.verbose,
            quiet=args.quiet,
            force=args.force,
            skip_if_fresher=args.skip_fresher,
        )
        if not paths:
            print(
                f"No JSON files in {args.data.resolve()}. Place Kaggle *.json there after download.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not args.quiet:
            prefix = "[dry-run] " if args.dry_run else ""
            for q in paths:
                print(f"{prefix}{q}")
        tag = "Validated (dry-run)" if args.dry_run else "Done"
        if not args.quiet or args.dry_run:
            print(f"{tag}: {len(paths)} file(s) in {time.perf_counter() - t0:.2f}s -> {args.output.resolve()}")

        if args.verify and not args.dry_run:
            from staad_generator.fea_verify import verify_portal_frame

            print("\n--- FEA Verification (PyNite) ---")
            for jp in sorted(args.data.glob("*.json")):
                spec = spec_from_json_path(jp)
                result = verify_portal_frame(spec)
                print(f"\n{spec.name}:")
                print(result.summary)
    except FrameValidationError as e:
        logger.error("%s", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
