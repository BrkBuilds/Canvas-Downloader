Run the Canvas Downloader architecture verification script and report all violations.

Execute this command:
```
python scripts/verify_architecture.py
```

After running, summarize:
1. How many violations were found per rule
2. Which files are most affected
3. Any [COMPAT_FALLBACK?] or [THEME_CONST?] annotated items that need a human decision
4. Suggested fix for each active violation
