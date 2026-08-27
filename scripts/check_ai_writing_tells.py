"""Measure the documented AI-writing tells across the built article pages.

Checklist assembled 2026-08-27 from tropes.fyi, Pangram's pattern guide, Forbes
(Feb 2026), Grammarly's AI-word list and the Claude-specific writeups. Only
things that can actually be COUNTED are here - "sounds robotic" is not a metric,
sentence-length variance is.

The point is a BASELINE plus a comparison: the five pre-existing articles were
written the same way as the three new ones, so if a number is bad it is bad
across all eight and that is the honest reading.
"""
import re
import statistics
import sys
import pathlib

DOCS = pathlib.Path(__file__).resolve().parent.parent / 'docs'

def _slugs() -> list[str]:
    """Read the article list from the generator, so a new page is covered
    without anyone remembering to extend this file."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from guide_pages_content import PAGES
    return [p['slug'] for p in PAGES]


SLUGS = _slugs()

# ---- lexical tells -------------------------------------------------------
BANNED_WORDS = [
    'delve', 'tapestry', 'testament', 'paradigm', 'realm', 'landscape of',
    'at its core', 'in a world where', 'navigate the', 'unlock',
    'harness the', 'harnessing',
    'seamless', 'robust', 'leverage', 'crucial', 'pivotal', 'vital',
    'game-chang', 'cutting-edge', 'ever-evolving', 'holistic', 'myriad',
    'plethora', 'utilize', 'foster', 'underscore', 'multifaceted',
    'valuable insight', 'journey', 'aspect of', 'furthermore', 'moreover',
    'in conclusion', 'overall,', "it's worth noting", 'it is worth noting',
    "here's the kicker", 'the best part', "here's the thing",
    "let's break", 'think of it as', 'the truth is', 'that said,',
    'dive into', 'deep dive', 'when it comes to', 'the fact that',
]

# ---- structural tells ----------------------------------------------------
# The tell is CONTRASTIVE negation - "it's not X, it's Y" - where the two halves
# are juxtaposed with a comma or a dash and no conjunction joining them. An
# ordinary compound clause ("this is not rare and it is worth checking") is not
# the pattern, and the first version of these patterns matched three of those
# for every real hit. It also ran straight across full stops, pairing clauses
# from different sentences.
#
# So: no sentence-ending punctuation in the gap, no coordinating conjunction in
# the gap, and a comma or dash required before the second half. A checker that
# flags correct writing gets ignored, which costs more than the hits it catches.
_GAP = r'(?:(?!\band\b|\bor\b)[^.!?;])'
NEG_PARALLEL = [
    r'\bis not\b' + _GAP + r'{1,60}[,\-]\s*\bit is\b',
    r"\bisn't\b" + _GAP + r"{1,60}[,\-]\s*\bit's\b",
    r'\bnot\b' + _GAP + r'{0,40}\bbut\b',
    r'\bnot only\b' + _GAP + r'{1,60}\bbut also\b',
]
RHETORICAL_Q = r'[a-z,]\s+[A-Z][^.?!]{3,60}\?\s+[A-Z]'   # mid-paragraph self-question


# The generated pages wrap their prose in `<div class="art">`, NOT in an
# `<article>` element. The first version of this file searched for `<article>`,
# matched nothing on every page, and silently fell back to scanning the whole
# document - a guard reading a superset of what it claimed to read. It happened
# to survive because the shell contributes almost no `<p>` and because the FAQ
# truncation below removes the footer as a side effect, but "correct by
# accident" is not a property to leave in place. _body() raises rather than
# falling back, so a shell change fails loudly instead of quietly widening the
# scan.
def _body(html: str) -> str:
    i = html.index('<div class="art"')
    return html[i:]


def visible_text(html: str) -> str:
    t = re.sub(r'(?s)<script.*?</script>|<style.*?</style>', ' ', html)
    t = _body(t)
    t = re.sub(r'(?s)<div class="toc".*?</div>', ' ', t)
    # A TABLE IS NOT PROSE. Stripping tags runs the cells together, which
    # manufactured a "rhetorical question" out of the header cell "In a Files
    # zip?" followed by the next cell's capital.
    #
    # It does NOT affect the sentence statistics, and the first version of this
    # comment claimed it did - a prediction written as a measurement. Verified
    # after the change: short% moved on no article, because sentences() reads
    # paragraphs(), which extracts <p> elements only, and a table cell is never
    # in a <p>. What this line actually changes is the word count and the
    # regex-based counts that run over visible_text: lexicon, negation,
    # rhetorical questions, dashes, contractions.
    t = re.sub(r'(?s)<table.*?</table>', ' ', t)
    # The FAQ is a list of questions BY DESIGN, and it was supplying 7 of the 8
    # "rhetorical question" hits on every page - a metric that always fires is a
    # guard that cannot say no.
    t = re.sub(r'(?s)<section[^>]*id="faq".*', ' ', t)
    t = re.sub(r'(?s)<h2[^>]*id="faq".*', ' ', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = t.replace('&nbsp;', ' ').replace('&amp;', '&')
    t = re.sub(r'&[a-z]+;', ' ', t)
    return re.sub(r'[ \t]+', ' ', t)


def paragraphs(html: str) -> list[str]:
    src = _body(html)
    # The byline ("By BrkBuilds, who builds the app - Published ...") is
    # boilerplate the generator writes, not prose anyone chose the rhythm of.
    src = re.sub(r'(?s)<p class="byline".*?</p>', ' ', src)
    out = []
    for m in re.finditer(r'(?s)<p[^>]*>(.*?)</p>', src):
        p = re.sub(r'<[^>]+>', ' ', m.group(1))
        p = re.sub(r'&[a-z]+;', ' ', p)
        p = re.sub(r'\s+', ' ', p).strip()
        if len(p.split()) > 8:
            out.append(p)
    return out


def sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\u201c])', text)
    return [p.strip() for p in parts if len(p.split()) >= 3]


def report(slug: str) -> dict:
    html = (DOCS / slug).read_text(encoding='utf-8')
    text = visible_text(html)
    low = text.lower()
    paras = paragraphs(html)
    sents = [s for p in paras for s in sentences(p)]
    lens = [len(s.split()) for s in sents]
    plens = [len(p.split()) for p in paras]

    hits = {w: low.count(w) for w in BANNED_WORDS if low.count(w)}
    neg = sum(len(re.findall(p, text, re.I)) for p in NEG_PARALLEL)
    rq = len(re.findall(RHETORICAL_Q, text))
    contractions = len(re.findall(r"\b\w+(?:'|\u2019)(?:s|t|re|ve|ll|d|m)\b", text))

    # anaphora: three or more consecutive sentences opening with the same word
    ana = 0
    for i in range(len(sents) - 2):
        w = [s.split()[0].lower().strip(',') for s in sents[i:i + 3]]
        if w[0] == w[1] == w[2]:
            ana += 1

    # dash-as-em-dash: " - " used the way an em dash is used
    dashes = len(re.findall(r'\S \- \S', text))

    return dict(
        slug=slug,
        words=len(text.split()),
        sents=len(sents),
        sent_mean=round(statistics.mean(lens), 1) if lens else 0,
        sent_sd=round(statistics.pstdev(lens), 1) if len(lens) > 1 else 0,
        short_pct=round(100 * sum(1 for x in lens if x <= 8) / max(1, len(lens))),
        long_pct=round(100 * sum(1 for x in lens if x >= 35) / max(1, len(lens))),
        para_mean=round(statistics.mean(plens), 1) if plens else 0,
        para_sd=round(statistics.pstdev(plens), 1) if len(plens) > 1 else 0,
        contractions=contractions,
        contr_per_1k=round(1000 * contractions / max(1, len(text.split())), 1),
        dashes=dashes,
        dash_per_1k=round(1000 * dashes / max(1, len(text.split())), 1),
        neg_parallel=neg,
        rhetorical_q=rq,
        anaphora=ana,
        banned=hits,
    )


if __name__ == '__main__':
    rows = [report(s) for s in SLUGS]
    hdr = ('slug', 'words', 'sent_mean', 'sent_sd', 'short%', 'long%',
           'para_sd', 'contr/1k', 'dash/1k', 'neg', 'rhetQ', 'anaph')
    print('%-44s %5s %5s %5s %6s %5s %7s %8s %7s %4s %5s %5s' % hdr)
    for r in rows:
        print('%-44s %5d %5.1f %5.1f %5d%% %4d%% %7.1f %8.1f %7.1f %4d %5d %5d' % (
            r['slug'][:44], r['words'], r['sent_mean'], r['sent_sd'],
            r['short_pct'], r['long_pct'], r['para_sd'],
            r['contr_per_1k'], r['dash_per_1k'],
            r['neg_parallel'], r['rhetorical_q'], r['anaphora']))
    print()
    allb = {}
    for r in rows:
        for k, v in r['banned'].items():
            allb[k] = allb.get(k, 0) + v
    print('banned lexicon hits across all articles:',
          dict(sorted(allb.items(), key=lambda kv: -kv[1])) or 'NONE')
