# Contributing

Thanks for wanting to help. Issues and pull requests are both welcome, and so is a bug report with
nothing but a good description in it.

## Ways to help that are not code

- **Report a bug.** The [bug report form](https://github.com/BrkBuilds/Canvas-Downloader/issues/new?template=bug_report.yml)
  asks for the things that actually make a bug findable: your OS, the app version, which mode you
  were in, and the exported error log.
- **Tell us your university uses Canvas and is missing from the picker.** The login screen lists
  4,757 verified institutions. If yours is absent, open an issue with the Canvas address you use and
  it can be added.
- **Improve the docs.** The website lives in `docs/` and is plain HTML.

## Setting up

Requires Python 3.11 or newer.

```bash
git clone https://github.com/BrkBuilds/Canvas-Downloader.git
cd Canvas-Downloader
pip install -r requirements.txt

python start.py          # run the packaged-style app (launcher plus desktop window)
streamlit run app.py     # run just the UI in a browser, which is easier to debug
```

You will need a Canvas access token from your own institution: **Account → Settings → Approved
Integrations → + New Access Token**.

## Running the tests

```bash
python -m pytest              # the whole suite, currently 3,827 tests
python -m pytest tests/test_folder_scope.py -x    # one file, fail fast
```

The suite must be green before a pull request is merged. It is fast enough to run often.

## The rules that are not obvious

`CLAUDE.md` in the repository root is the engineering logbook, and it is the most important file to
read before changing anything. It is long on purpose. Every entry records a real failure, the
measurement that found it, and why the obvious fix was wrong. Skim the section covering the area you
are touching and you will avoid re-introducing a bug that has already cost somebody a day.

A few rules come up constantly:

**Verify in the real app, not a mock.** A passing test proves the shape of the code. It does not
prove the screen works. Run `streamlit run app.py` and drive the actual screen before calling
anything done.

**A UI change is not finished until you have looked at it in a browser, before and after.** Most UI
defects in this project have been geometry: a container that does not grow, a gap that doubled, a
button 15px off centre. None of them are visible in a diff, and all of them are obvious in a
screenshot.

**No em-dashes or en-dashes in any user-facing text.** Use a spaced hyphen. This applies to the app,
the website and the README.

**Colours come from `shared/theme.py`.** Do not write a hex value that sits next to an existing one.
`scripts/verify_architecture.py` fails the build on any colour within 1.0 CIEDE2000 of a token and
tells you which token to use instead.

**Escape Canvas data.** Anything from Canvas that reaches HTML goes through `esc()` first, including
both halves of a value you split, such as a filename and its extension.

Run the architecture audit before you open a pull request:

```bash
python scripts/verify_architecture.py
```

It should report zero violations for rules 4 through 10.

## Pull requests

- Branch from `main`.
- Keep a pull request to one concern. Two unrelated fixes are two pull requests.
- Add or update tests. If you fixed a bug, the test should fail without your fix.
- Fill in the pull request template, especially the verification section.

If you are unsure whether an idea will be accepted, open an issue first and ask. That is cheaper for
both of us than a rejected pull request.

## Security

Please do not open a public issue for a security problem. See [SECURITY.md](SECURITY.md).

## Licensing of contributions

Canvas Downloader is licensed under the **GNU General Public License v3 or later** (see
[LICENSE](LICENSE)). By opening a pull request you agree that your contribution is offered under
that same license. There is no separate contributor licence agreement to sign.

You keep the copyright to what you write. In practice this means the project stays open source
permanently: nobody, including the maintainer, can take a contribution closed source later without
asking every contributor first.

## Code of conduct

Be decent to people. The full text is in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
