# ADR 0002: Evidence-first book-data acquisition

- Status: Proposed
- Date: 2026-10-17

## Context

The product is useful only if recommendations refer to real novels and claims
can be checked. Target platforms expose different metadata and may restrict
automated access. Search snippets and LLM memory are not reliable catalogues.

## Decision

Every candidate must contain one or more provenance records. A recommendation
may be displayed only when it has a resolvable source URL and passes evidence
validation. Provider adapters must document access authorization and supported
fields. Official/licensed sources are preferred; unauthorized scraping and
access-control bypasses are out of scope.

Separate three classes of information:

1. source-asserted metadata (for example author or completion status);
2. derived metadata (for example normalized genre labels);
3. model inference (for example a thematic match), always labeled and linked to
   the evidence used.

## Consequences

- Platform coverage may be narrower at beta, but claims will be more trustworthy.
- The data model needs field-level provenance, retrieval timestamps, and evidence
  quality indicators.
- Adapters can be disabled independently when permission, quality, or reliability
  changes.
- The first milestone must validate data access before UI scope expands.

