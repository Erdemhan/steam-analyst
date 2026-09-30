"""Consistency checker for config/parameters.toml against FORMULATION.md §8.

This script verifies that all parameter values in config/parameters.toml match
the machine-readable summary in FORMULATION.md's §8 section. It exists to catch
parameter drift that could invalidate results and make them non-reproducible
(ADR-013). Runs in CI and as a startup assertion in orchestration.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

# Use tomllib for Python 3.11+, tomli for earlier versions
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        raise ImportError(
            "tomli is required for Python < 3.11. "
            "Install it with: pip install tomli"
        )


class ParameterConsistencyError(Exception):
    """Parameter consistency check failure.

    Raised when parameters.toml does not match the machine-readable summary
    in FORMULATION.md's §8 section. This is distinct from ParameterError
    (invalid syntax or missing keys) — this error means the two sources are
    out of sync.

    Attributes:
        message: Human-readable description of what was wrong.
    """

    def __init__(self, message: str) -> None:
        """Initialize ParameterConsistencyError.

        Args:
            message: Human-readable description of what was wrong.
        """
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        """Render error message."""
        return self.message


def extract_toml_block_from_formulation(formulation_path: Path) -> str:
    """Extract the toml block from FORMULATION.md §8.

    Reads FORMULATION.md and extracts the fenced toml code block that
    immediately follows the line '## 8. Machine-Readable Summary'.

    Args:
        formulation_path: Path to FORMULATION.md.

    Returns:
        The raw TOML content as a string (without the fence markers).

    Raises:
        ParameterConsistencyError: If the §8 heading or toml fence is missing
            or malformed.
    """
    try:
        with open(formulation_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError as e:
        raise ParameterConsistencyError(
            f"FORMULATION.md not found at {formulation_path}"
        ) from e
    except OSError as e:
        raise ParameterConsistencyError(
            f"Cannot read FORMULATION.md: {e}"
        ) from e

    # Find the §8 heading
    heading_marker = "## 8. Machine-Readable Summary"
    heading_idx = content.find(heading_marker)
    if heading_idx == -1:
        raise ParameterConsistencyError(
            "FORMULATION.md is missing the '## 8. Machine-Readable Summary' heading. "
            "This section is required and must not be deleted or renamed."
        )

    # Search for the opening fence after the heading
    search_start = heading_idx + len(heading_marker)
    fence_start = content.find("```toml", search_start)
    if fence_start == -1:
        raise ParameterConsistencyError(
            "FORMULATION.md's §8 section is missing the opening '```toml' fence. "
            "Ensure the fenced code block immediately follows the §8 heading."
        )

    # Find the closing fence
    fence_open_end = fence_start + len("```toml")
    fence_close = content.find("```", fence_open_end)
    if fence_close == -1:
        raise ParameterConsistencyError(
            "FORMULATION.md's §8 section has an unclosed toml code block. "
            "Ensure the fenced block has a closing '```' marker."
        )

    # Extract the content between fences
    toml_content = content[fence_open_end:fence_close].strip()
    return toml_content


def parse_toml_string(toml_str: str, source_label: str) -> dict[str, Any]:
    """Parse a TOML string.

    Args:
        toml_str: The raw TOML content as a string.
        source_label: Label for error messages (e.g. "FORMULATION.md §8").

    Returns:
        The parsed TOML as a dict.

    Raises:
        ParameterConsistencyError: On TOML syntax error.
    """
    try:
        # tomllib.loads expects a string
        parsed = tomllib.loads(toml_str)
        return parsed
    except Exception as e:
        # Catch both tomllib.TOMLDecodeError and tomli.TOMLDecodeError
        if "TOMLDecodeError" in type(e).__name__ or "decode" in str(type(e).__name__).lower():
            raise ParameterConsistencyError(
                f"Invalid TOML syntax in {source_label}: {e}"
            ) from e
        raise


def parse_toml_file(path: Path, source_label: str) -> dict[str, Any]:
    """Parse a TOML file.

    Args:
        path: Path to the TOML file.
        source_label: Label for error messages (e.g. "parameters.toml").

    Returns:
        The parsed TOML as a dict.

    Raises:
        ParameterConsistencyError: On file I/O or TOML syntax error.
    """
    try:
        with open(path, "rb") as f:
            parsed = tomllib.load(f)
        return parsed
    except FileNotFoundError as e:
        raise ParameterConsistencyError(
            f"{source_label} not found at {path}"
        ) from e
    except Exception as e:
        if "TOMLDecodeError" in type(e).__name__ or "decode" in str(type(e).__name__).lower():
            raise ParameterConsistencyError(
                f"Invalid TOML syntax in {source_label}: {e}"
            ) from e
        raise


def get_nested_value(d: dict[str, Any], key_path: str) -> tuple[bool, Any]:
    """Get a nested value from a dict using dot notation.

    Args:
        d: The dict to search.
        key_path: Dot-separated path (e.g. "coarse_filter.min_review_count").

    Returns:
        A tuple (found, value). If found is False, value is None.
    """
    parts = key_path.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return (False, None)
    return (True, current)


def flatten_dict(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict to dot-notation keys.

    Args:
        d: The dict to flatten.
        prefix: Current key prefix for recursion.

    Returns:
        A flat dict with dot-notation keys.
    """
    result = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(flatten_dict(v, full_key))
        else:
            result[full_key] = v
    return result


def map_formulation_key_to_parameters_key(form_key: str) -> str:
    """Map a FORMULATION.md §8 key path to the corresponding parameters.toml key path.

    FORMULATION.md §8 uses simplified keys (e.g. "coarse_filter.min_review_count")
    but parameters.toml nests coarse_filter under acquisition
    (e.g. "acquisition.coarse_filter.min_review_count").

    Args:
        form_key: A key path from flattened FORMULATION.md §8.

    Returns:
        The corresponding key path in flattened parameters.toml.
    """
    if form_key.startswith("coarse_filter."):
        # coarse_filter.X → acquisition.coarse_filter.X
        return "acquisition." + form_key
    # enrichment.* and analysis.* map directly
    return form_key


def compare_toml_dicts(
    formulation_dict: dict[str, Any],
    parameters_dict: dict[str, Any],
) -> list[str]:
    """Compare formulation §8 values against parameters.toml values.

    Only keys present in formulation_dict are checked; extra keys in
    parameters_dict are ignored (operational-only keys are allowed).

    Special handling: the two keys documented as legitimately absent
    (coarse_filter.max_review_count, analysis.tag_distance_threshold)
    are compared as "both absent = OK" or "both present with equal value = OK".

    Args:
        formulation_dict: Parsed FORMULATION.md §8 toml block.
        parameters_dict: Parsed config/parameters.toml.

    Returns:
        A list of mismatched key paths (using formulation-style keys for reporting).
        Empty list means everything matches.
    """
    # Keys documented as legitimately absent when unset
    optional_absent_keys = {
        "coarse_filter.max_review_count",
        "analysis.tag_distance_threshold",
    }

    # Flatten both dicts for easier comparison
    form_flat = flatten_dict(formulation_dict)
    params_flat = flatten_dict(parameters_dict)

    mismatches = []
    for form_key, form_value in form_flat.items():
        # Map the formulation key to the parameters key path
        params_key = map_formulation_key_to_parameters_key(form_key)

        # Check if this key is one of the special optional-absent ones
        if form_key in optional_absent_keys:
            # Special handling: both absent = OK, both present with equal = OK
            params_found, params_value = get_nested_value(
                parameters_dict, params_key
            )
            form_found, _ = get_nested_value(formulation_dict, form_key)

            if form_found and params_found:
                # Both present — check equality
                if form_value != params_value:
                    mismatches.append(form_key)
            elif form_found != params_found:
                # One present, one absent — this is OK for these special keys
                pass
            continue

        # Normal key: must exist in parameters and have equal value
        if params_key not in params_flat:
            mismatches.append(form_key)
        elif form_value != params_flat[params_key]:
            mismatches.append(form_key)

    return mismatches


def verify_parameters_consistency(
    formulation_path: Path, parameters_path: Path
) -> None:
    """Verify that parameters.toml matches FORMULATION.md's machine-readable summary.

    Args:
        formulation_path: Path to FORMULATION.md.
        parameters_path: Path to config/parameters.toml.

    Returns:
        None if every checked value matches.

    Raises:
        ParameterConsistencyError: On any mismatch, naming every offending key,
            so a single run surfaces the full drift rather than one value at a
            time across repeated fix-and-rerun cycles. Also raised if the §8
            section or its toml fence is missing (distinct error message).
    """
    # Extract and parse FORMULATION.md §8
    toml_block = extract_toml_block_from_formulation(formulation_path)
    formulation_dict = parse_toml_string(toml_block, "FORMULATION.md §8")

    # Parse parameters.toml
    parameters_dict = parse_toml_file(parameters_path, "config/parameters.toml")

    # Compare
    mismatches = compare_toml_dicts(formulation_dict, parameters_dict)

    if mismatches:
        mismatch_str = ", ".join(sorted(mismatches))
        raise ParameterConsistencyError(
            f"Parameter mismatch: the following keys in FORMULATION.md §8 do not "
            f"match config/parameters.toml: {mismatch_str}"
        )


def main() -> int:
    """CLI entry point.

    Parses command-line arguments and runs the verification. Returns 0 on
    success, 1 on mismatch or error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Verify that config/parameters.toml matches FORMULATION.md §8 "
            "(ADR-013 consistency check)."
        ),
    )
    parser.add_argument(
        "--formulation-path",
        type=Path,
        default=None,
        help=(
            "Path to FORMULATION.md (default: .claude/context/FORMULATION.md "
            "relative to project root)"
        ),
    )
    parser.add_argument(
        "--parameters-path",
        type=Path,
        default=None,
        help=(
            "Path to config/parameters.toml (default: config/parameters.toml "
            "relative to project root)"
        ),
    )

    args = parser.parse_args()

    # Resolve default paths relative to project root
    # Assume the project root is the directory containing this script's parent
    project_root = Path(__file__).parent.parent

    formulation_path = args.formulation_path or (
        project_root / ".claude" / "context" / "FORMULATION.md"
    )
    parameters_path = args.parameters_path or (project_root / "config" / "parameters.toml")

    try:
        verify_parameters_consistency(formulation_path, parameters_path)
        print("[OK] Parameters consistency check passed.")
        return 0
    except ParameterConsistencyError as e:
        print(f"[FAIL] Parameters consistency check failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(
            f"[FAIL] Unexpected error during consistency check: {e}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
