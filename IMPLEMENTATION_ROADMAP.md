# SentiStream Implementation Roadmap

Track implementation work here. Check an item only after its code and documentation are in place; add important architecture and code choices to [DECISIONS.md](DECISIONS.md) in the same change.

## Completed

- [x] Prepare the hosted-demo foundation: full-stack Compose deployment, same-origin frontend routing, production write protections, health reporting, runtime image split, and deployment documentation. Commit: `89fbd38`.
- [ ] Repair the production dependency security gate: remove Transformers from the serving image, load the exported tokenizer artifact directly, upgrade vulnerable runtime dependencies, and confirm a clean CI audit.

## Next implementations

- [ ] Make stream processing resilient: retry transient failures, reclaim abandoned Redis pending entries, and expose queue age, retry, and dead-letter counts.
- [ ] Add trustworthy portfolio analytics: periodic equity/holdings snapshots, realized and unrealized P&L, drawdown, and benchmark-relative performance with clear sample-size and data-quality context.
- [ ] Make model comparisons real: give each registry slot an independently versioned artifact, add a labeled evaluation set, and report accuracy/F1/calibration before enabling any traffic experiment.
- [ ] Improve news data quality: persist source identity and publication timestamps, deduplicate syndicated headlines, and show freshness/coverage by ticker and feed.
- [ ] Complete hosted deployment: choose a host and domain, provision secrets and model artifacts, deploy the Compose stack, and verify the public health and websocket routes.
- [ ] Review and secure the ML build toolchain: migrate from the current Transformers 4-only ONNX exporter, then audit the training/export dependencies separately from production runtime.
