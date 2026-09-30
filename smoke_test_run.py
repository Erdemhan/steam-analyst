"""Manual smoke test: run the real pipeline end-to-end against live APIs.

Deliberately narrows the coarse filter in-memory (NOT touching the real
config/parameters.toml or FORMULATION.md) to a tiny candidate set so this
finishes in a couple of minutes instead of hours. Not a permanent script --
for one-off manual verification only.
"""
import dataclasses
import sys
import traceback
from pathlib import Path

sys.path.insert(0, "src")

from steam_analyst import config, orchestration, storage


def main() -> int:
    db_path = Path("data/analyses.db")
    settings = config.load_settings()
    parameters_version = config.parameters_version(settings.parameters_path)
    acquisition_config, enrichment_params, analysis_params = config.load_parameters(
        settings.parameters_path
    )

    # Smoke-test-only override: raise the review floor drastically so only a
    # handful of blockbuster titles survive the coarse filter, keeping this
    # run's per-app fetch count small. This does NOT touch the real locked
    # config/parameters.toml -- it is a local, in-memory copy for this script.
    narrow_coarse_filter = dataclasses.replace(
        acquisition_config.coarse_filter,
        min_review_count=200_000,
    )
    smoke_acquisition_config = dataclasses.replace(
        acquisition_config,
        coarse_filter=narrow_coarse_filter,
    )

    pipeline_config = orchestration.PipelineConfig(
        max_catalog_pages=1,
        notes="smoke test run (manual, narrowed coarse filter)",
    )

    with storage.connect(db_path) as conn:
        storage.initialize_schema(conn)
        run_id = storage.create_run(
            conn,
            config=pipeline_config.to_dict(),
            parameters_version=parameters_version,
            trigger_type="manual",
            notes=pipeline_config.notes,
        )
        print(f"Created run: {run_id}", flush=True)

    # run_pipeline itself calls config.load_parameters internally using
    # settings.parameters_path, which would give it the REAL (unnarrowed)
    # acquisition_config. To exercise the narrowed coarse filter for this
    # quick smoke test, monkeypatch load_parameters for the duration of this
    # call so run_pipeline picks up the narrowed AcquisitionConfig.
    import steam_analyst.orchestration.pipeline as orch_pipeline_module

    original_load_parameters = orch_pipeline_module.load_parameters

    def patched_load_parameters(path):
        return smoke_acquisition_config, enrichment_params, analysis_params

    orch_pipeline_module.load_parameters = patched_load_parameters

    try:
        with storage.connect(db_path) as conn:
            result = orchestration.run_pipeline(
                conn, run_id, pipeline_config, settings=settings
            )
        print(f"\nRESULT: status={result.status}", flush=True)
        print(f"  stages_run={result.stages_run}", flush=True)
        print(f"  duration_seconds={result.duration_seconds:.2f}", flush=True)
        print(f"  error_message={result.error_message}", flush=True)
        if result.acquisition:
            print(f"  acquisition: {result.acquisition}", flush=True)
        if result.enrichment:
            print(f"  enrichment: {result.enrichment}", flush=True)
        if result.analysis:
            print(f"  analysis: {result.analysis}", flush=True)
        return 0 if result.status == "succeeded" else 1
    except Exception:
        print("\nEXCEPTION during run_pipeline:", flush=True)
        traceback.print_exc()
        return 1
    finally:
        orch_pipeline_module.load_parameters = original_load_parameters
        print(f"\nrun_id = {run_id}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
