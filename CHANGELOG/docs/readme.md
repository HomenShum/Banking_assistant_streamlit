# README history

> Surface: developer and coding-agent instructions for choosing and configuring the actual Streamlit application.
>
> Preserve prior entries and add one dated entry for each later documentation change.

## 2026-10-15 — Point first-run instructions at the existing application

Replace the placeholder clone URL and absent launch target with the actual repository and the quoted chatv3 filename selected by the devcontainer. Explain the Python3.11 source environment, system-package and Streamlit secret-name prerequisites, retained older script, actual processing call paths, unpinned legacy dependency limits, and the absence of a standalone LICENSE file.

Before: the original README fails the frozen external source-fidelity checker, including its clone and launch instructions. After: the corrected README is checked against the same six tracked source/configuration files; an old-README negative control must still fail. The evidence covers documentation, tracked paths and Python AST parsing without importing either app. It does not prove installation, startup, document processing, provider/model quality, UI appearance or production readiness.

Runtime scripts, requirements, packages and devcontainer are unchanged. No historical entries were reconstructed.

**Commit**: uncommitted candidate. **Author**: Codex.
**Touches**: [history index](../README.md), [entry template](../TEMPLATE.md).
