"""LLM-assisted QRF parsing via Hugging Face Inference API with regex fallback."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".cache" / "staad_generator" / "ai_parse"


@dataclass
class MezzanineSpec:
    """Structured mezzanine parameters extracted from QRF text."""

    elevation_m: float = 0.0
    width_m: float = 0.0
    length_m: float = 0.0
    live_load_kn_m2: float = 5.0
    slab_dead_load_kn_m2: float = 2.0
    col_spacing_m: float = 6.0


def _cache_path(key: str) -> Path:
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{h}.json"


def _load_cache(key: str) -> MezzanineSpec | None:
    p = _cache_path(key)
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            return MezzanineSpec(**{k: v for k, v in d.items() if k in MezzanineSpec.__dataclass_fields__})
        except Exception:
            return None
    return None


def _save_cache(key: str, spec: MezzanineSpec) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps(asdict(spec)), "utf-8")
    except OSError:
        pass


def _regex_parse_mezzanine(rows: list[Mapping[str, Any]]) -> MezzanineSpec:
    """Parse mezzanine fields from QRF section rows using regex patterns."""
    idx: dict[str, str] = {}
    for r in rows:
        d = str(r.get("desc", "")).strip().lower()
        if d:
            idx[d] = str(r.get("details", ""))

    spec = MezzanineSpec()

    # Size: "10 m x 20 m" or "17.5 m x 95.85 m : 1677 m^2"
    size_text = idx.get("mezzanine size", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*m\s*[xX×]\s*(\d+(?:\.\d+)?)\s*m", size_text)
    if m:
        spec.width_m = float(m.group(1))
        spec.length_m = float(m.group(2))

    # Height/Elevation: "2.5 m" or "at 5.00 m Level"
    height_text = idx.get("height", "")
    if not height_text:
        # Try extracting from size text "at X.XX m Level"
        m_lev = re.search(r"at\s+(\d+(?:\.\d+)?)\s*m\s+level", size_text, re.I)
        if m_lev:
            spec.elevation_m = float(m_lev.group(1))
    else:
        m_h = re.search(r"(\d+(?:\.\d+)?)\s*m", height_text)
        if m_h:
            spec.elevation_m = float(m_h.group(1))

    # Live Load: "5.0 kN/sqm" or "1000 kg/m^2"
    ll_text = idx.get("live load", "")
    m_kn = re.search(r"(\d+(?:\.\d+)?)\s*kN\s*/\s*(?:sqm|m\s*\^?\s*2|m²)", ll_text, re.I)
    m_kg = re.search(r"(\d+(?:\.\d+)?)\s*kg\s*/\s*(?:m\s*\^?\s*2|m²)", ll_text, re.I)
    if m_kn:
        spec.live_load_kn_m2 = float(m_kn.group(1))
    elif m_kg:
        spec.live_load_kn_m2 = float(m_kg.group(1)) * 9.81 / 1000

    # Dead Load / Slab
    dl_text = idx.get("dead load", "")
    m_dl = re.search(r"(\d+(?:\.\d+)?)\s*kN\s*/\s*(?:sqm|m\s*\^?\s*2|m²)", dl_text, re.I)
    m_dk = re.search(r"(\d+(?:\.\d+)?)\s*kg\s*/\s*(?:m\s*\^?\s*2|m²)", dl_text, re.I)
    if m_dl:
        spec.slab_dead_load_kn_m2 = float(m_dl.group(1))
    elif m_dk:
        spec.slab_dead_load_kn_m2 = float(m_dk.group(1)) * 9.81 / 1000

    # Column spacing
    cs_text = idx.get("mezzanine column spacing", "")
    m_cs = re.search(r"(\d+(?:\.\d+)?)\s*m", cs_text)
    if m_cs:
        spec.col_spacing_m = float(m_cs.group(1))

    return spec


def _llm_parse_mezzanine(rows: list[Mapping[str, Any]]) -> MezzanineSpec | None:
    """Use Hugging Face Inference API to extract structured mezzanine data."""
    try:
        from huggingface_hub import InferenceClient
    except ImportError:
        logger.debug("huggingface_hub not installed; skipping LLM parse")
        return None

    raw_text = "\n".join(
        f"{r.get('desc', '')}: {r.get('details', '')}" for r in rows
    )
    cache_key = f"mezz_llm:{raw_text}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    prompt = f"""Extract mezzanine floor parameters from this QRF data. Return ONLY valid JSON with these keys:
- elevation_m (float): height above ground in meters
- width_m (float): mezzanine width in meters
- length_m (float): mezzanine length in meters
- live_load_kn_m2 (float): live load in kN/m²
- slab_dead_load_kn_m2 (float): dead load in kN/m²
- col_spacing_m (float): column spacing in meters

Use 0.0 for unknown values. Convert kg/m² to kN/m² (divide by ~102).

QRF Data:
{raw_text}

JSON:"""

    try:
        client = InferenceClient()
        response = client.text_generation(
            prompt,
            model="Qwen/Qwen2.5-Coder-32B-Instruct",
            max_new_tokens=256,
            temperature=0.1,
        )
        text = response.strip()
        # Extract JSON from response
        m = re.search(r"\{[^}]+\}", text, re.DOTALL)
        if m:
            d = json.loads(m.group())
            spec = MezzanineSpec(
                elevation_m=float(d.get("elevation_m", 0)),
                width_m=float(d.get("width_m", 0)),
                length_m=float(d.get("length_m", 0)),
                live_load_kn_m2=float(d.get("live_load_kn_m2", 5.0)),
                slab_dead_load_kn_m2=float(d.get("slab_dead_load_kn_m2", 2.0)),
                col_spacing_m=float(d.get("col_spacing_m", 6.0)),
            )
            _save_cache(cache_key, spec)
            return spec
    except Exception as exc:
        logger.debug("LLM mezzanine parse failed: %s", exc)

    return None


def parse_mezzanine_rows(rows: list[Mapping[str, Any]]) -> MezzanineSpec:
    """Parse mezzanine details: try LLM first, fall back to regex."""
    if not rows:
        return MezzanineSpec()

    llm_result = _llm_parse_mezzanine(rows)
    if llm_result is not None and (llm_result.width_m > 0 or llm_result.elevation_m > 0):
        logger.info("Mezzanine parsed via LLM: %s", llm_result)
        return llm_result

    regex_result = _regex_parse_mezzanine(rows)
    logger.info("Mezzanine parsed via regex: %s", regex_result)
    return regex_result
