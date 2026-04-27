---
name: conventional-gitmoji-commit
description: A commit style that combines conventional commits with gitmoji. Use when you're writing a git commit message, or you're asked to use this skill.
---

# conventional-gitmoji-commit

When you're writing a git commit message, you'd be familiar with the conventional-gitmoji-commit style:

```plaintext
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Conventional-gitmoji-commit is "compatible" with the conventional commit style, but it also incorporates gitmoji to make commit messages more visually appealing and easier to understand at a glance. The format is:

```plaintext
<type>[optional scope]: <gitmoji> <description>

[optional body]

[optional footer(s)]
```

For example:

```plaintext
feat: ✨ Add new user authentication flow
```

## When to use

When you're writing a git commit message, or you're asked to use this skill.

## Instructions

(RFC 2119 keywords)

1. MUST check the descriptions in ./gitmoji.yaml.
2. RECOMMENDED to check the descriptions in ./conventional-commit.yaml.
3. MUST choose a type from the conventional-commit types and an appropriate gitmoji.
4. MAY view the last 5 commit message for reference.
5. MUST write the commit message in English, whatever the historical commit messages are.
6. If you're asked to use this skill, you MUST commit your changes with this style.
7. Changes of different types SHOULD be separated in different commits.
