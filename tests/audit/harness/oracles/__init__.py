"""The five independent views of one truth.

    O1  ui      what the app TELLS the user          (harness/browser.py + probe.py)
    O2  log     what the app SAYS IT DID             (oracles/log.py)
    O3  disk    what ACTUALLY EXISTS                 (oracles/disk.py)
    O4  db      what the app BELIEVES exists         (oracles/db.py)
    O5  canvas  what SHOULD exist                    (oracles/canvas.py)

The point of five rather than three is that O1, O2 and O3 are all downstream of
the app's own discovery. If discovery misses a file, all three agree and all
three are wrong: the UI says 234, the log says 234 saved, the disk holds 234.
O5 is the only view computed outside the application, and O4 is the only view of
the app's internal model - which is where "silently up to date forever" bugs
live, since a manifest row pointing at a path that moved is invisible to the
other four.
"""
