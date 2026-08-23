"""Copy for the two search-facing guide pages. Read scripts/build_guide_pages.py first.

Every factual claim here was checked on 2026-08-20 against a primary source, and
the ones that vary by institution are stated as varying rather than as fact:

* "Download as Zip" from a course's Files tab, and the Ctrl/Cmd+A select-all
  step - University of Illinois KB 127046, Stanford Canvas Help 115001602467,
  NCTC 205334770.
* Files under Account > Files > Submissions are the student's OWN uploads, not
  the course material. Illinois KB 127046 describes exactly this and is easy to
  mistake for a course-file export, which is why the page separates them.
* Nothing in Canvas exports Pages or Assignments in bulk. The accepted answer on
  Instructure Community discussion 618390 (Oct 2024) says "As for Pages and
  Assignments, I'm not sure of a quick way off the top of my head", and the
  second accepted answer confirms Studio media downloads one at a time.
* Some institutions disable student access-token generation. Source: the asker
  in that same thread - "Previously, I used access tokens to run an application
  for downloading the files, but my school has recently removed that feature."
  This is why the token caveat is stated plainly instead of being buried.

TONE RULES
* Say "Canvas", never "LMS".
* No em dashes anywhere on this site; use " - ".
* Describe the competing approaches fairly, including where they beat this app.
  A page that only exists to sell does not earn the link that makes it rank.
"""
from __future__ import annotations

SITE = "https://canvasdownloader.app/"

# ============================================================ PAGE 1 =========

P1_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#builtin">What Canvas can do on its own</a></li>
          <li><a href="#zip">Method 1: Download as Zip, one course at a time</a></li>
          <li><a href="#submissions">Method 2: Your own submitted work</a></li>
          <li><a href="#extensions">Method 3: Browser extensions</a></li>
          <li><a href="#scripts">Method 4: Scripts and command-line tools</a></li>
          <li><a href="#app">Method 5: A desktop app that uses the Canvas API</a></li>
          <li><a href="#compare">All five, side by side</a></li>
          <li><a href="#pick">Which one you should use</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">There is no button in Canvas that downloads everything from
      every course. That is the honest starting point, and it is why this
      question gets asked so often. What Canvas gives you is a per-course zip of
      one particular tab, and that tab is frequently not where your slides
      actually live.</p>

      <p>Below is every route that works, what each one really collects, and
      where each one stops. Four of the five need no software at all, so start
      there and only go further if they fall short.</p>

      <h2 id="builtin">What Canvas can do on its own</h2>

      <p>Canvas has exactly two bulk exports available to a student, and they
      cover different things:</p>

      <ul>
        <li><strong>A course's Files tab</strong>, zipped. One course per zip.</li>
        <li><strong>Your own submissions</strong>, the documents you uploaded to
        assignments. Not the course material.</li>
      </ul>

      <p>Neither one touches Pages, Assignment descriptions, announcements,
      discussions, quizzes or the syllabus. Nothing built into Canvas exports
      those in bulk, which is the part most people are surprised by. When a
      student asked precisely this on the Instructure Community forum in October
      2024, the accepted answer ended with <em>"As for Pages and Assignments,
      I'm not sure of a quick way off the top of my head."</em> That is still
      the state of it.</p>

      <div class="note">
        <p><strong>"Can't I just export the course?"</strong> No, and this trips
        up a lot of people. Canvas does have a full course export that produces
        an <code>.imscc</code> package containing everything, but it is an
        instructor permission. As a student you will not see the option, and
        asking your instructor to run one for you is a real request rather than a
        formality.</p>
      </div>

      <h2 id="zip">Method 1: Download as Zip, one course at a time</h2>

      <p>This is the built-in route and it is the right first thing to try.</p>

      <ol class="steps">
        <li>Open the course in Canvas.</li>
        <li>Click <strong>Files</strong> in the course navigation on the left.</li>
        <li>Click once inside the file list, then press <code>Ctrl</code> +
        <code>A</code> (Windows) or <code>Cmd</code> + <code>A</code> (Mac) to
        select everything.</li>
        <li>Choose <strong>Download as Zip</strong> from the options that appear
        above the list.</li>
        <li>Wait for the progress bar, then unzip the file on your computer.</li>
      </ol>

      <p>You get the files and the folder structure exactly as the teacher
      arranged them. For a tidy course that is genuinely all you need.</p>

      <h3>Where it stops</h3>

      <ul>
        <li><strong>One course at a time.</strong> Six courses means repeating
        this six times, then organising six zips yourself.</li>
        <li><strong>Files uploaded straight into a Module or a Page may not be
        in the Files tab at all.</strong> This is the big one. A lecturer who
        attaches a slide deck directly to a module item has put a file in your
        course that the Files tab never lists, so the zip silently misses it.</li>
        <li><strong>The Files tab can be switched off.</strong> Teachers can
        hide it from course navigation, and plenty do. Then this method does not
        exist for that course.</li>
        <li><strong>Nothing else comes with it.</strong> No Pages, no assignment
        instructions, no announcements, no quiz content, no feedback you were
        given.</li>
        <li><strong>It is a snapshot.</strong> Next month's slides are not in
        last month's zip, so you repeat the whole thing.</li>
      </ul>

      <div class="note">
        <p>Worth knowing: a file being missing from the Files tab does not mean
        you cannot open it. It means it is not <em>listed</em> there. You can
        still reach it through the module, one click at a time.</p>
      </div>

      <h2 id="submissions">Method 2: Your own submitted work</h2>

      <p>Separate feature, commonly confused with the one above because several
      university help pages describe it under a heading about downloading "your
      files". This one collects the documents <em>you</em> handed in.</p>

      <p>There are two routes. The export is the thorough one:</p>

      <ol class="steps">
        <li>Click <strong>Account</strong> in the far-left global navigation, then
        <strong>Settings</strong>.</li>
        <li>Click <strong>Download Submissions</strong> in the sidebar, then
        <strong>Create Export</strong>.</li>
        <li>Wait for Canvas to build it, then download the zip. It covers current
        <em>and</em> concluded courses.</li>
      </ol>

      <p>Or browse them directly under <strong>Account</strong> then
      <strong>Files</strong> then <strong>My Files</strong> then
      <strong>Submissions</strong>, where there is a folder per course. Anything
      you embedded with the rich content editor sits in
      <strong>Uploaded Media</strong> instead.</p>

      <div class="note warn">
        <p>The export contains the files exactly as <em>you</em> submitted them.
        It does <strong>not</strong> include instructor-annotated versions, and it
        carries none of your grades or feedback comments. That is worth knowing
        before you assume you have saved everything: the annotated copy of your
        dissertation draft is not in this zip.</p>
      </div>

      <h2 id="extensions">Method 3: Browser extensions</h2>

      <p>Several Chrome extensions scan the page you are currently looking at
      and offer to download every file they can see on it. Some go a step
      further and follow links into Pages to find attachments the Files tab does
      not list.</p>

      <p><strong>What they are good at:</strong> speed and zero setup. You are
      already logged in, so there is no token to create and nothing to install
      beyond the extension. For grabbing one messy module quickly, an extension
      is hard to beat.</p>

      <p><strong>What to weigh up:</strong> an extension that can read your
      Canvas pages can read whatever else you have told it it can read, so the
      permissions it asks for are worth reading before you click Add. They work
      per page rather than per account, so "all my courses at once" is not
      normally on offer. They cannot fetch anything that is not reachable from a
      page you have open, and they have no memory of what they fetched last
      time, so every run starts from scratch.</p>

      <h2 id="scripts">Method 4: Scripts and command-line tools</h2>

      <p>There are good open-source scripts that talk to the Canvas API directly.
      They tend to be the most flexible option in existence: if you can read the
      code, you can make it fetch exactly what you want, in exactly the layout
      you want, on a schedule.</p>

      <p>The cost is that you need Python or Node installed, you need to be
      comfortable in a terminal, and you need to keep the thing working when
      something changes. That is a fine trade for some people and a wall for
      most. If you are studying computer science, this is probably your best
      option and you should ignore the rest of this page.</p>

      <h2 id="app">Method 5: A desktop app that uses the Canvas API</h2>

      <p>This is what <a href="index.html">Canvas Downloader</a> is, and since
      this is our site you should read this section knowing that. It is free,
      open source and the entire codebase is
      <a href="https://github.com/BrkBuilds/Canvas-Downloader" target="_blank"
      rel="noopener">public on GitHub</a>, so you can check every claim below
      rather than take our word for it.</p>

      <p>It signs in with an access token you create yourself in Canvas, then
      uses the same official API the Canvas mobile apps use. Because it works at
      the account level rather than the page level, it can do the two things the
      other methods cannot:</p>

      <ul>
        <li><strong>Every course in one run.</strong> Tick the courses you want
        and it downloads them all, each into its own folder.</li>
        <li><strong>Everything, not just the Files tab.</strong> It walks the
        modules as well, so a slide deck attached directly to a module item is
        collected like any other file. Assignments, announcements, discussions,
        quizzes, the syllabus and the feedback on your own submissions are
        saved as readable documents if you ask for them.</li>
      </ul>

      <p>Two things it adds that a one-off download cannot: it can
      <strong>sync</strong>, meaning the second run fetches only what is new or
      changed and leaves everything else alone, and it can save
      <strong>Panopto lecture recordings</strong> as video, audio, a transcript
      or subtitles, with the transcription running on your own machine.</p>

      <div class="note warn">
        <p><strong>The honest caveat:</strong> it needs an access token, and a
        small number of institutions have turned off students' ability to create
        one. If your Canvas account settings have no "New Access Token" button,
        no API-based tool can work for you, and Methods 1 to 3 are your options.
        Check before you install anything.</p>
      </div>

      <h2 id="compare">All five, side by side</h2>

      <div class="tbl-wrap" tabindex="0" role="region"
        aria-label="Comparison of five ways to download Canvas files">
        <table class="cmp">
          <thead>
            <tr>
              <th>What you want</th>
              <th>Download as Zip</th>
              <th>Submissions</th>
              <th>Extension</th>
              <th>Script</th>
              <th>Canvas Downloader</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>All courses in one go</td>
              <td class="no">No</td><td class="part">Partly</td>
              <td class="no">No</td><td class="yes">Yes</td><td class="yes">Yes</td>
            </tr>
            <tr>
              <td>Files hidden in Modules or Pages</td>
              <td class="no">No</td><td class="no">No</td>
              <td class="part">Some</td><td class="yes">Yes</td><td class="yes">Yes</td>
            </tr>
            <tr>
              <td>Assignments, announcements, quizzes</td>
              <td class="no">No</td><td class="no">No</td>
              <td class="no">No</td><td class="part">Varies</td><td class="yes">Yes</td>
            </tr>
            <tr>
              <td>Your grades and feedback</td>
              <td class="no">No</td><td class="no">No</td>
              <td class="no">No</td><td class="part">Varies</td><td class="yes">Yes</td>
            </tr>
            <tr>
              <td>Panopto lecture recordings</td>
              <td class="no">No</td><td class="no">No</td>
              <td class="no">No</td><td class="part">Rarely</td><td class="yes">Yes</td>
            </tr>
            <tr>
              <td>Only fetches what changed</td>
              <td class="no">No</td><td class="no">No</td>
              <td class="no">No</td><td class="part">Varies</td><td class="yes">Yes</td>
            </tr>
            <tr>
              <td>Nothing to install</td>
              <td class="yes">Yes</td><td class="yes">Yes</td>
              <td class="part">Extension</td><td class="no">No</td><td class="no">No</td>
            </tr>
            <tr>
              <td>Works without an access token</td>
              <td class="yes">Yes</td><td class="yes">Yes</td>
              <td class="yes">Yes</td><td class="no">No</td><td class="no">No</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 id="pick">Which one you should use</h2>

      <p><strong>One course, tidy Files tab, need it now.</strong> Download as
      Zip. Do not install anything.</p>

      <p><strong>One messy module where the files are scattered through
      Pages.</strong> A browser extension will be quicker than anything else.</p>

      <p><strong>You are about to lose access and want everything.</strong> This
      is the case the built-in tools handle worst, because "everything" includes
      the parts Canvas does not export. See
      <a href="canvas-access-after-graduation.html">what happens to your Canvas
      account after you graduate</a>.</p>

      <p><strong>You want your course folder to stay current all semester.</strong>
      Only a syncing tool does this. Everything else is a snapshot you have to
      keep repeating.</p>

      <p><strong>You are comfortable in a terminal.</strong> Use a script. You
      will get exactly what you want and you will understand every part of it.</p>

      <p><strong>You want the lecture recordings.</strong> None of the five above
      touch them, because Panopto is a separate system. See
      <a href="download-panopto-lecture-recordings.html">how to download Panopto
      lecture recordings</a>, and read the permission section first.</p>

      <div class="cta-box">
        <h3>Get every file from every course</h3>
        <p>Free and open source, for Windows and macOS. Runs on your own
        computer: no account, no server, nothing uploaded.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="guide.html" class="btn-nav-ghost"><span>See how it works</span></a>
        </div>
      </div>
"""

P1_FAQ = [
    ("Can I download all my Canvas courses at once?",
     'Not with anything built into Canvas. Canvas zips one course\'s Files tab at '
     'a time, and that zip leaves out Pages, assignments, announcements and '
     'quizzes. Downloading every course in one run needs a tool that talks to the '
     'Canvas API with an access token, such as a script or a desktop app like '
     '<a href="index.html">Canvas Downloader</a>.'),
    ("Why are some course files missing from the Files tab?",
     'Because a file attached directly to a module item or embedded in a Page does '
     'not have to appear in the Files tab. The Files tab lists the course file '
     'store, not everything the course contains, so "Download as Zip" can miss '
     'material you can plainly see in the course.'),
    ("My course has no Files link in the navigation. What now?",
     'Teachers can hide the Files tab, and that removes the built-in bulk download '
     'for that course. You can still open each file through the modules, use a '
     'browser extension on the module page, or use an API-based tool, which reads '
     'the modules rather than the Files tab.'),
    ("Is it legal to download my Canvas course files?",
     'Downloading material you already have access to, for your own study, is '
     'normally fine and it breaks no copy protection. What varies is your '
     "institution's own policy, especially about lecture recordings, and "
     'redistributing course material is not acceptable anywhere. Check your '
     'university\'s rules and see our '
     '<a href="disclaimer.html">acceptable use page</a>.'),
    ("Does downloading files tell my professor anything?",
     'No. Opening or downloading a file you have access to is not reported to your '
     'instructor. Canvas does record page views in its own access logs, exactly as '
     'it does when you browse the course normally.'),
    ("What is a Canvas access token and is it safe to use one?",
     'It is a key you generate yourself in Canvas under Account then Settings, and '
     'it grants exactly what your own account can already reach - your courses, '
     'your files, your grades. It cannot reach other students\' data, it is not '
     'your password, and you can revoke it at any time from the same screen.'),
    ("Can I download Panopto lecture recordings from Canvas?",
     'Not through any Canvas export. Panopto is a separate system that Canvas links '
     'out to, so recordings have to be fetched from Panopto itself. Some tools '
     'handle this; check your institution\'s rules first, because recordings are '
     'the material universities restrict most often.'),
    ("Will these methods work after my course ends?",
     'Only while you can still open the course. Once a course is concluded or your '
     'enrolment ends, the Files tab and the API both stop returning it. That is why '
     'the right time to do this is before the semester ends, not after.'),
]

# ============================================================ PAGE 2 =========

P2_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#howlong">How long you actually keep access</a></li>
          <li><a href="#three">Three different ways access disappears</a></li>
          <li><a href="#lose">What you lose that people regret</a></li>
          <li><a href="#checklist">The checklist, in priority order</a></li>
          <li><a href="#fast">Doing it for every course at once</a></li>
          <li><a href="#recordings">Lecture recordings are the hard part</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">There is no single answer to how long you keep Canvas
      after you graduate, because your university decides it, not Instructure.
      Some keep alumni accounts open for months. Some cut access on the day your
      enrolment ends. A few remove courses while your login still works, which
      is the version that catches people out.</p>

      <p>So the useful question is not how long you have. It is what you will
      wish you had kept, and how quickly you can get it. That takes about twenty
      minutes for a full degree, and it only works while you are still enrolled.</p>

      <h2 id="howlong">How long you actually keep access</h2>

      <p>Find your own answer rather than trusting a number from the internet.
      In order of reliability:</p>

      <ol class="steps">
        <li>Search your university's IT or library site for "Canvas access after
        graduation". Most institutions publish exactly this, because they get
        asked every year.</li>
        <li>Check whether your student email survives graduation. Canvas access
        usually follows the same identity, so if the email goes, Canvas normally
        goes with it.</li>
        <li>Ask the IT service desk directly. This is the only answer that is
        actually binding.</li>
      </ol>

      <div class="note warn">
        <p>Do not assume that being able to log in means your courses are still
        there. Access to the platform and access to a course are two different
        things, and the second one is usually taken away first.</p>
      </div>

      <h2 id="three">Three different ways access disappears</h2>

      <p>They feel the same and they are not, and knowing which one you are
      facing tells you how much time you have.</p>

      <h3>1. The course is concluded</h3>

      <p>The most common one, and it happens every semester regardless of
      graduation. A concluded course moves to your Past Enrolments. You can
      usually still read it, but it becomes read-only and it stops appearing on
      your dashboard. Downloading still works.</p>

      <h3>2. Your enrolment ends</h3>

      <p>The course disappears from your account. Your login may still work
      perfectly, which is why this one surprises people: Canvas looks normal and
      the course is simply gone. Nothing can retrieve it at this point except
      your institution.</p>

      <h3>3. Your account is deactivated</h3>

      <p>You cannot log in at all. This is usually tied to your student identity
      being retired, and it is often the last of the three to happen, sometimes
      months after the other two.</p>

      <p>The practical consequence: waiting until you cannot log in is waiting
      far too long. By then your courses have normally been gone for a while.</p>

      <h2 id="lose">What you lose that people regret</h2>

      <p>Course files are the obvious one, and they are usually the least
      painful, because a classmate probably has a copy. The things that are
      genuinely irreplaceable are the ones nobody thinks about:</p>

      <ul>
        <li><strong>Feedback on your own work.</strong> The comments an examiner
        wrote on your thesis draft exist in exactly one place.</li>
        <li><strong>Your submitted files.</strong> Especially anything you wrote
        on a laptop you no longer own.</li>
        <li><strong>Grades per assignment.</strong> Your transcript has the final
        mark, not the breakdown.</li>
        <li><strong>Lecture recordings.</strong> Almost never re-shareable after
        the fact, and often gone before the course is.</li>
        <li><strong>Assignment briefs and rubrics.</strong> Useful for years
        afterwards when you need to show what you actually did.</li>
        <li><strong>Discussion threads.</strong> Where the answer to the confusing
        part of the course usually lives.</li>
      </ul>

      <h2 id="checklist">The checklist, in priority order</h2>

      <p>Ordered by how hard each item is to replace, not by how easy it is to
      grab. Work down it and stop whenever you run out of patience: you will
      still have the parts that matter.</p>

      <ol class="steps">
        <li><strong>Your submissions and their feedback.</strong> Start here. It
        is the only category no one else can give you.</li>
        <li><strong>Lecture recordings</strong>, if your course has them and your
        institution allows you to keep them.</li>
        <li><strong>Course files</strong> - slides, readings, worksheets.</li>
        <li><strong>Assignment briefs and rubrics.</strong></li>
        <li><strong>Announcements and discussions</strong>, which often carry
        corrections that never made it into the slides.</li>
        <li><strong>The syllabus</strong> for each course, which is what you will
        need if you ever apply for credit transfer or exemptions.</li>
      </ol>

      <div class="note good">
        <p>Do this for your current courses too, not only the finished ones. The
        semester that is running now is the one you have the most of, and it will
        conclude like all the others.</p>
      </div>

      <h2 id="fast">Doing it for every course at once</h2>

      <p>By hand, this is an afternoon: Canvas exports one course's Files tab at
      a time, and it does not export assignments, announcements, quizzes or your
      feedback at all. Our
      <a href="how-to-download-all-canvas-files.html">comparison of every
      download method</a> goes through each option and where it stops.</p>

      <p>The short version: for one or two courses, use Canvas's own
      <strong>Download as Zip</strong> and be done. For a whole degree, use
      something that reads your account through the Canvas API, because that is
      the only way to get the categories Canvas has no export for.</p>

      <div class="cta-box">
        <h3>Save every course before access ends</h3>
        <p>Canvas Downloader collects every file, plus assignments, announcements,
        discussions, quizzes and your own feedback, from every course you pick.
        Free and open source, Windows and macOS.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="how-to-download-all-canvas-files.html" class="btn-nav-ghost"><span>Compare all methods</span></a>
        </div>
      </div>

      <h2 id="recordings">Lecture recordings are the hard part</h2>

      <p>Recordings usually live in Panopto rather than in Canvas, which means
      they are governed separately, they often expire on their own schedule, and
      no Canvas export has ever included them.</p>

      <p>They are also the material universities are strictest about. Many
      institutions permit personal study copies and forbid sharing; some forbid
      downloading entirely. Check your own rules before you save anything, and
      treat a recording as the most restricted thing in your course rather than
      the least. Our <a href="disclaimer.html">acceptable use page</a> sets out
      the same expectation.</p>

      <p>If you are allowed to keep them, a transcript is worth as much as the
      video and takes a fraction of the space. It is also searchable, which the
      video is not.</p>
"""

P2_FAQ = [
    ("How long do I have access to Canvas after I graduate?",
     'It depends entirely on your university, not on Canvas. Some keep access for '
     'months after graduation, some end it the day your enrolment does, and some '
     'remove your courses while your login still works. Search your own IT or '
     'library site for "Canvas access after graduation", or ask the service desk, '
     'because only your institution can answer it.'),
    ("Can I still download files from a concluded course?",
     'Usually yes. A concluded course becomes read-only and moves to Past '
     'Enrolments, but you can generally still open and download from it. What stops '
     'working is a course your enrolment has been removed from, which disappears '
     'entirely even though your login still works.'),
    ("I can log into Canvas but my courses are gone. Can I get them back?",
     'Not by yourself. Losing the course while keeping the login means your '
     'enrolment ended, and only your institution can restore it. It is worth '
     'asking the service desk, because some can reinstate access temporarily on '
     'request, but there is nothing you can do from your own account.'),
    ("What should I download first if I am short on time?",
     'Your own submitted work and the feedback on it. Everything else is likely to '
     'exist somewhere else - a classmate, a course page, next year\'s edition - but '
     'the comments an examiner wrote on your work exist only in your Canvas '
     'account.'),
    ("Does my university keep a copy for me?",
     'Your transcript and your formal record, yes. Course content, feedback and '
     'recordings, almost never in a form you can request later. Assume anything '
     'you have not downloaded is gone once access ends.'),
    ("Can I download lecture recordings before I lose access?",
     'Technically they are reachable while you still have access, but recordings '
     'are the material institutions restrict most, and the rules differ from one '
     'university to the next. Check your own policy first: many allow a personal '
     'study copy and forbid sharing, and some do not allow downloading at all.'),
    ("Is there a way to save everything from all my courses at once?",
     'Nothing built into Canvas does it. Canvas zips one course\'s Files tab at a '
     'time and does not export assignments, announcements or feedback. A tool that '
     'uses the Canvas API can cover every course and those extra categories in one '
     'run - see our <a href="how-to-download-all-canvas-files.html">comparison of '
     'every method</a>.'),
]

# ============================================================ PAGE 3 =========
# Facts checked 2026-08-20:
#  * Panopto student downloads are OFF BY DEFAULT. Only a recording's creator and
#    administrators can download unless a Creator changes the setting, which they
#    can do per folder, per subfolder or per recording. Sources: Stanford Canvas
#    Help 360047508074, Cambridge UIS lecture-capture guidance, Bryn Mawr Ask
#    Athena, Shoreline KB 2026.
#  * When enabled, viewers get a download option under the three-dots menu in the
#    player. When not enabled, no button appears at all.
#
# THIS PAGE MUST LEAD WITH THE PERMISSION QUESTION, NOT WITH CAPABILITY, and it
# must not contradict DISCLAIMER.md, which states plainly that the app "does not
# read that setting" and asks users to respect a lecturer's deliberate choice.
# Copy that reads as a workaround would misrepresent the product and would be the
# one page on this site capable of causing a reader real harm.

P3_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#where">Why no Canvas download includes your lectures</a></li>
          <li><a href="#button">First, check whether the download button is there</a></li>
          <li><a href="#ask">If it is not there, ask. That is the real answer.</a></li>
          <li><a href="#rules">What your institution allows</a></li>
          <li><a href="#app">What Canvas Downloader does, stated exactly</a></li>
          <li><a href="#formats">Video, audio, transcript or just a link</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">Lecture recordings are the one part of a course that no
      Canvas export has ever included, and the part students most want to keep.
      They are also the material universities restrict most carefully, so this
      page deals with the permission question before the how.</p>

      <h2 id="where">Why no Canvas download includes your lectures</h2>

      <p>Panopto is a separate system. Canvas only links out to it: what you
      click inside a module is a launch into Panopto, not a file stored in your
      course. So when you zip a course's Files tab, or use any of the
      <a href="how-to-download-all-canvas-files.html">other Canvas download
      methods</a>, the recordings are not in scope. There is nothing to
      include.</p>

      <p>It is also why recordings can vanish on their own schedule. Panopto
      folders usually carry a retention policy set by the institution, and it is
      independent of your Canvas access. A recording can be gone while the course
      is still open to you.</p>

      <h2 id="button">First, check whether the download button is there</h2>

      <p>Panopto has a built-in download. If it is switched on for your course,
      that is the whole answer and you need nothing else.</p>

      <ol class="steps">
        <li>Open the recording in the Panopto player, either inside Canvas or on
        your institution's Panopto site.</li>
        <li>Look for the three-dots menu in the upper right of the player.</li>
        <li>If a download option is listed, use it. You are usually offered the
        video, and often an audio-only version.</li>
      </ol>

      <div class="note warn">
        <p><strong>Expect it to be missing.</strong> Panopto ships with student
        downloads turned <strong>off</strong>: by default only the person who
        created the recording, and administrators, can download it. A lecturer
        can switch it on for a whole folder, one subfolder, or a single
        recording. If nobody has, you will see no button at all, and its absence
        is not a fault.</p>
      </div>

      <h2 id="ask">If it is not there, ask. That is the real answer.</h2>

      <p>It sounds like the boring option and it is the one that works. Enabling
      downloads is about two clicks in a folder's settings, most lecturers have
      never considered the setting, and a request framed around revision rather
      than convenience is rarely refused.</p>

      <div class="note">
        <p>"Would you be willing to enable downloads on the Panopto folder for
        this course? I revise offline and I would find it much easier to work
        from the recordings than from my notes. Happy for it to be just the
        lectures rather than everything."</p>
      </div>

      <p>Two things worth knowing before you send that. Some institutions lock
      the setting centrally, so your lecturer may be unable to say yes even if
      they want to. And if a lecturer says no, that is an answer: they may be
      protecting third-party material inside the recording, or the privacy of
      students who can be heard on it.</p>

      <h2 id="rules">What your institution allows</h2>

      <p>There is no single rule, and this is not a formality. Policies differ
      more here than anywhere else in a course:</p>

      <ul>
        <li>Many institutions allow a <strong>personal study copy</strong> and
        prohibit sharing it. This is the most common position.</li>
        <li>Some prohibit downloading entirely, and say so in a course handbook
        or a lecture-capture policy rather than anywhere in Canvas.</li>
        <li>Nearly all prohibit redistribution, including uploading to a shared
        drive, a group chat or a note-sharing site. That is the one that causes
        real trouble, and the easiest to do without thinking.</li>
      </ul>

      <p>Search your university's site for "lecture capture policy" or "Panopto
      policy". If you find nothing, ask, rather than reading the silence as
      permission.</p>

      <h2 id="app">What Canvas Downloader does, stated exactly</h2>

      <p>This is our site, so here is the mechanism rather than a claim, and
      every word of it is checkable in
      <a href="https://github.com/BrkBuilds/Canvas-Downloader" target="_blank"
      rel="noopener">the source</a>.</p>

      <p>When you open a Panopto link inside Canvas, your browser performs a
      sign-in handshake and then plays the recording. The app performs
      <strong>the same handshake your browser performs</strong> and saves the
      same stream the player would have sent you. It breaks no encryption and
      contains no decryption of any kind. It can only reach a recording your own
      account is already permitted to watch, and if Panopto refuses a request it
      reports the refusal and moves on.</p>

      <div class="note warn">
        <p><strong>The part you need to know:</strong> the app does
        <strong>not</strong> read Panopto's download-button setting. It saves the
        stream whether or not that button has been switched on. Many institutions
        leave the setting off site-wide without any deliberate decision ever being
        made about a particular lecture, which is why the app works this way and
        why the judgement is handed to you rather than made for you.</p>
        <p style="margin-top:10px;">So: where a lecturer has clearly made a
        choice, respect it. Where your institution's policy prohibits it, follow
        the policy. The full position is on our
        <a href="disclaimer.html">acceptable use page</a>, and the app shows you
        the same notice before it will fetch anything.</p>
      </div>

      <h2 id="formats">Video, audio, transcript or just a link</h2>

      <p>A semester of lecture video is enormous, and video is the least useful
      form of it for revision because you cannot search it. Each recording can be
      saved as any combination of five things:</p>

      <ul>
        <li><strong>Video (MP4)</strong> - the full recording. Largest by far.</li>
        <li><strong>Audio (MP3)</strong> - a fraction of the size and enough for
        anything that is not a slide walkthrough.</li>
        <li><strong>Transcript (.txt)</strong> - the spoken content as text.
        Searchable, tiny, and the format most study tools accept.</li>
        <li><strong>Subtitles (.srt)</strong> - the same text with timestamps, so
        you can jump to the moment in the recording instead of reading all of
        it.</li>
        <li><strong>Shortcut</strong> - a link file that opens the lecture back in
        Panopto. No bandwidth, no disk and no permission question, and it keeps
        the slides and the search Panopto provides. It stops working when your
        access does, which is exactly when people want an offline copy, so treat
        it as a companion rather than a substitute.</li>
      </ul>

      <p>Transcripts and subtitles are produced <strong>on your own
      computer</strong> by an offline speech-recognition model. The recording is
      never uploaded to be transcribed. The first run downloads the model, which
      takes a few minutes; after that it works with no network at all.</p>

      <div class="cta-box">
        <h3>Keep your lectures in a form you can revise from</h3>
        <p>Free and open source, Windows and macOS. Read the acceptable use page
        first: recordings are the one part of a course where the rules genuinely
        differ between universities.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="disclaimer.html" class="btn-nav-ghost"><span>Acceptable use</span></a>
        </div>
      </div>
"""

P3_FAQ = [
    ("Why can I not download my Panopto lecture?",
     "Because student downloads are off by default. Panopto ships with only the "
     "recording's creator and administrators able to download it, and a lecturer "
     "has to switch it on for the folder or the individual recording. If nobody "
     "has, the player shows no download option at all."),
    ("How do I ask my lecturer to enable Panopto downloads?",
     "Ask them to open the Panopto folder for the course, go to folder settings, "
     "and change the download setting so viewers can download. It is about two "
     "clicks. Some institutions lock the setting centrally, so your lecturer may "
     "not be able to change it even if they are willing."),
    ("Is it legal to download a lecture recording?",
     "It depends on your institution, and this is where policies differ most. "
     "Many universities allow a personal study copy and prohibit sharing; some "
     "prohibit downloading entirely. Redistribution is prohibited essentially "
     "everywhere. Check your lecture capture policy, and ask if you cannot find "
     "one."),
    ("Does downloading a recording tell my lecturer?",
     "Panopto records viewing statistics that lecturers can see, in the same way "
     "it records that you watched. Nothing announces a download specifically. "
     "That is not a reason to treat a restriction as optional."),
    ("Can I get just the transcript instead of the video?",
     "Yes, and for revision it is usually the better choice. A transcript is "
     "searchable, it is a rounding error in size next to the video, and it is the "
     "format most study tools accept. Canvas Downloader can produce a transcript "
     "and subtitles without keeping the video at all."),
    ("Does transcription upload my lecture anywhere?",
     "No. Transcription runs on your own computer using an offline speech "
     "recognition model. The first run downloads the model itself, and after that "
     "it works with no network connection."),
    ("Why are my lecture recordings missing from a Canvas download?",
     "Because they are not Canvas files. Panopto is a separate system and Canvas "
     "only links out to it, so no Canvas export or zip has ever included "
     "recordings. They have to be fetched from Panopto itself."),
    ("My recordings disappeared before the course ended. Why?",
     "Panopto folders usually have a retention policy set by the institution, and "
     "it is independent of your Canvas access. A recording can be removed while "
     "the course is still open to you, which is why recordings are worth dealing "
     "with earlier than the rest of a course."),
]

# ============================================================ PAGE 4 =========
# Grounded 2026-08-23. The load-bearing fact is that Canvas DOES have a
# student-side bulk export of submissions (Account > Settings > Download
# Submissions > Create Export), and that it contains none of the feedback:
# Instructure KB 661234 states it covers current and concluded courses, holds
# only the files submitted plus text entries saved as HTML, and explicitly
# excludes instructor-modified (annotated) submissions, grades, comments,
# discussions and quizzes, and that exports expire after 30 days. The
# annotation half is Instructure KB 661231 and 661230: annotations are shown by
# DocViewer behind a "View Feedback" button, downloading from DocViewer flattens
# them into a PDF, and a file that offers "Preview" instead is not DocViewer
# compatible and carries no annotations at all.

P4_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#export">The export Canvas does give you</a></li>
          <li><a href="#missing">What it leaves out, which is the important half</a></li>
          <li><a href="#where">Where each kind of feedback actually lives</a></li>
          <li><a href="#annotations">Saving inline annotations</a></li>
          <li><a href="#comments">Saving comments, rubrics and grades</a></li>
          <li><a href="#order">The order to do this in</a></li>
          <li><a href="#when">When to do it</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">Canvas will hand you every file you ever submitted, in one
      click, for every course you have taken. It will not hand you a single word
      your instructor wrote back. That asymmetry catches almost everybody, and it
      matters because the feedback is the half you cannot reconstruct.</p>

      <p>Your own essays are already on your laptop somewhere. The three
      paragraphs explaining why the argument in section two did not hold, the
      marked-up PDF, the rubric with the examiner's note against each criterion -
      those exist in exactly one place, and that place stops being yours on a
      date nobody tells you.</p>

      <h2 id="export">The export Canvas does give you</h2>

      <p>This one is genuinely good and very few students know it exists. It is
      not per course - it covers everything you have ever submitted.</p>

      <ol class="steps">
        <li>Click <strong>Account</strong> in the global navigation on the far
        left.</li>
        <li>Click <strong>Settings</strong>.</li>
        <li>In the sidebar on the right, click <strong>Download Submissions</strong>.</li>
        <li>Click <strong>Create Export</strong> and wait. Large accounts take a
        while.</li>
        <li>Download the ZIP when it appears.</li>
      </ol>

      <p>What arrives is every file you uploaded to an assignment, across
      <strong>current and concluded courses</strong>, plus anything you typed
      into the rich text editor saved as an HTML file. Group assignments are
      included even where a team mate did the submitting.</p>

      <div class="note warn">
        <p><strong>The export expires after 30 days.</strong> It is generated on
        request and then deleted, so this is not a link you can bookmark and
        come back to after graduation. Generate it and save the ZIP somewhere
        permanent the same day.</p>
      </div>

      <h2 id="missing">What it leaves out, which is the important half</h2>

      <p>The export contains your work and nothing about how it was received.
      Specifically, none of this is in it:</p>

      <ul>
        <li><strong>Inline annotations.</strong> The comments drawn directly on
        your PDF or essay. Canvas is explicit that instructor-modified
        submissions are excluded, so what you get back is the pristine file you
        uploaded, not the marked-up one.</li>
        <li><strong>Assignment comments.</strong> The conversation thread beside
        the submission, including audio and video comments.</li>
        <li><strong>Rubrics.</strong> The graded grid, and any per-criterion
        remarks in it.</li>
        <li><strong>Grades and scores.</strong> Not in the ZIP at all.</li>
        <li><strong>Discussions and quizzes.</strong> Neither your posts nor your
        quiz attempts, so a course graded largely on participation exports as
        very little.</li>
      </ul>

      <p>So the export is a good first move and a bad last one. Run it, then go
      and collect the feedback separately.</p>

      <h2 id="where">Where each kind of feedback actually lives</h2>

      <p>Canvas scatters feedback across three different places on one screen,
      which is why it is easy to save one kind and never notice the others. Open
      any graded assignment and you are looking at all three at once.</p>

      <div class="tbl-wrap" tabindex="0" role="region" aria-label="Where Canvas keeps each kind of feedback">
        <table class="cmp">
          <thead>
            <tr><th>Feedback</th><th>Where it is</th><th>In the export?</th></tr>
          </thead>
          <tbody>
            <tr><td>Marks on the document</td><td>DocViewer, behind <strong>View Feedback</strong></td><td class="no">No</td></tr>
            <tr><td>Written comments</td><td>Comment sidebar on the submission</td><td class="no">No</td></tr>
            <tr><td>Audio and video comments</td><td>Same sidebar, played in Canvas</td><td class="no">No</td></tr>
            <tr><td>Rubric with criterion notes</td><td>Submission details page</td><td class="no">No</td></tr>
            <tr><td>Grade and score</td><td>Grades page</td><td class="no">No</td></tr>
            <tr><td>The file you submitted</td><td>Your own upload</td><td class="yes">Yes</td></tr>
          </tbody>
        </table>
      </div>

      <h2 id="annotations">Saving inline annotations</h2>

      <p>Annotations are the ones people most want and most often lose, because
      they are not part of your file. Canvas renders them in a viewer on top of
      it, so downloading the file from your own submission gives you a clean copy
      with nothing on it.</p>

      <ol class="steps">
        <li>Open <strong>Grades</strong>, then click the assignment name.</li>
        <li>On the submission details page, look for
        <strong>View Feedback</strong>.</li>
        <li>The document opens in DocViewer with the annotations on it.</li>
        <li>Click <strong>Download</strong>. You get a PDF with the annotations
        flattened into the page, which is exactly what you want.</li>
      </ol>

      <div class="note">
        <p><strong>If the button says "Preview" rather than "View Feedback",
        stop looking.</strong> That means the file type is not DocViewer
        compatible, and a file DocViewer cannot open is a file nobody annotated.
        There is nothing to save; check the comment sidebar instead, which is
        where the feedback for those submissions ends up.</p>
      </div>

      <p>Do this per assignment. It is tedious and there is no bulk version, so
      be selective: the assignments worth ten minutes of your time are the ones
      whose feedback you would actually reread.</p>

      <h2 id="comments">Saving comments, rubrics and grades</h2>

      <p>These have no download button anywhere, which surprises people who
      assume feedback must be exportable somehow. Your options are ordinary ones.</p>

      <p><strong>Print the submission details page to PDF.</strong> The browser's
      print dialogue offers "Save as PDF" as a destination on every platform, and
      the submission details page carries the rubric, the score and the comment
      thread together. One page, one PDF, and it captures all three at once.
      Expand every comment first; a collapsed thread prints collapsed.</p>

      <p><strong>Audio and video comments need a different approach.</strong>
      They play inside Canvas and there is no save option. If a recorded comment
      matters, play it and write down what it says. That sounds primitive and it
      is the only reliable answer.</p>

      <p><strong>Grades.</strong> There is no student-side CSV export of your own
      grades. Print the Grades page to PDF per course, which also captures the
      per-assignment scores and any comment icons.</p>

      <h2 id="order">The order to do this in</h2>

      <p>If you have twenty courses and an afternoon, do it in this order. It is
      sorted by how permanently the thing disappears, not by how much of it there
      is.</p>

      <ol class="steps">
        <li><strong>Run the submissions export first</strong>, because it is one
        click and it runs while you do everything else.</li>
        <li><strong>Annotated documents</strong>, for assignments that mattered.
        Irrecoverable and per-assignment.</li>
        <li><strong>Submission detail pages</strong> for those same assignments,
        printed to PDF. Catches rubric, score and comments in one go.</li>
        <li><strong>Recorded comments</strong>, transcribed by hand where they
        were substantive.</li>
        <li><strong>Grades pages</strong>, one PDF per course.</li>
        <li><strong>The course material itself</strong> - slides, readings,
        recordings - which is a separate job. See
        <a href="how-to-download-all-canvas-files.html">how to download all your
        files from Canvas</a>.</li>
      </ol>

      <h2 id="when">When to do it</h2>

      <p>Before the course concludes, not after. A concluded course usually goes
      read-only, and read-only is survivable: you can still open it and still
      print. What is not survivable is the enrolment ending, at which point the
      course leaves your dashboard entirely and neither the submission page nor
      the export can reach it.</p>

      <p>The dates differ by institution and nobody emails you about them.
      <a href="canvas-access-after-graduation.html">Canvas access after
      graduation</a> covers the three separate ways access ends and roughly when
      each one bites.</p>

      <div class="cta-box">
        <h3>Saving the feedback with everything else</h3>
        <p>Canvas Downloader can save assignment feedback as it downloads a
        course: the grade and score, the rubric with its per-criterion comments,
        the full comment thread, and any file a teacher attached to a comment -
        one readable page per assignment, alongside the course material.</p>
        <p>It does <strong>not</strong> capture inline annotations. Those are
        drawn inside DocViewer rather than stored on the file, so the per-
        assignment Download button above is still the way to keep those.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="guide.html" class="btn-nav-ghost"><span>See how it works</span></a>
        </div>
      </div>
"""

P4_FAQ = [
    ("Can I download all my Canvas feedback at once?",
     'No. Canvas has a one-click export of your submissions - Account, then '
     'Settings, then Download Submissions - but it deliberately excludes '
     'annotated submissions, comments, rubrics and grades. There is no built-in '
     'bulk export of feedback, so it has to be collected per assignment.'),
    ("Does the Canvas submissions export include my grades?",
     'No. The ZIP holds the files you uploaded and any text-entry answers saved '
     'as HTML, for current and concluded courses. It contains no grades, no '
     'instructor comments and no annotated versions of your work.'),
    ("Why does my assignment show Preview instead of View Feedback?",
     'Because that file type is not compatible with Canvas DocViewer, which is '
     'the tool that displays annotations. If you only see Preview, there are no '
     'inline annotations to save on that submission, so check the comment '
     'sidebar instead.'),
    ("How do I download a PDF with my instructor's annotations on it?",
     'Open the assignment from Grades, click View Feedback to open the document '
     'in DocViewer, then click Download. The PDF you get has the annotations '
     'flattened into the page. Downloading the file from your own submission '
     'instead gives you the clean copy you uploaded, with nothing on it.'),
    ("Will my feedback disappear when the course ends?",
     'Eventually. A concluded course normally becomes read-only, so you can '
     'still open and print it. Once your enrolment ends the course leaves your '
     'account altogether, and at that point neither the submission page nor the '
     'export can reach it.'),
    ("Can I save audio or video comments from my instructor?",
     'Not directly - recorded comments play inside Canvas and have no download '
     'option. If a recorded comment is substantive, the practical answer is to '
     'play it and write down what it says while you still can.'),
    ("How long does the submissions export stay available?",
     'Thirty days. Canvas generates the ZIP on request and deletes it after '
     'that, so save the file somewhere permanent the same day rather than '
     'treating the export page as storage.'),
    ("Does downloading my feedback notify my instructor?",
     'No. Opening or downloading your own submission and its feedback is not '
     'reported to anyone. Canvas records page views in its own access logs '
     'exactly as it does when you browse a course normally.'),
]

# ============================================================ PAGE 5 =========
# Grounded 2026-08-23, and the premise CHANGED on investigation - see
# marketing/FINDINGS.md, where this page was deferred because it was going to be
# built on "NotebookLM cannot read Office files", which stopped being true in
# November 2025. Google's own announcement added .docx, Google Sheets, Drive
# URLs and images; .pptx is supported as well. So the page is framed on what
# does NOT change: NotebookLM cannot reach Canvas, the source cap makes
# curation the real skill, and video is the one genuine conversion problem
# because local video is not an accepted source type while audio is.
# Free tier at the time of writing: 50 sources per notebook, 100 notebooks,
# 50 chats a day, 3 Audio Overviews a day; per source 500,000 words or 200 MB,
# whichever comes first. Numbers move, so the page states them as current
# rather than as permanent.

P5_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#gap">The part nobody explains</a></li>
          <li><a href="#accepts">What NotebookLM accepts</a></li>
          <li><a href="#cap">Why the source limit changes what you upload</a></li>
          <li><a href="#getting">Getting the files out of Canvas first</a></li>
          <li><a href="#lectures">Lecture recordings, the one real conversion problem</a></li>
          <li><a href="#recipe">A recipe for one course</a></li>
          <li><a href="#weak">Where it is genuinely weak</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">NotebookLM is very good at the thing students want from it:
      answering questions from your own course material, with citations back to
      the source. There is one obstacle in front of that, and every guide skips
      it. NotebookLM cannot see your Canvas courses. It has no integration, no
      login, no way in. Everything has to be a file on your computer first.</p>

      <p>Which means the hard part of "use AI on my course material" is not the
      AI at all. It is the twenty minutes of clicking that gets four months of
      slides, readings and lecture recordings out of Canvas and into a folder.</p>

      <h2 id="gap">The part nobody explains</h2>

      <p>Canvas keeps your material behind a login, spread across a Files tab,
      module attachments, Pages and a separate lecture capture system. NotebookLM
      takes uploads. Nothing bridges those two automatically, so the workflow is
      always: get the files down, tidy them, then upload.</p>

      <p>That has one useful consequence. Once the files are on your machine they
      are yours permanently, and you can put them into whichever tool you like -
      NotebookLM today, something else next year, and your own reading in the
      meantime. The download is the durable part; the AI tool is not.</p>

      <h2 id="accepts">What NotebookLM accepts</h2>

      <p>The format situation is much better than it was. Word and PowerPoint
      were both added during 2025, which removed the conversion step that used to
      make this awkward. As things stand it takes:</p>

      <ul>
        <li><strong>Documents</strong> - PDF, <code>.docx</code>,
        <code>.pptx</code>, <code>.txt</code>, <code>.md</code>, CSV.</li>
        <li><strong>Google files</strong> - Docs, Slides and Sheets, plus Drive
        links.</li>
        <li><strong>Audio</strong> - MP3, M4A and WAV, transcribed on upload.</li>
        <li><strong>Images</strong>, pasted text, web page URLs, and public
        YouTube links.</li>
      </ul>

      <p>Per source you get up to 500,000 words or 200 MB, whichever you hit
      first, which no normal lecture deck or reading comes close to.</p>

      <div class="note warn">
        <p><strong>Local video files are not on that list.</strong> You can point
        it at a public YouTube URL, but a lecture recording saved as MP4 cannot
        be uploaded. That is the one place a conversion step is still genuinely
        required, and it is covered below.</p>
      </div>

      <h2 id="cap">Why the source limit changes what you upload</h2>

      <p>A free notebook holds <strong>50 sources</strong>. Paid plans raise it.
      Fifty sounds generous until you try to put a whole degree in one notebook
      and discover that a single semester of one course is already thirty files.</p>

      <p>So the cap pushes you toward the right habit anyway:
      <strong>one notebook per course</strong>. Grounding quality points the same
      direction. Ask a question of a notebook holding one course and the answer
      comes from that course's own material and cites it. Ask the same question
      of a notebook holding four unrelated courses and you get confident answers
      assembled from the wrong module.</p>

      <p>Curation is the actual skill here, and it is worth being ruthless. A
      semester folder straight off Canvas contains a lot that is not study
      material: administrative announcements, the same reading list posted three
      times, the assignment brief you already submitted against.</p>

      <h2 id="getting">Getting the files out of Canvas first</h2>

      <p>How much work this is depends entirely on where your course keeps its
      material. If everything is in the Files tab, Canvas will zip it for you and
      you are five minutes from done. If it is attached to modules or embedded in
      Pages, the Files tab does not contain it and the zip will quietly not
      include it.</p>

      <p><a href="how-to-download-all-canvas-files.html">How to download all your
      files from Canvas</a> covers every route in detail, including the built-in
      ones that need no software. Start there, and only reach for a tool if the
      built-in export leaves too much behind.</p>

      <h2 id="lectures">Lecture recordings, the one real conversion problem</h2>

      <p>A recorded lecture is the single most useful thing you can give
      NotebookLM, because it is where most of the actual explanation lives and it
      is the material you are least likely to reread. It is also the one thing
      you cannot upload as it comes.</p>

      <p>Two routes work, and one is clearly better:</p>

      <ul>
        <li><strong>Audio.</strong> Extract the audio track as MP3 and upload
        that. NotebookLM transcribes it on the way in - a half-hour recording
        takes a couple of minutes. Simple, and it costs you one source.</li>
        <li><strong>A transcript.</strong> Better. A text transcript is tiny,
        searchable in your own folder, quotable in your notes, readable without
        any AI tool at all, and it is what NotebookLM was going to produce
        internally anyway.</li>
      </ul>

      <p>Either way, remember that lecture recordings are the material
      universities restrict most often, and the permission question is a real one
      rather than a formality. See
      <a href="download-panopto-lecture-recordings.html">how to download Panopto
      lecture recordings</a>, which leads with exactly that.</p>

      <h2 id="recipe">A recipe for one course</h2>

      <ol class="steps">
        <li>Download the course to a folder on your computer.</li>
        <li>Delete the administrative noise - announcements about room changes,
        duplicated reading lists, the assignment briefs you have already
        submitted against.</li>
        <li>Turn any lecture recordings into transcripts or MP3s.</li>
        <li>Create a notebook named after the course. One course, one
        notebook.</li>
        <li>Upload the slides and readings first, then the transcripts. You will
        usually land somewhere between fifteen and forty sources, which fits.</li>
        <li>Ask it for a study guide, or a timeline of the topics, or the three
        questions most likely to come up. Then check the citations, which is the
        whole point of a grounded tool.</li>
      </ol>

      <div class="note good">
        <p><strong>Keep the folder, not just the notebook.</strong> The notebook
        is a view over your sources and it depends on somebody else's product
        staying free and staying available. The folder on your disk is the thing
        that is actually yours, and it will still open in ten years.</p>
      </div>

      <h2 id="weak">Where it is genuinely weak</h2>

      <p>It answers from what you gave it, so a gap in your folder is a gap in
      its answers, stated just as confidently as everything else. If half the
      course was delivered verbally and you uploaded only the slides, it will
      cheerfully summarise the slides and never mention the rest.</p>

      <p>It is also not a shortcut past your institution's rules. Policies on
      using AI tools with course material vary a great deal, they are usually
      stricter for assessed work than for revision, and a few explicitly cover
      uploading lecture material to third-party services. Check yours before
      building a workflow on it.</p>

      <div class="cta-box">
        <h3>Get the folder first</h3>
        <p>Canvas Downloader pulls a whole course down in one run and can convert
        as it goes: Office files to PDF, Canvas Pages to Markdown, and lecture
        recordings to audio or a searchable transcript - which is close to a
        list of what NotebookLM accepts.</p>
        <p>You do not need it. If your course keeps everything in the Files tab,
        Canvas will zip it and that is genuinely simpler.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="guide.html" class="btn-nav-ghost"><span>See how it works</span></a>
        </div>
      </div>
"""

P5_FAQ = [
    ("Can NotebookLM connect to Canvas directly?",
     'No. There is no Canvas integration and no way for NotebookLM to log in to '
     'your account. Course material has to be downloaded to your computer first '
     'and then uploaded as sources, which is why getting the files out of Canvas '
     'is the real work.'),
    ("Can I upload a lecture video to NotebookLM?",
     'Not a local video file. It accepts audio - MP3, M4A and WAV - and public '
     'YouTube links, so a recorded lecture needs to become audio or a transcript '
     'first. A transcript is usually the better choice: it is smaller, '
     'searchable in your own folder and readable without any AI tool.'),
    ("Does NotebookLM read PowerPoint and Word files?",
     'Yes. Both were added during 2025, so .pptx and .docx upload directly '
     'alongside PDF, plain text, Markdown, CSV and Google Docs, Slides and '
     'Sheets. The conversion step older guides describe is no longer needed for '
     'ordinary documents.'),
    ("How many files can I put in one notebook?",
     'Fifty sources per notebook on the free plan, with paid plans raising the '
     'limit. Each source can run to 500,000 words or 200 MB, whichever comes '
     'first, which no normal lecture deck approaches.'),
    ("Should I make one notebook per course or one per semester?",
     'Per course. The source limit pushes you that way and so does answer '
     'quality: a notebook holding one course cites that course, while a notebook '
     'holding four produces confident answers assembled from the wrong module.'),
    ("Is it safe to upload my course material to NotebookLM?",
     'That is a question about Google\'s terms and your institution\'s policy '
     'rather than a technical one. Policies vary, are usually stricter for '
     'assessed work than for revision, and some explicitly cover uploading '
     'lecture material to third-party services. Check yours first.'),
    ("Will NotebookLM make things up about my course?",
     'It answers from the sources you give it and cites them, which makes it '
     'much easier to check than a general chatbot. The real failure mode is a '
     'gap in your folder: material you did not upload simply will not appear in '
     'the answers, and nothing flags that it is missing.'),
    ("What should I not bother uploading?",
     'Administrative announcements, duplicated reading lists, assignment briefs '
     'you have already submitted against, and anything you would not reread. '
     'With a source limit, every slot spent on noise is a slot not spent on a '
     'lecture transcript.'),
]

# ============================================================================

PAGES = [
    dict(
        slug="how-to-download-all-canvas-files.html",
        title="How to Download All Files From Canvas (5 Methods Compared)",
        description=("Every way to get your Canvas course files onto your computer, "
                     "compared: Download as Zip, submissions, browser extensions, "
                     "scripts and a desktop app."),
        h1="How to download all your files from Canvas",
        lede=("Canvas has no button that downloads everything. Here is every route "
              "that works, what each one really collects, and which to pick."),
        crumb="How to download all your files from Canvas",
        body=P1_BODY, faq=P1_FAQ, extra_nodes=[],
        published="2026-08-20", modified="2026-08-20",
    ),
    dict(
        slug="canvas-access-after-graduation.html",
        title="Canvas Access After Graduation: What to Save Before It Ends",
        description=("How long you keep Canvas after graduating, the three ways "
                     "access disappears, and a checklist for saving your courses, "
                     "feedback and recordings first."),
        h1="Canvas access after graduation",
        lede=("How long you keep it, the three different ways it disappears, and "
              "what to save first while you still can."),
        crumb="Canvas access after graduation",
        body=P2_BODY, faq=P2_FAQ, extra_nodes=[],
        published="2026-08-20", modified="2026-08-20",
    ),
    dict(
        slug="download-panopto-lecture-recordings.html",
        title="How to Download Panopto Lecture Recordings",
        description=("Why Panopto downloads are off by default, how to get them "
                     "enabled, what your university allows, and how to keep a "
                     "lecture as video, audio or a searchable transcript."),
        h1="How to download Panopto lecture recordings",
        lede=("Downloads are off by default, and the permission question comes "
              "first. How to check, how to ask, and what you can keep."),
        crumb="Download Panopto lecture recordings",
        body=P3_BODY, faq=P3_FAQ, extra_nodes=[],
        published="2026-08-20", modified="2026-08-20",
    ),
    dict(
        slug="save-canvas-assignment-feedback.html",
        title="How to Save Your Canvas Assignment Feedback",
        description=("Canvas exports your submissions in one click but not the "
                     "feedback on them. How to save annotations, comments and "
                     "rubrics before access ends."),
        h1="How to save your Canvas assignment feedback",
        lede=("Canvas hands back every file you submitted. It hands back nothing "
              "your instructor wrote, and that is the half you cannot rebuild."),
        crumb="Save your Canvas assignment feedback",
        body=P4_BODY, faq=P4_FAQ, extra_nodes=[],
        published="2026-08-23", modified="2026-08-23",
    ),
    dict(
        slug="canvas-files-into-notebooklm.html",
        title="How to Get Your Canvas Files Into NotebookLM",
        description=("What NotebookLM accepts, why it cannot reach Canvas, how to "
                     "choose sources that matter, and what to do with lecture "
                     "recordings."),
        h1="How to get your Canvas files into NotebookLM",
        lede=("NotebookLM cannot see your Canvas courses. Everything has to be a "
              "file on your computer first, and that is the part guides skip."),
        crumb="Canvas files into NotebookLM",
        body=P5_BODY, faq=P5_FAQ, extra_nodes=[],
        published="2026-08-23", modified="2026-08-23",
    ),
]
