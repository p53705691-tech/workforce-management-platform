---
paths:
  - "app/**/*.py"
  - "tests/**/*.py"
  - "static/**/*.js"
---

# Code Quality Rules

Write code for humans first.

Prefer:

- clear names
- small functions
- focused modules
- explicit control flow
- consistent formatting
- simple abstractions

Avoid:

- clever one-liners
- unnecessary nesting
- magic numbers
- unexplained constants
- duplicated logic
- dead code
- premature abstractions
- excessively long functions
- unnecessary comments

Comments should explain:

- why something exists
- a non-obvious business rule
- a security decision
- a tricky edge case

Do not use comments to compensate for unclear code.

Prefer descriptive names over comments.

Follow the project's formatter and linter configuration.

Before finishing a change, ask:

"Would another developer understand this code quickly?"

If not, simplify it.
