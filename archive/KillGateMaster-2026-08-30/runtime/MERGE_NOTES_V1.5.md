# Killgate v1.5 Merge Notes

Date: 2026-08-27

## Incorporated from Grok patch

- Added `FEASIBILITY_REQUIRED` as a first-class research verdict.
- Added mechanism classification/scoreboard fields for CORE vs SUPPORTING mechanisms and KEEP / TEST / REMOVE_DEFER / CONTRADICTED actions.
- Added an explicit feasibility test contract for load-bearing technical capabilities.
- Added evaluator enforcement so a claimed `RESEARCH_PASS` cannot bypass an unresolved load-bearing CORE capability test.
- Added feasibility-result handling that keeps ordinary buyer/WTP validation locked until the capability test passes.
- Updated validation contract version to 1.5 and updated research/validation prompts.
- Updated CLI and web UI rendering for the new state.
- Updated the Android UI preview asset to demonstrate the v1.5 feasibility workflow.
- Preserved the complete Grok v1.5 reference snapshot under `docs/killgate-v1.5/`.

## Verification

- Core research + validation-contract tests: 47 passed.
- Full test suite excluding the environment-dependent Android SDK signature-tool test: 161 passed, 1 deselected.
- Python modules touched by the merge compile successfully.
- Final preview APK ZIP integrity and APK Signature Scheme v2 signature were independently verified.

## APK/runtime boundary

`Killgate-v1.5-PATCHED-UI-PREVIEW.apk` is the Android preview shell. The real research/evaluator behavior is implemented in this merged backend source and must be deployed to the production web/backend environment for the live app to use the v1.5 engine.

The original preview APK signing private key was not present in the supplied source, so the rebuilt preview is signed with a new key. Uninstall the previous `com.killgate.preview` preview APK before installing this one.
