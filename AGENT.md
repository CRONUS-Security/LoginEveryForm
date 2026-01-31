# AGENTS.md

## Code Styles

1. Code Style Requirements:
    - All comments and strings must be in English only.
    - No non-ASCII characters are allowed in the codebase. This includes comments, strings, filenames, documentation, and any text content.
    - Remove any emoji or non-Latin script from source files and documentation before commit.

2. HTTP Request Policy:
    - Use POST for all HTTP requests whenever possible.
    - GET requests are allowed only for safe, read-only retrievals such as static files or public assets.
    - Endpoints should accept POST and validate input, authentication, and CSRF protections as appropriate.

3. Authentication Requirements:
    - The system requires the "AuthToken" cookie for access authorization.
    - Missing or invalid "AuthToken" must trigger automatic redirection to the login endpoint.

4. Enforcement and Validation:
    - Code reviews, linters, and CI checks must enforce English-only and ASCII-only rules.
    - Any file that contains non-ASCII characters or non-English text must be fixed before merging.
