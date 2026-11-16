# Human labelling rubric

Automated metrics cannot fully capture "useful". This rubric is written **before**
labelling (not after) so the judgment stays consistent. Hand-label 150–200 posted
comments against it. If a second person labels 50 independently, report inter-rater
agreement.

## The three labels

Judge each **posted inline comment** as exactly one of:

### `useful`
A competent engineer, seeing this comment on their own PR, would either make a change
or seriously consider one. It identifies a concrete defect, risk, or correctness issue
in code the PR added, and points to specific evidence.

Examples:
- "This loop runs `range(len(x) + 1)`, so the last iteration indexes past the end."
- "`token == expected` is not constant-time; use `hmac.compare_digest`."
- "`user` can be `None` here (see `get_user` returning `None` on miss); `.name` will raise."

### `harmless`
Not wrong, but not worth the author's attention. Technically accurate yet trivial,
redundant with a linter, or so low-impact that a reviewer would not have raised it.
It does not damage trust, but it does not earn its place.

Examples:
- "Consider adding a docstring to this function."
- "This variable could be named more descriptively."
- A correct but utterly minor observation the author already knows.

### `noise`
Actively bad: wrong, speculative, based on code the model could not see, a restatement
of what the code obviously does, or a style/preference opinion dressed up as a defect.
These are the comments that get a bot uninstalled.

Examples:
- A claim the code "may leak memory" with no evidence and no leak present.
- "This might not handle unicode" on code that demonstrably does.
- "You should extract this into a helper" (preference, not a defect).

## Procedure

1. Label without looking at the model's confidence score first; then record it, to
   study calibration separately.
2. When torn between two labels, pick the **worse** one. A reviewer's benefit of the
   doubt is exactly what the precision filter is meant to not rely on.
3. Re-label 20 comments from the start of the batch at the end and check your own
   consistency. Report the self-agreement rate.

## Reporting

- `useful %`, `harmless %`, `noise %` of all posted comments.
- The flagship number stays **false positives per clean PR** (every comment on a clean
  PR is at best harmless and usually noise).
- If a second labeller participated, Cohen's κ or raw agreement on the shared 50.
