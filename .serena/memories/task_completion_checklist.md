# Task Completion Checklist

When a coding task is complete, do the following before declaring done:

1. **Run the test suite**
   ```bash
   uv run pytest
   ```
   All non-real tests must pass. If you added new code, add corresponding tests.

2. **Check for type errors** (if pyright/mypy is available)
   ```bash
   uv run pyright agentcouncil/   # optional, not configured in pyproject.toml
   ```

3. **Verify imports and __all__**
   - New public symbols should be added to `__all__` in their module.
   - No unused imports left behind.

4. **Check git status**
   ```bash
   git status
   git diff
   ```
   Confirm only intended files are modified.

5. **Commit** (when asked by user)
   - Use concise commit messages focused on WHY, not what.
   - Never add "Co-Authored-By" trailer lines.
   - Verify git author is "Kiran Krishna" before committing.

6. **Sync skill files** if skills were modified
   - `.claude/skills/<protocol>/SKILL.md` → `skills/<protocol>/SKILL.md`
   - The allowed copy commands are pre-approved in settings.local.json.
