---
name: looop-pm-research-core
description: Answer one decision-relevant question with attributable current evidence, then stop.
license: MIT
---

# research-core

Name the single decision this research informs and the exact question that would change it. State a stop condition before reading anything: which sources would settle it, what counts as an answer and how much effort is proportionate. Research that cannot change a decision is not run.

Keep two evidence classes separate and never merge them:

- **Current state**: what the project's code, tests, configuration and state actually show. Cite the file path and an exact quotation copied from the bytes you read.
- **Public evidence**: what an external, publicly reachable source currently says. Cite a full URL and an exact quotation that appears verbatim in the retrieved page.

Every factual claim carries its own attributable source. A page you did not open is not evidence; a search summary, marketing claim or recollection is not a source. Record retrieval failures as gaps instead of paraphrasing them into plausibility.

Actively look for counterevidence: alternatives that would make the answer wrong, existing behavior that already satisfies the need, contradicting sources and missing signals. Write down what you found and what you could not check. Agreement between sources is not proof; the number of sources is not a threshold.

Close with exactly one conclusion:

- `supported` — the named question is answered by the recorded sources.
- `rejected` — the evidence contradicts the premise, or an alternative is better supported.
- `insufficient_evidence` — a named gap remains, with the specific missing source or observation.

Missing evidence is recorded as a gap and stops there. Never fill it with assumption, an invented citation or a synthetic result presented as real; a partial answer stays partial.

Stay inside project authority. Research may read what the project permits and retrieve public pages read-only. It never expands scope, adds providers, services or dependencies, approves a requirement, or authorizes implementation. The conclusion is input to a decision the project owns.

Keep output bounded: the question and stop condition, the two evidence classes, counterevidence, the conclusion and the gaps. Return it through the caller's existing state mechanism. Do not create a standalone report, a document tree or a growing research diary.
