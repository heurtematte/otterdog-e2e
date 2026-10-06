"""Deterministic helpers of AI-assisted test writing (``otterdog-e2e assist``, docs/ai-assistance.md).

The harness never calls an AI: agents (driven by the skills of ``.claude/skills/``) read the context bundles these
commands write and get their work validated by them. Everything that needs no judgement is done here: gathering
context (pr_context, triage, coverage), pre-classifying failures (triage) and validating what an agent wrote (check).

Bundles are written below ``<artifacts root>/assist/`` (bundle.write_bundle: private directories, files 0600, replaced
atomically, every text redacted); text taken from a pull request or from otterdog's output is untrusted data and is
always fenced (bundle.untrusted_block), never presented as instructions.
"""
