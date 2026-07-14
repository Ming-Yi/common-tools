# Release procedure

1. Ensure the worktree contains only the intended release changes.
2. Run Ruff, Pyright, the full test suite, and `uv build`.
3. Commit the release changes.
4. Create an annotated SemVer tag on that commit, for example:

   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0"
   ```

5. Build again from the tagged commit and confirm the wheel version is `0.2.0`.
6. Push the commit and tag only after review:

   ```bash
   git push origin main
   git push origin v0.2.0
   ```

Never move or reuse a published tag. Production consumers pin the immutable tag.
