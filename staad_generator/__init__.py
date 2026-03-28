"""JSON QRF/spec → STAAD.Pro command file (.std) generator for PEB-style frames."""

from staad_generator._version import __version__
from staad_generator.ai_parser import MezzanineSpec, parse_mezzanine_rows
from staad_generator.boq import BOQSummary, estimate_boq, format_boq
from staad_generator.section_optimizer import optimize_sections
from staad_generator.spec import format_spec_summary
from staad_generator.validate import FrameValidationError, validate_frame, validate_frame_or_raise
from staad_generator.writer import build_std_text, json_file_to_std

__all__ = [
    "__version__",
    "BOQSummary",
    "build_std_text",
    "estimate_boq",
    "format_boq",
    "format_spec_summary",
    "FrameValidationError",
    "json_file_to_std",
    "MezzanineSpec",
    "optimize_sections",
    "parse_mezzanine_rows",
    "validate_frame",
    "validate_frame_or_raise",
]
