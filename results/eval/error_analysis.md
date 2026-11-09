# Error analysis (eval, 300 questions, frozen prompts)

Every question that at least one version got wrong (123 questions) was re-run (gold SQL and predicted SQL) and
read by hand: question, hint, gold SQL, predicted SQL and both results. Each got one root-cause category, stored in
the `error_category` and `error_note` columns of [failures.csv](failures.csv).

**Caveat:** the categories are our judgment from reading each case. "Answer key questionable" means our answer is a
defensible reading of the question **and** the gold SQL is buggy, ignores part of the question or reads it oddly.
It does not mean the official score is wrong to count them as misses; we report official EX everywhere.

## What kind of mistakes does the model make?

Counted over the **115** questions *Guess once* got wrong. The first attempt is shared by all three versions, so
this is the model's "natural" error profile.

| Group | Count | Share |
|---|---:|---:|
| **A. Real mistake:** the model misunderstood the question or the data | 30 | 26% |
| **B. Right idea, wrong shape:** basically the right answer, marked wrong by strict scoring | 22 | 19% |
| **C. Answer key questionable:** our answer is defensible, the gold answer is not | 63 | 55% |

| Group | Category | Count | Plain English |
|---|---|---:|---|
| A | `schema-linking` | 10 | Used the wrong table or column (e.g. per-race results instead of championship standings) |
| A | `aggregation` | 6 | Wrong counting/grouping logic (e.g. all races of the first season instead of the first race) |
| A | `value-spelling` | 5 | A value written differently from the data (`'2019-8-20'` vs `'2019-08-20'`, `'human'` vs `'Human'`) |
| A | `hint-ignored` | 3 | Did not use the formula the hint gives |
| A | `join` | 2 | Joined tables in a way that adds or drops rows |
| A | `filter-wrong`, `missing-columns`, `null-handling`, `exec-error` | 1 each | |
| B | `extra-columns` | 4 | Returned a column the question did not ask for |
| B | `ties` | 4 | Several rows tie for "the highest"; we return all, gold arbitrarily picks one |
| B | `name-concatenated` | 3 | "Sebastian Vettel" in one column; gold wants first and last name as two columns |
| B | `column-order` | 3 | Right columns, different order (BIRD compares rows as ordered tuples) |
| B | `value-format` | 3 | e.g. answered `0` where gold expects `'NO'` |
| B | `wrong-output-column` | 3 | Returned card names where gold returns card ids |
| B | `float-precision` | 2 | Correct, but differs in the 15th decimal place |
| C | `gold-questionable` | 63 | See below |

By difficulty: of the misses on **simple** questions, 6 of 19 are real mistakes; on **moderate** 20 of 68; on
**challenging** 4 of 28. Most misses on harder questions are group C.

**Common reasons in group C:**
- **Gold counts rows, not things (11 cases).** "How many patients…" where gold counts every lab-test row, so a
  patient with 10 tests counts 10 times. The model counts distinct patients.
- **Gold drops columns the question asks for** (e.g. "Which group is larger, and by how much?" but gold returns
  only the number), or adds ones it doesn't.
- **Bugs in the gold SQL** (e.g. qid 234 and 1247: `a AND b OR c` without brackets; qid 1107 asks for the *first*
  date but gold sorts descending; qid 1029 asks for the *highest* but gold sorts ascending).
- **Wrong or misleading hints** that the model followed literally (e.g. qid 244: the hint has `' = '` with spaces;
  qid 1171: "underage refers to year(Birthday) < 18").

If group C were counted as correct, *Guess once* would score about **83%** instead of 61.7% (about 90% with group B
as well). This is our estimate, for the discussion only.

## What did retrying and self-checking change?

| Step | Fixed | Broke | Net |
|---|---:|---:|---:|
| Guess once → Try again if it crashes | 1 | 0 | +1 |
| Try again → Double-check the answer | 5 | 8 | −3 |

**Retry** can only act when the query fails to run. That happened on just 3 of 300 first attempts (all timeouts).
Retry got all 3 running and 1 right:

> **qid 685:** "Identify the total views on the post 'Computer Game Datasets'. Name the user who posted it last time."
> The first query joined the post-history table to itself and **timed out**. Retry was shown "query timed out" and
> rewrote it with a small subquery. It ran and matched the gold answer.

**Self-check fixed 5**, and 4 of the 5 fixes started from an **empty result** (the 5th, qid 915, from NULL birth
dates sorting first):

> **qid 581:** "Who is the owner of the post titled 'Open source tools for visualizing multi-dimensional data?'"
> The first query dropped the `?` from the title, so it returned **0 rows**. Self-check saw "Warning: the result is
> EMPTY", put the `?` back, got "Paul", and answered OK.

Others: qid 563 (copied the hint's date format `2014/4/23`; the data uses `2014-04-23`), qid 98 and 173 (wrong
filter or table → empty → repaired).

**Self-check broke 8** correct answers by "improving" them:

> **qid 945:** "How many circuits are there in Adelaide, Australia?" The first answer (location = 'Adelaide') was
> right. The hint oddly says "Melbourne is the location of circuit"; on the second look the model switched to
> Melbourne and answered 0.

> **qid 100:** "How many female customers born before 1950 stayed in Sokolov?" The first answer (8) was right.
> Self-check added an extra condition (account owners only) that the question never asked for, giving 7.

Other breaks: adding `atom_id < atom_id2` to "remove duplicates" (248), switching to the wrong table (483, 683),
switching to a different join (215), counting distinct players instead of rows (1037), extra columns (83).

**Takeaway:** self-checking helps only when the answer is **visibly broken** (empty result, NULLs). When the answer
looks plausible, a second look at the same evidence is as likely to talk the model out of a right answer as into
one. With this model the SQL almost never crashes (3/300), so "Try again if it crashes" rarely has anything to do.

## Limitations of our own prompt

- The prompt rule "follow the hint exactly" (added during pilot tuning) can backfire because some BIRD hints are
  wrong: 21 of the 115 misses involve the hint (e.g. qid 758 hint `'human'` vs data `'Human'`; qid 1239 hint says
  "> 2" where the question says "two or more"; qid 352 hint says `Sum(id)`).
- The rule "use INNER JOIN unless asked otherwise" lost qid 27, where gold keeps schools without SAT scores.
- These rules were tuned on 30 pilot questions only and frozen before the eval, so the eval numbers are unbiased;
  the rules may simply not generalise perfectly.
