"""Measure the documented AI-writing tells across every page of docs/.

Checklist assembled 2026-08-27 from tropes.fyi, Pangram's pattern guide, Forbes
(Feb 2026), Grammarly's AI-word list and the Claude-specific writeups, then
widened 2026-09-02 to the whole of `marketing/anti-slop-field-manual.md`. Only
things that can actually be COUNTED are here - "sounds robotic" is not a metric,
sentence-length variance is.

The point is a BASELINE plus a comparison: if a number is bad it is usually bad
across every page, and that is the honest reading.

Two things changed 2026-09-02 and both widen what the guard can see:

* It reads `<main>`, so it covers ALL 26 pages rather than the 13 that carry an
  author box. The homepage, the two product guides and the legal pages were
  never scanned, and the homepage turned out to hold more tells than any
  article. `<main>` also picks up the hero `<h1>` and its standfirst, which
  `<div class="art">` cut off - the first two lines a reader sees.
* The lexicon matches on WORD BOUNDARIES. `low.count('unlock')` fired on "a
  module that unlocks later"; that false positive was known and left in place,
  and it is now simply gone.

Run:  python scripts/check_ai_writing_tells.py            # the table
      python scripts/check_ai_writing_tells.py --detail   # every hit, quoted
      python scripts/check_ai_writing_tells.py --control  # prove it says both
"""
import re
import sys
import html as _html
import statistics
import pathlib

DOCS = pathlib.Path(__file__).resolve().parent.parent / 'docs'

# The URL directory is 4,757 rows of generated table and no prose at all.
SKIP = {'canvas-url-directory.html'}


def _slugs() -> list[str]:
    """Every page with a `<main>`, which is every page that has prose.

    This used to read the article list from the generator that rebuilt the
    articles. That generator was deleted 2026-08-31 (an article is a document,
    not a build artifact); the marker then became the author box, which covered
    the 13 articles and none of the marketing or product pages. A page a reader
    can land on is a page whose prose counts, so the marker is now `<main>`.
    """
    out = []
    for p in sorted(DOCS.glob('*.html')):
        if p.name in SKIP:
            continue
        if '<main' in p.read_text(encoding='utf-8'):
            out.append(p.name)
    return out


SLUGS = _slugs()

# Pages that are an article: they carry the author box and the shared shell, so
# their sentence statistics are comparable with each other. The marketing and
# product pages are mostly headings, buttons and short blocks, so their
# sentence numbers mean less and their LEXICON numbers mean more.
ARTICLES = [s for s in SLUGS
            if 'class="author-box"' in (DOCS / s).read_text(encoding='utf-8')]


# ---- lexical tells -------------------------------------------------------
# Tiers are from the field manual. Tier 1 is "kill on sight"; tier 2 convicts
# only in clusters; tier 3 is a light signal that matters when it piles up.
# A phrase containing a space is matched literally; a bare word gets \b...\b,
# so "unlock" no longer fires on "unlocks later" the way substring counting did.
# `underscore` is a CHARACTER on this site: both product pages explain that a
# dot in a filename "becomes an underscore". The tell is the VERB, which always
# takes an object, so only that form is listed - see UNDERSCORE_VERB below.
TIER1 = [
    'delve', 'delve into', 'leverage', 'utilize', 'facilitate',
    'tapestry', 'testament', 'realm', 'myriad',
    'plethora', 'paradigm', 'multifaceted', 'encompass', 'encompasses',
    'embark', 'endeavor', 'holistic', 'synergy', 'spearhead', 'galvanize',
    'elucidate', 'epitomize', 'catalyze', 'juxtapose',
]
TIER2 = [
    'robust', 'seamless', 'seamlessly', 'comprehensive', 'streamline',
    'streamlined', 'empower', 'empowers', 'foster', 'cultivate', 'enhance',
    'enhanced', 'elevate', 'pivotal', 'intricate',
    'cutting-edge', 'groundbreaking', 'game-changer', 'game-changing',
    'transformative', 'unleash', 'bespoke', 'bolster', 'cornerstone',
    'meticulous', 'meticulously', 'versatile',
]
# Three words this site uses in their literal, domain sense, so a bare match on
# them is noise rather than a finding. Measured before removing them: 8 hits,
# 8 false positives.
#   `unlock`     - Canvas MODULE locking. "a module that unlocks later",
#                  "students cannot unlock Privacy & Security".
#   `harness`    - the audit HARNESS, a test rig, named 5 times on one page.
#   `underscore` - the character `_`.
# The marketing senses are still caught: HERO_VERB has "unlock your ...", and
# the two verb patterns below need a following object.
UNDERSCORE_VERB = (r'\bunderscor(?:e|es|ed|ing)\s+'
                   r'(?:the|a|an|its|their|his|her|our|how|why|that)\b')
HARNESS_VERB = r'\bharness(?:es|ed|ing)?\s+(?:the|its|your|their|this|that)\b'
TIER3 = [
    'crucial', 'essential', 'vital', 'paramount', 'remarkable', 'exceptional',
    'furthermore', 'moreover', 'additionally', 'consequently', 'nevertheless',
    'ultimately', 'arguably', 'foundational', 'vibrant', 'compelling',
    'unprecedented', 'ever-evolving', 'effortlessly', 'simply put',
]
# These pairs signal empty text almost on their own; the sentence around one
# usually needs rewriting rather than the phrase swapping.
COLLOCATIONS = [
    'robust framework', 'seamless integration', 'multifaceted approach',
    'digital landscape', 'ever-evolving landscape', 'holistic approach',
    'paradigm shift', 'meaningful results', 'continuous improvement',
    'rich cultural heritage', 'key driver', 'landscape of', 'at its core',
    'valuable insight', 'a thing of the past', 'the modern era',
]
OPENERS = [
    "in today's fast-paced", "in today's digital age", "in today's world",
    "let's dive into", "let's dive in", "dive into", "deep dive",
    "when it comes to", 'picture this', 'imagine this', 'imagine a world',
    "let's break", "let's unpack", 'think of it as', 'think of it like',
    'the truth is', "here's the thing", "here's the kicker",
    'the best part', 'in a world where', 'that said,', 'the fact that',
    'aspect of', 'journey',
]
LEXICON = {'t1': TIER1, 't2': TIER2, 't3': TIER3,
           'colloc': COLLOCATIONS, 'opener': OPENERS}


def _lex_re(term: str) -> re.Pattern:
    """Word-boundary match for a single word, literal match for a phrase.

    `\\b` after a term ending in a non-word character (`cutting-edge`) never
    matches, so the boundary is only applied where it can fire.
    """
    pat = re.escape(term)
    if re.match(r'\w', term[0]):
        pat = r'\b' + pat
    if re.search(r'\w$', term):
        pat = pat + r'\b'
    return re.compile(pat, re.I)


LEX_RE = {tier: [(t, _lex_re(t)) for t in terms] for tier, terms in LEXICON.items()}


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
# A closing bracket ends the construction too: "(you asked for a PDF, not
# both), but it is worth knowing" is two clauses either side of a parenthesis
# rather than a contrastive pair, and it was the one false positive left in
# this pattern after the 2026-08-29 tightening.
_GAP = r'(?:(?!\band\b|\bor\b)[^.!?;()])'
NEG_PARALLEL = [
    r'\bis not\b' + _GAP + r'{1,60}[,\-]\s*\bit is\b',
    r"\bisn't\b" + _GAP + r"{1,60}[,\-]\s*\bit's\b",
    r'\bnot\b' + _GAP + r'{0,40}\bbut\b',
    r'\bnot only\b' + _GAP + r'{1,60}\bbut also\b',
    # The four forms the field manual names. "not just X, Y" and "more than
    # just X, Y" are the two this site actually produced.
    r"\bnot just\b" + _GAP + r'{1,60}[,\-]\s*\b(?:it|they|this|that)\b',
    r'\bmore than (?:just )?(?:a|an|another)\b' + _GAP + r'{1,60}[,\-]',
    r"\b(?:isn't|is not) (?:simply|merely|just)\b" + _GAP + r'{1,60}[.,\-]',
]
RHETORICAL_Q = r'[a-z,]\s+[A-Z][^.?!]{3,60}\?\s+[A-Z]'   # mid-paragraph self-question

# A present participle hung off a comma at the END of a sentence: the field
# manual's "participial tail", called there the single most reliable machine
# giveaway in expository prose. Restricted to the SUMMARY verbs, because
# "He left, carrying the box" is an ordinary sentence and only the analysis
# verbs are the tic. The generic version of this pattern was tried first and
# matched four legitimate sentences for every real hit.
PARTICIPIAL_TAIL = (
    r',\s+(?:under(?:scor|lin)ing|ensuring|highlighting|marking|setting the '
    r'stage|cementing|solidifying|reflecting|allowing|making it|creating|'
    r'providing|offering|contributing|demonstrating|showcasing|emphasi[sz]ing|'
    r'reinforcing|paving|giving|helping to|serving as|leaving you|ushering)\b'
    r'[^.!?]*[.!?]'
)

# Significance inflation: the plain verb "is" swapped for something momentous.
# `represent` and `mark` both have ordinary literal senses this site uses -
# "if you represent an institution", "mark a missing file as present" - and
# both were false positives on the first run. The INFLATION is in the adjective
# that follows, so the pattern now requires one.
_BIG = (r'(?:major|significant|key|new|fundamental|critical|pivotal|important|'
        r'real|profound|dramatic|turning|watershed|milestone|defining)')
SIGNIFICANCE = (
    r'\b(?:serves? as|stands? as'
    r'|represents? (?:a|an|the) ' + _BIG +
    r'|marks? (?:a|an|the) ' + _BIG +
    r'|plays? (?:a|an) (?:pivotal|key|crucial|central|vital|major|important) '
    r'role|is a testament|speaks? volumes)\b'
)
# Signposting filler: announces importance, adds none. Cut it and the sentence
# is unharmed, which is the tell.
SIGNPOST = (
    r"\b(?:it(?:'s| is) (?:worth|important) (?:noting|to note)|it should be "
    r'noted|needless to say|importantly,|notably,|interestingly,|'
    r'as (?:we(?:\'ve| have) seen|mentioned (?:earlier|above))|'
    r'to (?:answer your question|circle back))'
)
# Authority with no name, source or number.
VAGUE_AUTHORITY = (
    r'\b(?:studies (?:have )?(?:show|shown|suggest)|research (?:shows|suggests|'
    r'indicates)|experts? (?:agree|say|note)|many (?:believe|argue|say)|'
    r'it is widely (?:believed|known|accepted)|industry observers)\b'
)
# Marketing warmth. `ultimate` and `all-in-one` are the two this site shipped.
PROMOTIONAL = (
    r'\b(?:the ultimate|all-in-one|endless possibilities|breathtaking|'
    r'unforgettable|world-class|best-in-class|revolutionary|state of the art|'
    r'state-of-the-art|second to none|look no further|supercharge|'
    r'take (?:your|it) .{1,20} to the next level)\b'
)
# Fortune-cookie closure, and the closing line that reframes the piece as a Big
# Question.
APHORISM = (
    r'\b(?:at the end of the day|in the end,|one thing is clear|'
    r'time will tell|the real question|the journey matters|'
    r'change is the only constant|when all is said and done)\b'
)
# Answer-shaped preamble: describing what the answer will do instead of giving
# it.
# The tell is ANNOUNCE-THEN-DELAY: "There are a few things to consider. Let's
# break them down one by one." A sentence that announces a count and then
# supplies the items after a colon has already answered, so it is an ordinary
# enumeration - `canvas-download-tools-compared.html`'s "There are three ways to
# get a Canvas course onto your computer without doing it by hand: a browser
# extension, a script, or a desktop app" is that article's whole spine, not a
# stall. The count branch therefore requires NO colon before the sentence ends.
PREAMBLE = (
    r'\b(?:there are (?:a few|several|many|three|four|five) (?:things|factors|'
    r'reasons|ways|options)(?![^.!?:]*:)|let(?:\'s| us) (?:break|walk|explore|'
    r'look at)|before we (?:dive|begin|start)|in this (?:section|article|'
    r'guide),? we(?:\'ll| will))\b'
)
SIGNPOSTED_END = r'\b(?:in conclusion|in summary|to sum up|to summari[sz]e|overall,)\b'
# "from X to Y to Z": three points is never a spectrum. The gaps forbid a
# comma, semicolon or colon, because all three of the first run's hits were an
# infinitive in a LATER clause ("from Canvas to work out which you have, then
# how to download ...") rather than a third item in one list. A real false
# range has no sentence punctuation between its poles.
_NOPUNCT = r'(?:(?!\bto\b)[^.!?;:,])'
FALSE_RANGE = r'\bfrom\b' + _NOPUNCT + r'{2,40}\bto\b' + _NOPUNCT + r'{2,40}\bto\b'
# Hedge stacking: two or more modal qualifiers inside one sentence.
HEDGE = (r'\b(?:might|may|could|perhaps|potentially|arguably|somewhat|'
         r'relatively|fairly|generally|typically|in some cases|in certain)\b')
# The verb-your-noun hero, from section VI of the field manual.
HERO_VERB = (r'\b(?:elevate|transform|supercharge|unlock|unleash|revolutioni[sz]e|'
             r'empower|maximi[sz]e|streamline|optimi[sz]e|reimagine) your\b')
SOCIAL_PROOF = (r'\b(?:trusted by (?:teams|thousands|students|users)|'
                r'join (?:thousands|millions)|loved by)\b')
# Straight from the manual's formatting section: characters not on a keyboard.
UNICODE_DECOR = r'[→←⇒•…—–]'

SHAPES = {
    'underscore-v': UNDERSCORE_VERB,
    'harness-v': HARNESS_VERB,
    'partic': PARTICIPIAL_TAIL,
    'signif': SIGNIFICANCE,
    'signpost': SIGNPOST,
    'authority': VAGUE_AUTHORITY,
    'promo': PROMOTIONAL,
    'aphorism': APHORISM,
    'preamble': PREAMBLE,
    'endlabel': SIGNPOSTED_END,
    'falserange': FALSE_RANGE,
    'heroverb': HERO_VERB,
    'socialproof': SOCIAL_PROOF,
}


# ---- cadence tells -------------------------------------------------------
# Added 2026-09-02, after the product owner rejected a "clean" verdict on the
# articles. Every metric above this line is a SURFACE feature - a word, a dash,
# a sentence length - and the articles passed all of them while still reading as
# machine-written. What he and a second model independently identified is a
# STRUCTURAL habit: the periodic sentence on repeat, where the payload is held
# back to the final clause, so every sentence is a setup and a kicker.
#
# The worked example, `panopto-lecture-transcript.html`'s lede, trips all four
# of these at once, which is what says the four are measuring the right thing:
#
#   "A transcript is the most useful form of a lecture and the least demanded.
#    It is searchable, it is a few hundred kilobytes against a few hundred
#    megabytes, it opens on anything, and it is the only form an AI study tool
#    will read. It is also, right now, easier to get than it has ever been -
#    and for most people it already exists."
#
#   ANTITHESIS      most useful ... and the least demanded
#   CLAUSE_ANAPHORA "it is" opening three of four clauses
#   ASCENDING       the last list item is the longest, by a wide margin
#   KICKER          two sentences ending in a coordinator + a fresh subject
#
# None of it is wrong on its own. All four, in one paragraph, three sentences
# long, is a fingerprint.

# A sentence whose LAST clause is introduced by a coordinator and then starts a
# new subject or a new predicate: the "and it is the only form ..." tail. The
# subject list is closed on purpose. A procedural list ("open the course, click
# Files, and press Ctrl + A") continues the same subject with a bare imperative
# verb and must not count - that is an instruction, not a rhetorical tail.
_KICKER_HEAD = (r'^(?:and|but|so|yet)\s+'
                r'(?:it|they|he|she|we|you|i|this|that|there|the|a|an|for|only|'
                r'nobody|everything|nothing|most|almost|its|their|your)\b')


def kicker(sentence: str) -> bool:
    """The sentence's FINAL clause is a coordinator introducing a fresh subject.

    Written over clauses() rather than as one regex, because the regex version
    was wrong in a way that looked right: it matched a coordinator ANYWHERE and
    then let `[^.!?]*` run to the end of the sentence, so "If you want several
    videos, and they lack the same formats, you can set the order yourself"
    counted as a kicker. That is an ordinary mid-sentence compound, which is
    most of English, and it was inflating every page's number including the
    human control corpus. Taking the LAST clause is the definition the tell
    actually has.
    """
    cs = clauses(sentence)
    if len(cs) < 2:
        return False
    return bool(re.match(_KICKER_HEAD, cs[-1].strip(), re.I))


# Three or more clauses inside ONE sentence opening with the same one or two
# words. The existing `anaphora` counter only looks ACROSS sentences, so
# "It is searchable, it is ..., it opens ..., and it is ..." was invisible to it.
_COORD = r'^(?:and|but|or|so|yet)\s+'

# A comma list of three or more items whose LAST item is the longest, which is
# the Law of Increasing Members applied mechanically. Measured as a SHARE: one
# ascending list is ordinary English, and a page where most lists ascend is a
# writer following a rule.

# Superlative or polar antithesis inside one predicate, joined by "and": the
# manufactured paradox that opens a piece and tells the reader nothing.
ANTITHESIS = (
    r'\bthe (?:most|least|best|worst|biggest|smallest|first|last) '
    r'[^,.!?]{0,60}\band the (?:most|least|best|worst|biggest|smallest|first|last)\b'
    r'|\b(?:everything|always|never|nobody|everyone) [^,.!?]{0,50}\band (?:nothing|never|always|everybody|nobody|everyone)\b'
)


def clauses(sentence: str) -> list[str]:
    """Split a sentence into clauses on commas, semicolons and spaced dashes."""
    parts = re.split(r',\s+|;\s+|\s+-\s+|:\s+', sentence)
    return [p.strip() for p in parts if p.strip()]


def clause_anaphora(sentence: str) -> bool:
    """Three or more clauses in one sentence opening with the same 1-2 words."""
    openers = []
    for c in clauses(sentence):
        c = re.sub(_COORD, '', c, flags=re.I)
        w = re.findall(r"[A-Za-z']+", c)[:2]
        if w:
            openers.append(' '.join(x.lower() for x in w))
    if len(openers) < 3:
        return False
    for o in set(openers):
        if openers.count(o) >= 3:
            return True
        # a one-word opener repeated three times counts too ("it is / it opens")
        head = o.split()[0]
        if sum(1 for x in openers if x.split()[0] == head) >= 3:
            return True
    return False


def ascending_list(sentence: str) -> bool | None:
    """True/False for a 3+ item comma list; None when the sentence has no list."""
    cs = clauses(sentence)
    if len(cs) < 3:
        return None
    lens = [len(c.split()) for c in cs]
    return lens[-1] > max(lens[:-1])


def _body(html: str) -> str:
    """The page's own content, without the shared nav and footer.

    The first version searched for `<article>`, matched nothing on any page and
    silently fell back to scanning the whole document - a guard reading a
    superset of what it claimed to read. It then used `<div class="art">`,
    which exists only on the 13 articles and cut off the hero heading even
    there. `<main>` is on all 26 pages and starts at the `<h1>`. It raises
    rather than falling back, so a shell change fails loudly.
    """
    i = html.index('<main')
    j = html.rindex('</main>')
    # `guide.html` and `engine.html` put their hero OUTSIDE `<main>`: the `<h1>`
    # is at 35,491 and `<main>` opens at 38,047. Reading from `<main>` therefore
    # skipped the headline and the standfirst on exactly the two pages with the
    # most prose, and the standfirst is the second line a reader sees. Start at
    # whichever comes first. On the other 24 pages the `<h1>` is inside `<main>`
    # and this changes nothing; the nav sits earlier than both, so it stays out.
    h1 = html.find('<h1')
    if 0 <= h1 < i:
        i = h1
    return html[i:j]


# A quoted run of four words or more, with no quote character inside it, is
# somebody else's sentence. Written as a function rather than as one regex
# because the regex version let `\w+` split a single word into four, so
# `"damaged"` scored as a four-word quotation and vanished from the word count.
# Counting the words explicitly is the thing that cannot be fooled that way.
_QUOTED = re.compile(r'["\u201c]([^"\u201c\u201d]{8,600}?)["\u201d]')


def _strip_quotations(t: str) -> str:
    return _QUOTED.sub(
        lambda m: ' ' if len(m.group(1).split()) >= 4 else m.group(0), t)


def visible_text(html: str) -> str:
    t = re.sub(r'(?s)<script.*?</script>|<style.*?</style>|<svg.*?</svg>', ' ', html)
    # AN HTML COMMENT IS NOT PROSE. index.html carries several hundred words of
    # engineering notes inside <!-- --> (the LCP writeup, the palette notes),
    # and they were being scored as the page's writing - one of them supplied a
    # "rhetorical question" hit reading "div.hero-gif-wrap > div.hero-media".
    # Developer prose about a paint bug is not copy a visitor reads.
    t = re.sub(r'(?s)<!--.*?-->', ' ', t)
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
    # Code samples are not prose either, and win-setup/mac-setup are largely
    # terminal commands.
    t = re.sub(r'(?s)<pre.*?</pre>|<code.*?</code>', ' ', t)
    # A QUOTATION IS SOMEBODY ELSE'S PROSE. These pages quote Instructure's KB,
    # university policy pages and forum answers on purpose - citing sources is
    # the site's main credibility lever - and scoring those words as this
    # site's writing flagged a university's own "ANY aspect of interactive
    # media" as a lexicon hit. Nothing there can be rewritten without
    # misquoting, so it must not be counted.
    t = re.sub(r'(?s)<blockquote.*?</blockquote>', ' ', t)
    # Most citations on this site are NOT in a <blockquote> - they are a
    # quoted run inside a sentence, often wrapped in <em> inside the source
    # link. Echo360's own policy wording, quoted verbatim on the lecture-video
    # page, was scoring as this site's use of "aspect of". So any quoted run of
    # four words or more comes out, wherever it sits. Short quotes stay, which
    # keeps UI labels ("damaged", "unidentified developer") in the word count.
    #
    # This deliberately also excludes app copy quoted character-exact, which
    # CLAUDE.md requires be quoted rather than reflowed - prose nobody is
    # allowed to rewrite must not be scored as prose somebody wrote.
    # The call itself is at the END of this function, after the tags are gone.
    # The FAQ is a list of questions BY DESIGN, and it was supplying 7 of the 8
    # "rhetorical question" hits on every page - a metric that always fires is a
    # guard that cannot say no.
    t = re.sub(r'(?s)<section[^>]*id="faq".*', ' ', t)
    t = re.sub(r'(?s)<h2[^>]*id="faq".*', ' ', t)
    # A HEADING IS NOT A SENTENCE IN A PARAGRAPH, and RHETORICAL_Q is defined as
    # a MID-PARAGRAPH self-question. Stripping tags runs a question-shaped
    # heading straight into the following paragraph's opening capital, which is
    # the pattern exactly - so `<h3>Is Files in the course navigation?</h3>`
    # followed by any sentence scored as a rhetorical question. Same defect as
    # the FAQ and the table cell above it, and the same fix: remove the thing
    # the metric never claimed to be reading.
    #
    # This cannot hide a real hit. A genuine mid-paragraph self-question lives
    # inside a <p>, which is untouched here. Positive control in the commit:
    # a paragraph containing one is still caught after this line.
    t = re.sub(r'(?s)<h[1-6][^>]*>.*?</h[1-6]>', ' ', t)
    # A `<summary>` IS a heading - it is the disclosure widget's title, and on
    # this site every one of them is a question by design ("Is it really free?",
    # "Why is Windows warning me?"). Left in, they supplied 6 of the 8
    # rhetorical-question hits on the homepage: the same defect as the FAQ, the
    # table cell and the `<h3>` above, found the same way and fixed the same
    # way. The FAQ truncation only removed the ones under `id="faq"`; the
    # homepage carries three more disclosure blocks outside it.
    t = re.sub(r'(?s)<summary[^>]*>.*?</summary>', ' ', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = _html.unescape(t)
    # ONLY NOW. The first version stripped quotations while the markup was
    # still present, so `class="hero"` and every href paired their attribute
    # quotes with the next one and blanked whole sentences in between: the word
    # count fell and four real hits vanished, which reads exactly like a
    # successful edit. Unescape first as well, or a `&quot;` citation is
    # invisible to it.
    t = _strip_quotations(t)
    return re.sub(r'[ \t]+', ' ', t)


def paragraphs(html: str) -> list[str]:
    src = _body(html)
    src = re.sub(r'(?s)<script.*?</script>|<style.*?</style>|<svg.*?</svg>', ' ', src)
    # The byline ("By BrkBuilds, who builds the app - Published ...") is
    # boilerplate, not prose anyone chose the rhythm of.
    src = re.sub(r'(?s)<p class="byline".*?</p>', ' ', src)
    out = []
    for m in re.finditer(r'(?s)<p[^>]*>(.*?)</p>', src):
        p = re.sub(r'<[^>]+>', ' ', m.group(1))
        p = _html.unescape(p)
        p = re.sub(r'\s+', ' ', p).strip()
        if len(p.split()) > 8:
            out.append(p)
    return out


def headings(html: str) -> list[tuple[str, str]]:
    src = _body(html)
    src = re.sub(r'(?s)<svg.*?</svg>', ' ', src)
    out = []
    for m in re.finditer(r'(?s)<(h[1-6])[^>]*>(.*?)</\1>', src):
        t = re.sub(r'<[^>]+>', ' ', m.group(2))
        t = re.sub(r'\s+', ' ', _html.unescape(t)).strip()
        if t:
            out.append((m.group(1), t))
    return out


def summaries(html: str) -> list[str]:
    src = _body(html)
    src = re.sub(r'(?s)<svg.*?</svg>', ' ', src)
    out = []
    for m in re.finditer(r'(?s)<summary[^>]*>(.*?)</summary>', src):
        t = re.sub(r'<[^>]+>', ' ', m.group(1))
        t = re.sub(r'\s+', ' ', _html.unescape(t)).strip()
        if t:
            out.append(t)
    return out


def bullets(html: str) -> list[str]:
    src = _body(html)
    src = re.sub(r'(?s)<svg.*?</svg>', ' ', src)
    return [m.group(1) for m in re.finditer(r'(?s)<li[^>]*>(.*?)</li>', src)]


def sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"“])', text)
    return [p.strip() for p in parts if len(p.split()) >= 3]


# Words that stay lowercase inside a title, so they do not count against the
# Title Case test. Product nouns that are capitalised in the UI (Canvas, Quick
# Sync, Panopto) would otherwise make every correct heading look title-cased,
# so they are excluded from the ratio too.
_MINOR = {'a', 'an', 'the', 'and', 'or', 'but', 'for', 'nor', 'of', 'to', 'in',
          'on', 'at', 'by', 'from', 'with', 'as', 'is', 'it', 'if', 'so',
          'into', 'your', 'you', 'my', 'me', 'that', 'this', 'not', 'no'}
_PROPER = {'canvas', 'panopto', 'notebooklm', 'windows', 'macos', 'mac',
           'microsoft', 'github', 'quick', 'sync', 'today', 'downloader',
           'apple', 'office', 'powerpoint', 'word', 'excel', 'pdf', 'files',
           'modules', 'pages', 'instructure', 'studio', 'kaltura', 'zip',
           'ai', 'faq', 'api', 'i', 'python', 'chrome', 'whisper', 'settings',
           'account', 'store', 'gpl', 'srt', 'mp3', 'mp4', 'birk', 'brkbuilds',
           'sonoma', 'sequoia', 'tahoe', 'ventura', 'silicon', 'intel',
           'terminal', 'keychain', 'finder', 'safari', 'edge', 'firefox'}


def title_case_headings(hs: list[tuple[str, str]]) -> list[str]:
    """Headings where the writer capitalised words that are not proper nouns.

    Humans use sentence case. The test only looks at words after the first,
    ignores the minor words a title-caser would leave lowercase anyway, and
    ignores this product's own capitalised nouns - otherwise "Download from
    Canvas with Quick Sync" scores as Title Case on two correct capitals.
    Fires at two or more, so a single stray capital is not a hit.
    """
    out = []
    for _, t in hs:
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", t)[1:]]
        cand = [w for w in words
                if w.lower() not in _MINOR and w.lower() not in _PROPER
                and not w.isupper()]
        if len(cand) >= 2 and sum(1 for w in cand if w[0].isupper()) >= 2:
            out.append(t)
    return out


def report(slug: str) -> dict:
    html = (DOCS / slug).read_text(encoding='utf-8')
    text = visible_text(html)
    paras = paragraphs(html)
    sents = [s for p in paras for s in sentences(p)]
    lens = [len(s.split()) for s in sents]
    plens = [len(p.split()) for p in paras]
    hs = headings(html) + [('summary', t) for t in summaries(html)]
    lis = bullets(html)

    lex = {}
    for tier, terms in LEX_RE.items():
        hits = {}
        for term, rx in terms:
            n = len(rx.findall(text))
            if n:
                hits[term] = n
        lex[tier] = hits

    shape = {}
    for name, pat in SHAPES.items():
        shape[name] = len(re.findall(pat, text, re.I))

    neg = sum(len(re.findall(p, text, re.I)) for p in NEG_PARALLEL)
    # RHETORICAL_Q is defined as a MID-PARAGRAPH self-question, so it now runs
    # over the paragraphs rather than over the concatenated page. Stripping tags
    # runs a question-shaped heading, `<summary>`, table cell or link-card title
    # straight into the next element's opening capital, which is that pattern
    # exactly. Four separate strip rules had been added to chase that class one
    # element at a time; reading <p> ends the whole class at once, and it cannot
    # hide a real hit, because a genuine mid-paragraph self-question is in a <p>.
    rq = sum(len(re.findall(RHETORICAL_Q, q)) for q in paras)
    contractions = len(re.findall(r"\b\w+(?:'|’)(?:s|t|re|ve|ll|d|m)\b", text))

    # anaphora: three or more consecutive sentences opening with the same word
    ana = 0
    for i in range(len(sents) - 2):
        w = [s.split()[0].lower().strip(',') for s in sents[i:i + 3]]
        if w[0] == w[1] == w[2]:
            ana += 1

    # hedge stacking: two or more modal qualifiers in one sentence
    hedge = sum(1 for s in sents if len(re.findall(HEDGE, s, re.I)) >= 2)

    # fragment cadence: three consecutive sentences of four words or fewer
    frag = 0
    for i in range(len(lens) - 2):
        if lens[i] <= 4 and lens[i + 1] <= 4 and lens[i + 2] <= 4:
            frag += 1

    # cadence: the setup-then-kicker habit, measured four ways
    kick = sum(1 for x in sents if kicker(x))
    cl_ana = sum(1 for x in sents if clause_anaphora(x))
    asc = [ascending_list(x) for x in sents]
    asc = [a for a in asc if a is not None]
    antith = sum(1 for x in sents if re.search(ANTITHESIS, x, re.I))

    # dash-as-em-dash: " - " used the way an em dash is used
    dashes = len(re.findall(r'\S \- \S', text))
    # the dash SANDWICH: a paragraph carrying two or more of them
    dash_pairs = sum(1 for p in paras if len(re.findall(r'\S \- \S', p)) >= 2)

    # bold-first bullets: <li><strong>Label:</strong> clause, as a template
    boldfirst = sum(1 for li in lis
                    if re.match(r'\s*<(?:strong|b)>', li))

    return dict(
        slug=slug,
        article=slug in ARTICLES,
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
        dash_pairs=dash_pairs,
        kicker=kick,
        kicker_pct=round(100 * kick / max(1, len(sents))),
        clause_anaphora=cl_ana,
        ascending=sum(1 for a in asc if a),
        lists=len(asc),
        ascending_pct=round(100 * sum(1 for a in asc if a) / max(1, len(asc))),
        antithesis=antith,
        neg_parallel=neg,
        rhetorical_q=rq,
        anaphora=ana,
        hedge=hedge,
        fragments=frag,
        titlecase=title_case_headings(hs),
        bold_bullets=boldfirst,
        bullets=len(lis),
        unicode_decor=len(re.findall(UNICODE_DECOR, text)),
        lex=lex,
        shape=shape,
        banned={**lex['t1'], **lex['t2'], **lex['colloc'], **lex['opener']},
    )


def _quote(text: str, pat: str, width: int = 110) -> list[str]:
    out = []
    for m in re.finditer(pat, text, re.I):
        a = max(0, m.start() - 45)
        out.append('...' + re.sub(r'\s+', ' ', text[a:m.end() + width]).strip() + '...')
    return out


def detail(slug: str) -> None:
    html = (DOCS / slug).read_text(encoding='utf-8')
    text = visible_text(html)
    r = report(slug)
    printed = False

    def head():
        nonlocal printed
        if not printed:
            print('\n=== %s ===' % slug)
            printed = True

    for tier in ('t1', 't2', 't3', 'colloc', 'opener'):
        for term in sorted(r['lex'][tier]):
            head()
            print('  [%s] %s x%d' % (tier, term, r['lex'][tier][term]))
            for q in _quote(text, _lex_re(term).pattern)[:4]:
                print('      ' + q)
    for name, pat in SHAPES.items():
        if r['shape'][name]:
            head()
            print('  [shape] %s x%d' % (name, r['shape'][name]))
            for q in _quote(text, pat)[:6]:
                print('      ' + q)
    if r['neg_parallel']:
        head()
        print('  [shape] neg-parallel x%d' % r['neg_parallel'])
        for p in NEG_PARALLEL:
            for q in _quote(text, p)[:3]:
                print('      ' + q)
    if r['rhetorical_q']:
        head()
        print('  [shape] rhetorical-q x%d' % r['rhetorical_q'])
        for q in _quote(text, RHETORICAL_Q)[:4]:
            print('      ' + q)
    if r['titlecase']:
        head()
        print('  [format] Title Case headings x%d' % len(r['titlecase']))
        for t in r['titlecase'][:10]:
            print('      ' + t)
    if r['unicode_decor']:
        head()
        print('  [format] unicode decoration x%d' % r['unicode_decor'])
        for q in _quote(text, UNICODE_DECOR, 60)[:4]:
            print('      ' + q)
    if r['hedge']:
        head()
        print('  [shape] hedge stacking x%d' % r['hedge'])


# (pattern, must fire, must not fire, flags) - every new pattern gets one of
# each, so a zero on the site is a real zero and not a broken regex.
#
# The FLAGS column exists because the first version of this list applied re.I
# to everything while report() runs RHETORICAL_Q case-sensitively. Under re.I
# that pattern matches almost any question, so the control reported a failure
# the production code could never produce. A control that does not run the
# pattern the way the product runs it is testing a different regex - third time
# a checker on this site needed fixing before its number meant anything.
CONTROL = [
    (PARTICIPIAL_TAIL,
     'They shipped it in March, underscoring their commitment to reliability.',
     'She left the room, carrying the box she had packed.', re.I),
    (SIGNIFICANCE,
     'The release represents a major shift for the project.',
     'If you represent an institution, please open an issue.', re.I),
    (SIGNIFICANCE,
     'The building serves as a reminder of the city.',
     'It would mark a missing file as present.', re.I),
    (SIGNPOST,
     "It's worth noting that the free plan has limits.",
     'The free plan has limits and you can upgrade any time.', re.I),
    (VAGUE_AUTHORITY,
     'Studies have shown that users prefer simpler interfaces.',
     "Nielsen's 2024 study found task time dropped 30 percent.", re.I),
    (PROMOTIONAL,
     'The ultimate tool for university students.',
     'A download tool for university students.', re.I),
    (APHORISM,
     'At the end of the day, we are all human.',
     'The ferry runs twice a day from the harbour.', re.I),
    (PREAMBLE,
     "There are a few things to consider. Let's break them down.",
     'Use Postgres unless you have a reason not to.', re.I),
    (PREAMBLE,
     'There are several factors here. We will come back to them later.',
     'There are three ways to do it by hand: an extension, a script, or an app.',
     re.I),
    (SIGNPOSTED_END,
     'In conclusion, the export is worth running.',
     'The export is worth running before the semester ends.', re.I),
    (FALSE_RANGE,
     'Everything from onboarding to analytics to culture is handled.',
     'It copies files from Canvas to your computer.', re.I),
    (FALSE_RANGE,
     'It ranges from small to medium to large in one table.',
     'Start with how to download videos from Canvas to work out which you '
     'have, then how to download Panopto recordings.', re.I),
    (HERO_VERB,
     'Supercharge your productivity today.',
     'It downloads your courses in one run.', re.I),
    (UNDERSCORE_VERB,
     'The delay underscores the need for a second check.',
     'The dot becomes an underscore rather than being appended.', re.I),
    (HARNESS_VERB,
     'The team harnesses the power of the platform.',
     'It drives a real account through an audit harness.', re.I),
    (SOCIAL_PROOF,
     'Trusted by teams worldwide.',
     '1,100 people have installed it.', re.I),
    # A real one, lifted from canvas-access-token-explained.html. The pattern
    # is a MID-PARAGRAPH self-question, so the capital that opens it has to
    # follow a lowercase word or a comma; a question that starts a new sentence
    # after a full stop was never matched and never claimed to be. The first
    # positive control here was "So what changed?" after a full stop, which
    # this pattern cannot match - a control that fails for the right reason
    # still fails, and the fix is a control that exercises the real pattern.
    (RHETORICAL_Q,
     'the question underneath is always the same one: how much am I handing '
     'over? Instructure answers it in a sentence.',
     'The files were there. So why did nobody notice? Nobody looked.', 0),
]


def control() -> int:
    """Prove every pattern can say BOTH yes and no.

    A negative result from a diagnostic nobody has controlled is worth nothing.
    Returns the number of failures.
    """
    bad = 0
    for pat, yes, no, flags in CONTROL:
        if not re.search(pat, yes, flags):
            print('FAIL positive: %s ... on %r' % (pat[:40], yes)); bad += 1
        if re.search(pat, no, flags):
            print('FAIL negative: %s ... on %r' % (pat[:40], no)); bad += 1
    for term, rx in LEX_RE['t2']:
        if term == 'unlock':
            if rx.search('a module that unlocks later on'):
                print('FAIL: word-boundary lexicon still matches "unlocks"'); bad += 1
            if not rx.search('Unlock your potential.'):
                print('FAIL: lexicon no longer matches the real word'); bad += 1
    # neg-parallel: the two the manual names, plus the compound clause that
    # must NOT fire (it was three false positives per real hit before).
    for s in ("It's not just a to-do app, it's a way of thinking.",
              'This is more than just a downloader, it keeps the folder current.'):
        if not any(re.search(p, s, re.I) for p in NEG_PARALLEL):
            print('FAIL neg-parallel positive: %r' % s); bad += 1
    if any(re.search(p, 'This is not rare and it is worth checking.', re.I)
           for p in NEG_PARALLEL):
        print('FAIL neg-parallel negative on a compound clause'); bad += 1
    # Title Case: a real one fires, a sentence-case heading with product nouns
    # does not.
    if not title_case_headings([('h2', 'Download Your Course Files Fast')]):
        print('FAIL titlecase positive'); bad += 1
    if title_case_headings([('h2', 'Download every file from Canvas with Quick Sync')]):
        print('FAIL titlecase negative on product nouns'); bad += 1
    # The quotation strip, both ways: a cited sentence is not scored, an
    # identical uncited one is, and a one-word quote survives in the word count.
    for html, word, expect in (
            ('<main><p>It is a <em>"robust and seamless holistic approach"</em>'
             ' today.</p></main>', 'robust', False),
            ('<main><p>It is a robust and seamless holistic approach today.'
             '</p></main>', 'robust', True),
            ('<main><p>macOS says it is "damaged" when the seal breaks.'
             '</p></main>', 'damaged', True)):
        if (word in visible_text(html).lower()) is not expect:
            print('FAIL quotation strip on %r' % word); bad += 1
    # An HTML comment is not prose.
    if 'opacity' in visible_text('<main><!-- .reveal starts at opacity:0 -->'
                                 '<p>Real copy here for the reader.</p></main>'):
        print('FAIL: HTML comment counted as prose'); bad += 1
    # ---- cadence, controlled both ways ----------------------------------
    # KICKER must catch a rhetorical tail and must NOT catch a procedure. The
    # difference is grammatical: a tail introduces a fresh subject ("and it
    # is..."), an instruction continues the same one with a bare imperative
    # ("and press Ctrl + A").
    for txt, want in (
            ('It is searchable, and it is the only form an AI tool will read.', True),
            ('It is easier to get than ever - and for most people it already exists.', True),
            ('This page starts with the free one, and only then covers your own.', True),
            ('Open the course, click Files, and press Ctrl or Cmd + A.', False),
            ('It downloads your courses and keeps the folder current.', False),
            ('Tick the courses you want, then choose a folder.', False),
            # the mid-sentence compound the first regex version wrongly caught
            ('If you want several videos, and they lack the same formats, you '
             'can set the order of preference yourself.', False)):
        if kicker(txt) is not want:
            print('FAIL kicker on %r' % txt); bad += 1
    for txt, want in (
            ('It is searchable, it is small, it opens on anything, and it is the only form.', True),
            ('It is searchable, small, and easy to open on anything at all.', False),
            ('You can rename files, move them, and reorganise the whole folder.', False)):
        if clause_anaphora(txt) is not want:
            print('FAIL clause_anaphora on %r' % txt); bad += 1
    for txt, want in (
            ('It is fast, it is small, and it is the only form an AI tool will read.', True),
            ('It is the only form an AI study tool will read, it is small, and it is fast.', False),
            ('It is fast.', None)):
        if ascending_list(txt) is not want:
            print('FAIL ascending_list on %r' % txt); bad += 1
    for txt, want in (
            ('It is the most useful form of a lecture and the least demanded.', True),
            ('It is the most useful form of a lecture and the fastest to make.', False)):
        if bool(re.search(ANTITHESIS, txt, re.I)) is not want:
            print('FAIL antithesis on %r' % txt); bad += 1
    print('control: %d failure(s)' % bad)
    return bad


if __name__ == '__main__':
    # Windows defaults stdout to CP1252 and the quoted hits contain the
    # arrows and curly quotes this scanner exists to find, so printing one
    # raised UnicodeEncodeError and killed the run mid-report.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    if '--control' in sys.argv:
        raise SystemExit(1 if control() else 0)

    rows = [report(s) for s in SLUGS]

    if '--detail' in sys.argv:
        for s in SLUGS:
            detail(s)
        raise SystemExit(0)

    hdr = ('page', 'words', 'mean', 'sd', 'short%', 'long%', 'contr/1k',
           'dash/1k', 'neg', 'rhtQ', 'ana', 'hedg', 'shape', 'lex')
    print('%-44s %5s %5s %5s %6s %5s %8s %7s %4s %5s %4s %5s %6s %4s' % hdr)
    for r in rows:
        print('%-44s %5d %5.1f %5.1f %5d%% %4d%% %8.1f %7.1f %4d %5d %4d %5d %6d %4d' % (
            r['slug'][:44], r['words'], r['sent_mean'], r['sent_sd'],
            r['short_pct'], r['long_pct'], r['contr_per_1k'], r['dash_per_1k'],
            r['neg_parallel'], r['rhetorical_q'], r['anaphora'], r['hedge'],
            sum(r['shape'].values()),
            sum(len(v) for v in r['lex'].values())))

    print()
    for tier in ('t1', 't2', 't3', 'colloc', 'opener'):
        allb = {}
        for r in rows:
            for k, v in r['lex'][tier].items():
                allb[k] = allb.get(k, 0) + v
        print('%-8s %s' % (tier, dict(sorted(allb.items(), key=lambda kv: -kv[1])) or 'NONE'))
    print()
    allshape = {}
    for r in rows:
        for k, v in r['shape'].items():
            allshape[k] = allshape.get(k, 0) + v
    print('shapes  %s' % {k: v for k, v in sorted(allshape.items(), key=lambda kv: -kv[1]) if v})
    print('titlecase headings: %d across %d pages'
          % (sum(len(r['titlecase']) for r in rows),
             sum(1 for r in rows if r['titlecase'])))
    print('bold-first bullets: %d of %d'
          % (sum(r['bold_bullets'] for r in rows), sum(r['bullets'] for r in rows)))
    print('unicode decoration: %d' % sum(r['unicode_decor'] for r in rows))
    print('dash sandwiches (2+ in one paragraph): %d' % sum(r['dash_pairs'] for r in rows))
