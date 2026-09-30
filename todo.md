# TODO

Items recorded for later. None of these are started.

## 1. Make the complexity weights user-adjustable

- Allow the complexity score weights (FORMULATION §4, `enrichment.complexity_weights.*`) to be overridden by the user at run time.
- When the user does not override them, the frozen defaults from `config/parameters.toml` must be used unchanged.
- Open points to settle before implementation:
  - Where the override is supplied (run configuration, UI form, or a separate TOML file).
  - Validation: overridden weights must still sum to 1.00 (or be renormalized, which needs a decision).
  - Whether the overridden weights are stored with the run so that results remain reproducible.
  - FORMULATION.md is user-locked, so the defaults stay there and overrides must not modify it.

## 2. Archetype labels are ambiguous

- Observed on a 1000-game scan: an archetype reported as "Action, Multiplayer, Singleplayer" is unclear.
  It is not evident whether it means single-player only, multiplayer only, or games that support both.
- If the label means "both", it is unclear how contradictory tags can legitimately co-occur in one archetype.
  If it does not, the clustering puts contradictory tags into the same group, which would be a clustering problem.
- To investigate:
  - How cluster labels are derived from tags (which tags are shown, and on what criterion).
  - Whether mode tags (Singleplayer, Multiplayer, Co-op, etc.) should be separated from genre/mechanic tags
    in the distance measure and in the displayed label.
  - Whether the label should state explicitly how many member games carry each tag (for example, share of members per tag).
- Any change to tag distance or clustering affects FORMULATION §6 and needs user approval.
