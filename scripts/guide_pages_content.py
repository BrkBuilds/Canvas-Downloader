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
      student asked precisely this on the <a class="src" href="https://community.instructure.com/en/discussion/618390/how-to-download-all-course-files-and-media-on-canvas" target="_blank" rel="noopener">Instructure Community forum</a> in October 2024, the accepted answer ended with <em>"As for Pages and
      Assignments, I'm not sure of a quick way off the top of my head."</em>
      That is still the state of it.</p>

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
      arranged them. For a tidy course that is genuinely all you need. This is
      the route university help desks document, and they agree on the steps -
      <a class="src" href="https://answers.uillinois.edu/illinois/page.php?id=127046" target="_blank" rel="noopener">Illinois</a>, <a class="src" href="https://canvashelp.stanford.edu/hc/en-us/articles/115001602467-Bulk-download-Canvas-files" target="_blank" rel="noopener">Stanford</a> and <a class="src" href="https://ecampushelpdesk.nctc.edu/hc/en-us/articles/205334770-Downloading-multiple-files-from-Canvas-to-your-PC" target="_blank" rel="noopener">NCTC</a> all describe the same select-all and zip.</p>

      <h3>Where it stops</h3>

      <ul>
        <li><strong>One course at a time.</strong> Six courses means repeating
        this six times, then organising six zips yourself.</li>
        <li><strong>The Files tab can be switched off entirely.</strong> This is
        the big one, and it is bigger than the one everybody warns about. A
        teacher can disable Files in course navigation, and plenty do. Then this
        method does not exist for that course at all.
        <a href="what-canvas-download-as-zip-misses.html">Measured across 33
        real courses</a>, that was the case in 3 of the 11 that held any
        material, and those three held 246 files between them.</li>
        <li><strong>Files uploaded straight into a Module or a Page may not be
        in the Files tab.</strong> A lecturer who attaches a slide deck directly
        to a module item has put a file in your course that the Files tab never
        lists, so the zip misses it. Real, and smaller than its reputation: in
        the same measurement it came to 3 files out of 358, in one course of
        eight.</li>
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
        <em>and</em> concluded courses, and it
        <a class="src" href="https://community.instructure.com/en/kb/articles/661234" target="_blank" rel="noopener">expires after 30 days</a>, so save it somewhere
        permanent the same day.</li>
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

      <p>It signs in with
      <a href="canvas-access-token-explained.html">an access token you create
      yourself</a> in Canvas, then uses the same official API the Canvas mobile
      apps use. Because it works at the account level rather than the page
      level, it can do the two things the other methods cannot:</p>

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
        Check before you install anything, and see
        <a href="canvas-access-token-explained.html">what a Canvas access token
        is and what it cannot do</a> if you are weighing up whether to make
        one.</p>
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
      Pages.</strong> A browser extension will be quicker than anything else, and
      <a href="canvas-download-tools-compared.html">the tool comparison</a> names
      the ones worth trying.</p>

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

      <p><strong>You want the grades and comments you were given.</strong> None
      of the five collects those, and Canvas's submissions export deliberately
      leaves them out. See
      <a href="save-canvas-assignment-feedback.html">how to save your Canvas
      assignment feedback</a>.</p>

      <p><strong>You want the Pages, quizzes, discussions and announcements.</strong>
      None of them is a file, so nothing on this page reaches them. There is one
      built-in route with a deadline on it -
      <a href="save-canvas-pages-quizzes-discussions.html">how to save Canvas
      quizzes, Pages and discussions</a>.</p>

      <p><strong>You want the lecture recordings.</strong> None of the five above
      touch them, because the video is never a Canvas file - it belongs to Studio,
      Panopto or Kaltura. Start with
      <a href="download-lecture-videos-from-canvas.html">how to download lecture
      videos from Canvas</a> to work out which you have, then
      <a href="download-panopto-lecture-recordings.html">how to download Panopto
      lecture recordings</a> if it is Panopto. Read the permission section
      first.</p>

      <div class="cta-box">
        <h3>Every course, in one run</h3>
        <p>Tick the courses you want and Canvas Downloader fetches all of them:
        the Files tab, the files hidden in modules and Pages that the zip misses,
        and the categories Canvas has no export for at all - assignments,
        announcements, discussions, quizzes, the syllabus, and the feedback on
        your own work. Run it again next month and it fetches only what
        changed.</p>
        <p>Free and open source, for Windows and macOS. Runs on your own
        computer: no account, no server, nothing uploaded.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
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
      minutes for a full degree, and it only works while you are still enrolled.
      There is a step-by-step version in
      <a href="back-up-canvas-course-before-losing-access.html">how to back up a
      Canvas course before you lose access</a>, including what to save
      first.</p>

      <h2 id="howlong">How long you actually keep access</h2>

      <p>There is no single answer, and the spread between institutions is much
      wider than most people expect. Four published policies, to show the range:
      <a class="src" href="https://canvashelp.stanford.edu/hc/en-us/articles/1500000114382-Student-access-to-course-content-after-the-quarter-ends" target="_blank" rel="noopener">Stanford</a> gives graduating students
      <strong>120 days</strong>; <a class="src" href="https://mycanvas.wustl.edu/faq-how-long-will-i-be-able-to-access-my-course-after-the-semester-ends-or-i-graduate-leave-washu/" target="_blank" rel="noopener">Washington University in St. Louis</a> keeps courses available for <strong>365 days</strong> after the semester
      ends; <a class="src" href="https://infocanvas.upenn.edu/students/canvas-after-graduation/" target="_blank" rel="noopener">Penn</a> retains course sites for
      <strong>five years</strong> from the term they ran in; and
      <a class="src" href="https://teamdynamix.umich.edu/TDClient/30/Portal/KB/Article/119/Student-Alumni-Access-to-Canvas-after-Graduation-or-the-End-of-Term" target="_blank" rel="noopener">Michigan</a> moves students to read-only access shortly
      after the term. So a number you read anywhere, including here, tells you
      about somebody else's university.</p>

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
        is the only category no one else can give you, and Canvas exports the
        submissions but not the feedback -
        <a href="save-canvas-assignment-feedback.html">how to save your Canvas
        assignment feedback</a> is the separate job.</li>
        <li><strong>Lecture recordings</strong>, if your course has them and your
        institution allows you to keep them.</li>
        <li><strong>Course files</strong> - slides, readings, worksheets.</li>
        <li><strong>Assignment briefs and rubrics.</strong></li>
        <li><strong>Announcements and discussions</strong>, which often carry
        corrections that never made it into the slides -
        <a href="save-canvas-pages-quizzes-discussions.html">none of which is a
        file</a>, so nothing file-based will collect them.</li>
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
      <a href="save-canvas-pages-quizzes-discussions.html">the only way to get
      the categories Canvas has no export for</a>.</p>

      <div class="cta-box">
        <h3>Save every course before access ends</h3>
        <p>Tick every course you are still enrolled in and Canvas Downloader
        saves them all in one run: every file, including the ones attached to
        modules that the built-in zip leaves behind, plus assignments,
        announcements, discussions, quizzes, the syllabus, and the grades and
        feedback you were given. Those last ones are exactly what you cannot get
        back once the enrolment ends.</p>
        <p>Free and open source, Windows and macOS. Runs on your own computer.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="how-to-download-all-canvas-files.html" class="btn-nav-ghost"><span>Compare all methods</span></a>
        </div>
      </div>

      <h2 id="recordings">Lecture recordings are the hard part</h2>

      <p>Recordings usually live outside Canvas - in Panopto, Canvas Studio or
      Kaltura - which means they are governed separately, they often expire on
      their own schedule, and no Canvas export has ever included them.
      <a href="download-lecture-videos-from-canvas.html">How to download lecture
      videos from Canvas</a> covers all five systems and how to tell them apart;
      <a href="download-panopto-lecture-recordings.html">how to download Panopto
      lecture recordings</a> goes deeper on the most common one.</p>

      <p>They are also the material universities are strictest about. Many
      institutions permit personal study copies and forbid sharing; some forbid
      downloading entirely. Check your own rules before you save anything, and
      treat a recording as the most restricted thing in your course rather than
      the least. Our <a href="disclaimer.html">acceptable use page</a> sets out
      the same expectation.</p>

      <p>If you are allowed to keep them, a transcript is worth as much as the
      video and takes a fraction of the space. It is also searchable, which the
      video is not - and it is usually the easiest thing in the course to get
      hold of, because
      <a href="panopto-lecture-transcript.html">Panopto has probably already made
      one</a>.</p>
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

      <p>If you are not certain your lectures are in Panopto at all, check first:
      Canvas embeds video from
      <a href="download-lecture-videos-from-canvas.html">five different systems</a>,
      Canvas Studio and Kaltura among them, and the rules on this page apply only
      to Panopto.</p>

      <h2 id="button">First, check whether the download button is there</h2>

      <p>Panopto's own guide to
      <a class="src" href="https://support.panopto.com/s/article/How-to-Download-a-Session-as-an-MP4" target="_blank" rel="noopener">downloading a session as an MP4</a> describes the
      same two-step reality: the option exists in the player, and it is only
      there when the folder or the recording has been set to allow it.</p>

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
        recording - <a class="src" href="https://support.panopto.com/s/article/Enable-Podcast-Downloads" target="_blank" rel="noopener">Panopto's own documentation</a> calls it enabling podcast downloads, and it is off until somebody does.
        If nobody has, you will see no button at all, and its absence is not a
        fault. Universities document it the same way on both sides of the
        Atlantic - <a class="src" href="https://canvashelp.stanford.edu/hc/en-us/articles/360047508074-Enable-download-of-Panopto-Course-Videos-recordings-for-students" target="_blank" rel="noopener">Stanford</a> and <a class="src" href="https://help.uis.cam.ac.uk/service/teaching-and-learning/lecture-capture/share-and-publish-recordings/enable-students-download" target="_blank" rel="noopener">Cambridge</a> both describe it as a setting a lecturer has to
        switch on deliberately.</p>
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

      <p>Timing matters more here than anywhere else in a course: recordings are
      often removed on their own schedule, ahead of the rest of the material. If
      you are near the end of a degree, read
      <a href="canvas-access-after-graduation.html">what happens to your Canvas
      access after graduation</a> before you plan around them.</p>

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

      <p>A transcript is also the form an AI study tool can actually read -
      see <a href="canvas-files-into-notebooklm.html">getting your Canvas files
      into NotebookLM</a>, where a local video file is the one thing it will not
      accept.</p>

      <p>Transcripts and subtitles are produced <strong>on your own
      computer</strong> by an offline speech-recognition model. The recording is
      never uploaded to be transcribed. The first run downloads the model, which
      takes a few minutes; after that it works with no network at all.</p>

      <p>The transcript is worth its own page, because it is the one part of a
      recording you can often keep when the video itself is restricted:
      <a href="panopto-lecture-transcript.html">how to get a transcript of a
      Panopto lecture</a> covers the one Panopto has probably already made, and
      how long transcribing a lecture yourself really takes.</p>

      <div class="cta-box">
        <h3>Keep your lectures in a form you can revise from</h3>
        <p>Canvas Downloader saves Panopto recordings alongside the rest of the
        course, in whichever form is useful to you: the video, an audio-only
        copy, or a searchable transcript and subtitle file. The transcription
        runs on your own computer, so nothing is uploaded to be transcribed.</p>
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
        <p><strong>The export <a class="src" href="https://community.instructure.com/en/kb/articles/661234" target="_blank" rel="noopener">expires after 30 days</a>.</strong> It is generated on request and then deleted, so this is not a
        link you can bookmark and come back to after graduation. Generate it and save the ZIP somewhere
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
      they are not part of your file. Canvas <a class="src" href="https://community.instructure.com/en/kb/articles/661231" target="_blank" rel="noopener">renders them in a viewer on top of it</a>, so downloading the file from your own submission gives you a clean copy
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
        compatible, and <a class="src" href="https://community.instructure.com/en/kb/articles/661230" target="_blank" rel="noopener">a file DocViewer cannot open</a> is a file nobody annotated.
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
        files from Canvas</a>, and
        <a href="save-canvas-pages-quizzes-discussions.html">how to save the
        quizzes, Pages and discussions</a>, which are not files and need their
        own answer.</li>
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
        <p>Canvas Downloader saves your feedback as it downloads a course: the
        grade and score, the rubric with its per-criterion comments, the full
        comment thread, and any file a teacher attached to a comment - one
        readable page per assignment, sitting next to the material it belongs to.
        Inline DocViewer annotations are the one exception, for the reason
        above, so keep using the per-assignment Download button for those.</p>
        <p>Do it for every course you are still enrolled in, in one run. Free and
        open source, Windows and macOS.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
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

# ---------------------------------------------------------------------------
# WRITING A cta-box: the rules, and why. Set 2026-08-26 by the product owner
# after reading these five. Full reasoning in marketing/BLOG_PLAN.md Phase 0b.
#
#   1. The box is the CONVERSION element. Limits belong in the body, where the
#      claim is made. Page 5 used to END its box with: "You do not need it. If
#      your course keeps everything in the Files tab, Canvas will zip it and
#      that is genuinely simpler." True, already stated under #getting above,
#      and the last thing a reader saw before the Download button.
#   2. Say the biggest true thing. "A whole course in one run" understates
#      "every course you tick", which is the product.
#   3. Use the reader's noun: Panopto lecture recordings, not lecture
#      recordings; PowerPoints and Word documents, not Office files. Drop
#      conversion mechanics nobody asked for ("Canvas Pages to Markdown").
#   4. Answer THIS article's problem, not the product in general. P1's box
#      used to carry only the trust blurb and no capability at all.
#   5. The ghost button's destination must match its label AND be built for an
#      arrival. "See it in action" -> index.html#features (the demo clips),
#      never guide.html, which is reference documentation for people who
#      already run the app.
#   6. Before writing one, read core/preset_manager.py. This page shipped an
#      article about NotebookLM without mentioning that the app has a built-in
#      preset called "100% AI & NotebookLM Ready" that does exactly what the
#      article spends 1,700 words describing by hand.
# ---------------------------------------------------------------------------
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

      <div class="note">
        <p><strong>NotebookLM is now called Gemini Notebook.</strong> Google
        <a class="src" href="https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/" target="_blank" rel="noopener">renamed it on 16 July 2026</a> and describes it
        as a rename rather than a replacement: same product, same notebooks,
        new name and logo rolling out over several weeks. Everything on this
        page applies to both names, and this page says "NotebookLM" throughout
        because that is still what most people call it.</p>
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
      were both <a class="src" href="https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-deep-research-file-types/" target="_blank" rel="noopener">added during 2025</a>, which removed the
      conversion step that used to make this awkward. As things stand it
      takes:</p>

      <ul>
        <li><strong>Documents</strong> - PDF, <code>.docx</code>,
        <code>.pptx</code>, <code>.txt</code>, <code>.md</code>, CSV.</li>
        <li><strong>Google files</strong> - Docs, Slides and Sheets, plus Drive
        links.</li>
        <li><strong>Audio</strong> - MP3, M4A and WAV, transcribed on upload.</li>
        <li><strong>Images</strong>, pasted text, web page URLs, and public
        YouTube links.</li>
      </ul>

      <p>Per source you get up to <strong>500,000 words or 200 MB</strong>,
      whichever you hit first, which no normal lecture deck or reading comes
      close to. The accepted types and the limits are listed in
      <a class="src" href="https://support.google.com/notebooklm/answer/16215270" target="_blank" rel="noopener">Google's own source documentation</a>, and they do
      move, so check it rather than trusting this paragraph in a year.</p>

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
        internally anyway. See
        <a href="panopto-lecture-transcript.html">how to get a transcript of a
        Panopto lecture</a> - there is often one waiting that you do not have to
        make.</li>
      </ul>

      <p>Getting the recording in the first place is its own problem, because
      Canvas embeds video from
      <a href="download-lecture-videos-from-canvas.html">five different systems</a>
      and each has different rules. Useful detail for this page: in both Canvas
      Studio and Panopto the <strong>transcript is a separate permission from the
      video</strong>, and it is often left open when the video is not - which
      hands you the better source anyway.</p>

      <p>Either way, remember that lecture recordings are the material
      universities restrict most often, and the permission question is a real one
      rather than a formality. See
      <a href="download-panopto-lecture-recordings.html">how to download Panopto
      lecture recordings</a>, which leads with exactly that.</p>

      <h2 id="recipe">A recipe for one course</h2>

      <ol class="steps">
        <li>Download the course to a folder on your computer. If the Files tab
        holds everything, Canvas's own zip is the quickest route; if it does not,
        or if you are doing this for several courses, the
        <strong>100% AI &amp; NotebookLM Ready</strong> preset below does steps
        1 to 3 in a single run.</li>
        <li>Delete the administrative noise - announcements about room changes,
        duplicated reading lists, the assignment briefs you have already
        submitted against.</li>
        <li>Turn any lecture recordings into transcripts or MP3s. This is the
        step with no manual equivalent - NotebookLM will not take the video, so
        something has to convert it before you upload.</li>
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
        that is actually yours, and it will still open in ten years - which
        matters most if you are close to
        <a href="canvas-access-after-graduation.html">losing Canvas access
        altogether</a>.</p>
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
        <h3>A course folder NotebookLM already accepts</h3>
        <p>Canvas Downloader ships a preset called <strong>100% AI &amp;
        NotebookLM Ready</strong>, built for exactly this. Tick as many courses
        as you like and each course arrives as one flat folder, drag-and-drop
        ready: PowerPoints, Word documents and spreadsheets converted to PDF,
        Canvas Pages and link lists as text, and the Panopto lecture recordings
        saved separately as audio, or as a searchable transcript - which is the
        one source on this page NotebookLM will not take as video.</p>
        <p>Free and open source, Windows and macOS. Runs on your own computer,
        and the transcription does too.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
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

# ============================================================ PAGE 6 =========
# Grounded 2026-08-27. Cluster A of marketing/BLOG_PLAN.md - the biggest
# measured demand and the least institutional SERP of any cluster in the map.
#
# The premise of the page is that the query has no direct answer: there is no
# such thing as "a Canvas lecture video". Canvas is a shell around one of five
# different systems, and which one you are looking at decides everything. Every
# competing page on this query answers for ONE of the five and never says so.
#
# Primary sources, all fetched 200 on 2026-08-27:
#  * Instructure KB 664517 (embedding Studio media, RCE Studio Embed
#    Improvements): "When embedding media in Canvas, the download option is
#    turned off by default for media you own, but you can enable the download
#    option." The viewer restrictions are separate toggles - "Allow media
#    download (except YouTube or Vimeo videos)" and "Allow transcript download".
#    This is the single most useful fact on the page and no content farm has it.
#  * Instructure KB 660507 (downloading media or transcript files in Studio):
#    "This feature is a legacy add-on that is now available with Canvas Plus and
#    Canvas Next." Plus "Note: You can not download media files from YouTube or
#    Vimeo." So the Studio-side download is a LICENCE question, not only a
#    permission one.
#  * Instructure Community 618390, accepted answer: "Studio videos are
#    downloaded easily from your Studio account. But this is one at a time. And
#    for media uploaded to the rich content editor, please go to your account
#    Files > My Files > Uploaded Media."
#  * Panopto support, Enable Podcast Downloads - off until somebody enables it.
#  * University of Michigan MiVideo KB 10274 (Kaltura): "The default Media
#    Gallery player does not have the download button enabled", and the fix is
#    selecting the "Enable Primary Video Download Button" player. So on Kaltura
#    the download button is a property of the PLAYER, not of the video.
#
# HONESTY: this app downloads Panopto and does NOT download Canvas Studio or
# Kaltura - shared/helpers.LTI_STREAM_EXTENSIONS is what makes a URL-less Canvas
# video report as a stream rather than a failure. That is stated plainly in the
# body (section "What this app covers"), NOT inside the CTA box, per the Phase 0b
# rule: limits belong in the body, where the claim is made. The box names Panopto
# explicitly, so the scope is disclosed by the box's own strongest noun.

P6_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#where">First work out where the video actually lives</a></li>
          <li><a href="#tell">How to tell which one you are looking at</a></li>
          <li><a href="#studio">Canvas Studio</a></li>
          <li><a href="#panopto">Panopto</a></li>
          <li><a href="#kaltura">Kaltura, My Media and the branded ones</a></li>
          <li><a href="#files">A plain video file, and the one people miss</a></li>
          <li><a href="#transcript">When the video is off, the transcript often is not</a></li>
          <li><a href="#allowed">What you are actually allowed to do</a></li>
          <li><a href="#app">What this app covers</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">There is no such thing as a Canvas lecture video. Canvas
      almost never stores the recording; it embeds a player belonging to one of
      five other systems. Which system decides everything about what you can do
      next: one click, one email to your lecturer, or nothing at all.</p>

      <p>That is why the answers you find contradict each other. They are all
      correct, each for a different one of the five, and none of them says which.
      Work out which one you have first and the rest of this page is short.</p>

      <h2 id="where">First work out where the video actually lives</h2>

      <p>Five systems put a video in front of a Canvas student. They behave
      nothing alike:</p>

      <ul>
        <li><strong>Canvas Studio</strong> - Instructure's own video tool, built
        into Canvas. Downloading is off by default and your lecturer switches it
        on per embed.</li>
        <li><strong>Panopto</strong> - a separate lecture-capture system Canvas
        links out to. Also off by default, enabled per folder or per
        recording.</li>
        <li><strong>Kaltura</strong>, often rebranded as <em>My Media</em>,
        <em>Media Gallery</em> or a local name like MiVideo. Whether there is a
        download button depends on which player the channel uses.</li>
        <li><strong>A plain video file</strong> that somebody uploaded to the
        Files tab. This is an ordinary file and downloads like any other.</li>
        <li><strong>An external link</strong> - YouTube, Vimeo, a Zoom cloud
        recording, or a link to a departmental server. Governed by that service,
        not by Canvas.</li>
      </ul>

      <p>Only two of those five are ever affected by anything you do inside
      Canvas, which is the part that surprises people. Deleting your Canvas
      account does not delete a Panopto recording, and exporting your Canvas
      course does not export one either.</p>

      <h2 id="tell">How to tell which one you are looking at</h2>

      <p>You do not need to ask anybody. Thirty seconds of looking will tell
      you:</p>

      <ol class="steps">
        <li><strong>Right-click the video and look for the player's name.</strong>
        Panopto and Kaltura both put their branding in the context menu or in a
        corner of the player. Studio does not brand itself at all, because inside
        Canvas it is not meant to look like a separate product.</li>
        <li><strong>Look at the module item.</strong> If clicking it opens a new
        tab, or a full-width page with its own toolbar, you have launched into an
        external system - almost always Panopto or Kaltura. If the video is sitting
        inline in a Canvas page among ordinary text, it is Studio or a file.</li>
        <li><strong>Check the course navigation menu on the left.</strong> A
        <em>My Media</em> or <em>Media Gallery</em> entry means Kaltura. A
        <em>Panopto</em> entry means Panopto. A <em>Studio</em> entry means
        Studio.</li>
        <li><strong>Open the Files tab and search for the name.</strong> If the
        recording appears there as an <code>.mp4</code>, it is a plain file and
        you are done - skip to the last section.</li>
      </ol>

      <h2 id="studio">Canvas Studio</h2>

      <p>Studio is the one most people are actually asking about, because it is
      Instructure's own and it comes with Canvas. It is also the one with the
      most misinformation around it, because there are two separate downloads and
      they are controlled by two different people.</p>

      <p><strong>The download inside the embedded player.</strong> When a
      lecturer drops a Studio video into a page, Instructure's own documentation
      is explicit that
      <a class="src" href="https://community.instructure.com/en/kb/articles/664517-how-do-i-embed-canvas-studio-media-in-a-canvas-course-using-rce-studio-embed-improvements" target="_blank" rel="noopener">the download option is turned off by default</a>
      and has to be enabled deliberately. It is a per-embed setting, so the same
      recording can be downloadable on one page and not on the next, and there
      are <strong>two separate toggles</strong>: one allowing the media download
      and one allowing the transcript download. That second one matters more
      than it sounds, and it gets its own section below.</p>

      <p><strong>The download inside Studio itself.</strong> If your course
      navigation has a <em>Studio</em> entry, you can open the media there and
      download it from your own library. Two catches. Instructure describes this
      as
      <a class="src" href="https://community.instructure.com/en/kb/articles/660507-how-do-i-download-media-files-or-media-transcript-files-in-canvas-studio" target="_blank" rel="noopener">"a legacy add-on that is now available with Canvas Plus and Canvas Next"</a>,
      so whether you have it at all depends on which Canvas package your
      institution bought. Not on you, and not on your lecturer. It is also
      strictly one file at a time. The accepted answer in Instructure's own
      community thread on this exact question says
      <a class="src" href="https://community.instructure.com/en/discussion/618390/how-to-download-all-course-files-and-media-on-canvas" target="_blank" rel="noopener">"Studio videos are downloaded easily from your Studio account. But this is one at a time."</a></p>

      <div class="note warn">
        <p><strong>A Studio video that came from YouTube or Vimeo can never be
        downloaded.</strong> Instructure states it flatly: "You can not download
        media files from YouTube or Vimeo." Studio is embedding somebody else's
        player, so there is no file for it to hand you. The <em>Allow media
        download</em> toggle does not even appear for those.</p>
      </div>

      <h2 id="panopto">Panopto</h2>

      <p>Panopto is the same story with different buttons. Downloads are off
      until somebody turns them on -
      <a class="src" href="https://support.panopto.com/s/article/Enable-Podcast-Downloads" target="_blank" rel="noopener">Panopto calls it enabling podcast downloads</a>
      - and it can be switched on for a whole folder, one subfolder, or a single
      recording. If your player's menu has no download entry, nobody has enabled
      it, and its absence is not a fault or a bug.</p>

      <p>Because Panopto lives outside Canvas entirely, it also expires on its
      own schedule, which frequently runs ahead of your Canvas access.
      <a href="download-panopto-lecture-recordings.html">How to download Panopto
      lecture recordings</a> covers the whole of it, including what to ask for and
      how to ask.</p>

      <h2 id="kaltura">Kaltura, My Media and the branded ones</h2>

      <p>Kaltura is the one that confuses people most, because the download
      button is a property of the <strong>player</strong> rather than of the
      video. The University of Michigan's guide to its own Kaltura deployment
      puts it plainly:
      <a class="src" href="https://teamdynamix.umich.edu/TDClient/30/Portal/KB/PrintArticle?ID=10274" target="_blank" rel="noopener">"The default Media Gallery player does not have the download button enabled"</a>,
      Turning it on means an instructor picking a different player, one
      literally named <em>Enable Primary Video Download Button</em>, either for
      the whole Media Gallery or for a single embedded item.</p>

      <p>So on Kaltura, "there is no download button" almost never means the
      video is protected. It usually means nobody changed a default that most
      lecturers do not know exists. That is worth knowing before you write the
      email, because it makes the request a small one.</p>

      <p>A number of institutions replaced Kaltura with Canvas Studio through
      2024 and 2025. If yours did, old links may have been relinked to Studio
      automatically, so read the Studio section rather than this one.</p>

      <h2 id="files">A plain video file, and the one people miss</h2>

      <p>If the recording is an ordinary <code>.mp4</code> in the course Files
      tab, none of the above applies. Select it and download it, or select
      everything and take the lot.
      <a href="how-to-download-all-canvas-files.html">The five ways to download
      your Canvas files</a> covers that, and Download as Zip handles it with no
      software at all.</p>

      <p>One almost nobody knows about. <strong>Media you recorded
      yourself</strong> through Canvas's own record button, such as a video
      discussion reply or a recorded submission, is filed separately from
      everything else. Instructure's community thread gives the path:
      <em>Account, then Files, then My Files, then Uploaded Media</em>. If you have spent an hour hunting for a video
      submission you made two semesters ago, that is where it went.</p>

      <h2 id="transcript">When the video is off, the transcript often is not</h2>

      <p>This is the most useful thing on this page and it is almost never
      mentioned. In both Studio and Panopto, <strong>the transcript is a separate
      permission from the video</strong>. Studio's embed settings list <em>Allow
      media download</em> and <em>Allow transcript download</em> as two different
      toggles, and lecturers who deliberately restrict the video routinely leave
      the transcript open, because captions exist for accessibility and turning
      them off is a decision nobody wants to defend.</p>

      <p>So before concluding that a lecture is locked, open the player's options
      menu and look for a transcript or captions download. For revision that is
      frequently the better artefact anyway:</p>

      <ul>
        <li>It is <strong>searchable</strong>. A ninety-minute recording is not.</li>
        <li>It is a few hundred kilobytes against a few hundred megabytes.</li>
        <li>It is the format an AI study tool can actually read - see
        <a href="canvas-files-into-notebooklm.html">getting your Canvas files into
        NotebookLM</a>, where a local video file is the one thing it will not
        accept.</li>
        <li>It still opens in ten years, on any machine, with no player and no
        login.</li>
      </ul>

      <p>If there is no transcript at all, ask for one separately. Asking for
      captions lands very differently from asking for a download, and failing
      that you can always make your own from the audio.
      <a href="panopto-lecture-transcript.html">How to get a transcript of a
      Panopto lecture</a> covers both routes, with measured timings for the
      second.</p>

      <h2 id="allowed">What you are actually allowed to do</h2>

      <p>Every route above is a supported feature that somebody chose to switch
      on or off. None of them is a way around anything, and that is deliberate.
      Lecture recordings are the most restricted material in a typical course,
      and for reasons that hold up. They contain other students' voices and
      questions. They are the lecturer's own performance. Any third-party clip
      inside one is usually licensed for the cohort and nobody else.</p>

      <p>Which is why the honest first step is nearly always the email. "Could
      you enable downloads for this folder, or share the transcript?" is a small,
      specific request that costs your lecturer about a minute, and in the
      Kaltura case it is a request to change a default rather than to make an
      exception. Screen recorders and browser plugins that pull the stream
      regardless are a different thing entirely, and your institution's academic
      regulations will treat them that way.</p>

      <div class="note">
        <p><strong>Timing beats technique.</strong> Recordings are usually the
        first thing removed and often go before the rest of the course. Near the
        end of a term, ask now rather than in exam week. See
        <a href="canvas-access-after-graduation.html">what happens to your Canvas
        access after graduation</a> for how little warning you tend to get.</p>
      </div>

      <h2 id="app">What this app covers</h2>

      <p>Being specific about scope, because half of this page is about systems
      Canvas does not own. Canvas Downloader handles <strong>Panopto</strong>: it
      discovers the recordings a course links to and saves them as video, audio,
      a searchable transcript, or a shortcut back to the original, and it fetches
      them for every course you select in one run.</p>

      <p>It does <strong>not</strong> download Canvas Studio or Kaltura. Canvas
      hands out no file for either. The app sees a video with no download
      address and reports it as a stream rather than pretending it failed. So
      for those two the routes above are the routes, and what the app does
      instead is everything around the recording: the slides, the readings, the
      assignment briefs and the discussions.</p>

      <div class="cta-box">
        <h3>Every Panopto recording, and the whole course around it</h3>
        <p>Tick as many courses as you like. Canvas Downloader saves each
        <strong>Panopto lecture recording</strong> as video, as audio, or as a
        searchable transcript produced <strong>on your own computer</strong>, and
        pulls down the slides, readings, assignment briefs, announcements and
        feedback from the same courses in the same run.</p>
        <p>Free and open source, Windows and macOS. Nothing is uploaded anywhere,
        including the transcription.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P6_FAQ = [
    ("Why is there no download button on my lecture video?",
     'Because downloading is off by default in both of the systems Canvas '
     'usually embeds. Instructure states that a Studio embed has the download '
     'option turned off unless the lecturer enables it, and Panopto downloads '
     'are disabled until somebody switches them on. A missing button almost '
     'always means a default nobody changed, not a deliberate lock.'),
    ("How do I know whether my video is Canvas Studio, Panopto or Kaltura?",
     'Look at the left-hand course navigation for a Studio, Panopto or My Media '
     'entry, and right-click the player to see whose branding appears. A video '
     'that opens in a new tab or on its own full-width page is almost always an '
     'external system; one sitting inline among ordinary Canvas text is Studio '
     'or a plain file.'),
    ("Can I download a Canvas Studio video?",
     'Only if it has been allowed, and there are two separate routes. One is '
     'the download option on the embed, which a lecturer turns on per embed. '
     'The other is downloading from your own Studio library, which Instructure '
     'calls a legacy add-on available with Canvas Plus and Canvas Next, so that '
     'one depends on which Canvas package your institution bought. Studio media '
     'that came from YouTube or Vimeo can never be downloaded at all.'),
    ("Does Canvas export or Download as Zip include lecture recordings?",
     'No. Download as Zip takes the Files tab, so it takes a video only if the '
     'video is an ordinary file sitting in that tab. Anything played through '
     'Studio, Panopto or Kaltura is not a Canvas file at all, so no Canvas '
     'export has ever contained it.'),
    ("Can I download the transcript if the video is blocked?",
     'Often, yes, and it is worth checking. The transcript is a separate '
     'permission from the video in both Studio and Panopto, and lecturers who '
     'restrict the recording frequently leave captions open because they exist '
     'for accessibility. Open the player\'s options menu and look for a '
     'transcript or captions download.'),
    ("Where did my own recorded video submission go?",
     'Media you recorded through Canvas\'s own record button is filed under '
     'Account, then Files, then My Files, then Uploaded Media - separately from '
     'both your course files and your submissions. Instructure\'s community '
     'thread on downloading course media gives that path.'),
    ("Is it against the rules to record the lecture player with a screen recorder?",
     'Usually, and it is the one route on this page that is not a supported '
     'feature. Recordings contain other students, the lecturer\'s own delivery, '
     'and often third-party material licensed only for the cohort, so most '
     'institutions treat capturing them outside the provided tools as a '
     'disciplinary matter. Ask for the download or the transcript instead.'),
    ("Can Canvas Downloader get my lecture videos?",
     'It downloads Panopto recordings, as video, audio or a searchable '
     'transcript, for every course you select. It does not download Canvas '
     'Studio or Kaltura, because Canvas provides no file for either - for those '
     'the routes on this page are the routes.'),
]

# ============================================================ PAGE 7 =========
# Grounded 2026-08-27. Cluster B of marketing/BLOG_PLAN.md, and the split the
# per-article dispositions called for: PAGE 3 keeps the permission-and-download
# story, this page takes the transcript half, which is uncontested and is the
# one job on the whole demand map that only this app does.
#
# The page leads with PANOPTO'S OWN transcript rather than with ours, and that
# ordering is deliberate. It is free, it is already there for most people, and
# it needs no software - saying so first is the same rule the flagship follows
# ("describe the competing approaches fairly, including where they beat this
# app"), and it is also simply the correct advice for the majority of readers.
#
# Primary sources, all fetched 200 on 2026-08-27:
#  * Panopto's own captioning FAQ: "ASR captions are typically 90-95% accurate
#    depending on the audio quality in the recording", and captions "can be
#    created in about one-quarter of the total video length".
#  * Brown University IT KB, Managing Automatic Captions in Panopto - the dated
#    default change: "On or before May 11, 2026 automatic captions will be
#    turned on for all new content uploaded to Panopto", for HHS Section 504 and
#    WCAG 2.1 Level AA; and "Automatic machine captions are generated using an
#    ASR engine and may contain errors."
#    ATTRIBUTED TO BROWN, not stated as a universal Panopto fact - it is one
#    institution's documentation of a rollout, and a second institution (Boston
#    College) documents the behaviour without the date. Timing genuinely varies
#    per tenant, so the page says so.
#  * Panopto support, How to Download Captions from the Viewer.
#  * openai/whisper-large-v3 model card: trained on "1 million hours of weakly
#    labeled audio and 4 million hours of pseudo-labeled audio", and "10% to 20%
#    reduction of errors compared to Whisper large-v2".
#
# FIRST-HAND MEASURED DATA, from panopto/models.py, and it is the most valuable
# thing on this page because nobody else has it. Apple M4, 10 cores, int8,
# beam_size=5, vad_filter=True, 180 s of real Danish lecture audio, as multiples
# of realtime: tiny 25.5x | base 17.5x | small 6.2x | turbo 3.3x | medium 2.5x.
# Plus the finding that corrects a widely-repeated claim: Turbo's speed comes
# from its 4-layer DECODER against large-v3's 32, while its ENCODER is large-v3's
# unchanged - and on CPU the encoder dominates, so "Turbo is fast" is a GPU fact
# that does not transfer to a laptop.
# THE SAMPLE IS ONE MACHINE AND ONE CLIP AND THE PAGE SAYS SO. A number
# presented as a benchmark it is not would not survive this project's own rules.

P7_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#free">Panopto has probably already made one</a></li>
          <li><a href="#get">Getting it out of the player</a></li>
          <li><a href="#gaps">When Panopto's transcript is not there, or not enough</a></li>
          <li><a href="#own">Making your own, on your own computer</a></li>
          <li><a href="#speed">How long it actually takes, measured</a></li>
          <li><a href="#model">Which model, and the advice that is wrong on a laptop</a></li>
          <li><a href="#accurate">How accurate any of this is</a></li>
          <li><a href="#use">What a transcript is actually good for</a></li>
          <li><a href="#allowed">The permission question</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">A transcript is the most useful form of a lecture and the
      least demanded. It is searchable, it is a few hundred kilobytes against a
      few hundred megabytes, it opens on anything, and it is the only form an AI
      study tool will read. It is also, right now, easier to get than it has ever
      been - and for most people it already exists.</p>

      <p>So this page starts with the free one that needs no software, and only
      then covers making your own.</p>

      <h2 id="free">Panopto has probably already made one</h2>

      <p>Panopto machine-transcribes recordings to produce closed captions, and
      captions are a transcript with timestamps on. What changed recently is that
      it is no longer something a lecturer has to remember to switch on.</p>

      <p>Brown University's IT knowledge base records the rollout and the reason:
      <a class="src" href="https://ithelp.brown.edu/kb/articles/managing-automatic-captions-in-panopto" target="_blank" rel="noopener">"On or before May 11, 2026 automatic captions will be turned on for all new content uploaded to Panopto"</a>,
      to meet the US Section 504 ruling and WCAG 2.1 Level AA. That is one
      institution documenting one rollout, and tenants are configured
      independently, so read it as "check yours" rather than as a guarantee. The
      direction only goes one way, though, and it is driven by accessibility law
      rather than by anybody's product roadmap. <strong>Captions are far more likely to
      be present on a 2026 recording than on a 2023 one.</strong></p>

      <p>Two consequences worth having:</p>

      <ul>
        <li><strong>Captions are usually not the same permission as the video.</strong>
        A lecturer who has switched downloading off has very often left captions
        alone, because turning accessibility features off is a decision nobody
        wants to defend. Check the transcript before concluding a lecture is
        locked.</li>
        <li><strong>They arrive on a delay.</strong> Panopto's own FAQ says
        captions <a class="src" href="https://www.panopto.com/blog/frequently-asked-questions-faqs-about-video-captioning-answered/" target="_blank" rel="noopener">"can be created in about one-quarter of the total video length"</a>,
        so a two-hour lecture is roughly half an hour behind the recording. If a
        lecture went up an hour ago and has no captions, wait rather than
        conclude.</li>
      </ul>

      <h2 id="get">Getting it out of the player</h2>

      <p>Inside the Panopto viewer the transcript is a panel beside the video,
      and it is worth opening even if you never download it: clicking a line
      jumps the recording to that moment, which is the fastest way to find the
      four minutes of a lecture you actually needed.</p>

      <ol class="steps">
        <li>Open the recording in the Panopto player, inside Canvas or on your
        institution's Panopto site.</li>
        <li>Open the <strong>Captions</strong> or <strong>Transcript</strong>
        panel. If there is no such panel, the recording has no captions yet -
        see the next section.</li>
        <li>Look for a download option on that panel or in the player's menu.
        Panopto documents this as
        <a class="src" href="https://support.panopto.com/s/article/How-to-Download-Captions-from-the-Viewer" target="_blank" rel="noopener">downloading captions from the viewer</a>,
        and what you get is a subtitle file.</li>
        <li>If you only want the words, open the file in any text editor and
        delete the numbers. A subtitle file is plain text with timestamps; there
        is nothing proprietary in it.</li>
      </ol>

      <div class="note">
        <p><strong>A subtitle file is more useful than a plain one, so keep it.</strong>
        <code>.srt</code> and <code>.vtt</code> carry a timestamp per line, which
        means the text stays anchored to the recording. Search the transcript,
        find the timestamp, jump to that minute. A plain transcript loses that
        for the sake of tidiness you will not care about in April.</p>
      </div>

      <h2 id="gaps">When Panopto's transcript is not there, or not enough</h2>

      <p>Four situations where the free route runs out, all ordinary:</p>

      <ul>
        <li><strong>Older recordings.</strong> The default change applies to new
        content. A 2024 course may have nothing, and nothing will appear on its
        own.</li>
        <li><strong>Caption downloads switched off</strong> while viewing is
        allowed. You can read it and not keep it.</li>
        <li><strong>The wrong language, or a mixed one.</strong> ASR picks a
        language and commits. A lecture delivered in Danish with English slides
        and English technical vocabulary is exactly the case machine captioning
        handles worst, and it is completely normal in Europe.</li>
        <li><strong>You are about to lose access.</strong> A transcript you can
        only read inside Panopto disappears with your account, which is precisely
        when you want it - see
        <a href="canvas-access-after-graduation.html">what happens to your Canvas
        access after graduation</a>.</li>
      </ul>

      <h2 id="own">Making your own, on your own computer</h2>

      <p>The alternative is to transcribe the audio yourself. This used to mean
      an upload to a paid service; it does not any more. Open speech-recognition
      models run on an ordinary laptop, and the whole job is local: the audio
      never leaves your machine, there is no account, no quota and no per-minute
      charge.</p>

      <p>The shape of it is always the same, whatever tool you use:</p>

      <ol class="steps">
        <li>Get the audio. You do not need the video - a lecture's audio track is
        a fraction of the size and carries everything a transcript can use.</li>
        <li>Download a speech-recognition model once. They run from about
        <strong>75 MB</strong> to <strong>3 GB</strong> depending on how accurate
        you want to be.</li>
        <li>Run it. After the first download, nothing needs a network
        connection.</li>
        <li>Keep both outputs if the tool offers them: a plain
        <code>.txt</code> to read and search, and a timestamped
        <code>.srt</code> to navigate with.</li>
      </ol>

      <p>The catch is not accuracy. It is time, and almost nothing published
      about this is specific about how much.</p>

      <h2 id="speed">How long it actually takes, measured</h2>

      <p>Here is a real measurement rather than an estimate. Six models on the
      same clip, on one machine, timed as <strong>multiples of realtime</strong> -
      so 6x means an hour of lecture takes ten minutes.</p>

      <div class="tbl-wrap" tabindex="0" role="region"
        aria-label="Transcription speed by model on a 10-core CPU">
        <table class="cmp">
          <thead>
            <tr>
              <th>Model</th>
              <th>Download size</th>
              <th>Speed on this CPU</th>
              <th>One hour of lecture takes</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Tiny</td><td>75 MB</td><td>25.5x realtime</td><td>about 2 minutes</td></tr>
            <tr><td>Base</td><td>145 MB</td><td>17.5x realtime</td><td>about 3 minutes</td></tr>
            <tr><td>Small</td><td>484 MB</td><td>6.2x realtime</td><td>about 10 minutes</td></tr>
            <tr><td>Large v3 Turbo</td><td>1.6 GB</td><td>3.3x realtime</td><td>about 18 minutes</td></tr>
            <tr><td>Medium</td><td>1.5 GB</td><td>2.5x realtime</td><td>about 24 minutes</td></tr>
            <tr><td>Large v3</td><td>3.1 GB</td><td>not timed - wants a GPU</td><td>-</td></tr>
          </tbody>
        </table>
      </div>

      <div class="note">
        <p><strong>The method, and how small the sample is.</strong> One machine -
        an Apple M4 with 10 CPU cores, running on the CPU - over 180 seconds of
        real Danish lecture audio, at int8 quantisation, beam size 5, with
        voice-activity filtering on. That is a single clip on a single laptop, not a benchmark suite. It
        is published because the relative ordering is stable and useful and
        nobody else states it at all, not because four significant figures would
        mean anything. Your machine will differ; the <em>shape</em> of the table
        will not.</p>
      </div>

      <p>Two things fall out of it that matter more than the exact numbers.
      First, on a CPU the range across models is <strong>ten-fold</strong>, so
      the choice is not a detail. Second, a semester is not one lecture: at
      2.5x realtime, thirty two-hour lectures is about a full day of your laptop
      running flat out, and at 25x it is under three hours.</p>

      <h2 id="model">Which model, and the advice that is wrong on a laptop</h2>

      <p>The standard advice is to use Large v3 Turbo, because it is nearly as
      accurate as Large v3 and several times faster. On a GPU that is correct.
      <strong>On a CPU it is wrong, and the reason is structural rather than a
      matter of degree.</strong></p>

      <p>Turbo's speed comes from its <strong>decoder</strong>, which has four
      layers where Large v3 has thirty-two. Its <strong>encoder</strong> is Large
      v3's, unchanged. On a GPU the decoder dominates the time, so cutting it to
      an eighth is transformative. On a CPU the encoder dominates - and the
      encoder did not change, so almost none of that speed-up arrives. In the
      table above Turbo lands between Small and Medium, in the group that is too
      slow to be practical.</p>

      <p>What that costs in real terms, from a real course: <strong>36
      recordings that take 40 to 60 minutes on Tiny would have taken about six
      and a half hours</strong> on the model a naive "pick the best one" rule
      selects.</p>

      <p>So the honest rule is short:</p>

      <ul>
        <li><strong>No GPU?</strong> Nothing above Small. Small is the floor
        rather than Tiny because the tier below it loses real accuracy on
        non-English lecture audio, which is what most of these recordings
        are.</li>
        <li><strong>A GPU with 4 GB or more free?</strong> Turbo, and this is
        where its reputation comes from.</li>
        <li><strong>A GPU with 6 GB or more?</strong> Large v3, if you want the
        last sliver of accuracy on a hard language.</li>
      </ul>

      <h2 id="accurate">How accurate any of this is</h2>

      <p>Both routes are machine transcription and both are wrong sometimes, so
      it is worth knowing where.</p>

      <p>Panopto states that
      <a class="src" href="https://www.panopto.com/blog/frequently-asked-questions-faqs-about-video-captioning-answered/" target="_blank" rel="noopener">"ASR captions are typically 90-95% accurate depending on the audio quality in the recording"</a>,
      and institutions restate that with a warning attached: Brown's guidance
      says machine captions
      <a class="src" href="https://ithelp.brown.edu/kb/articles/managing-automatic-captions-in-panopto" target="_blank" rel="noopener">"may contain errors"</a>
      and that creators are expected to review and edit them. Which is worth
      reading twice: <strong>90 to 95% correct means roughly one word in fifteen
      is wrong</strong>, and they are not distributed evenly.</p>

      <p>The open models sit in a similar band. They were trained at a scale
      that makes them fairly tolerant of accents and background noise: the
      current large model was built on
      <a class="src" href="https://huggingface.co/openai/whisper-large-v3" target="_blank" rel="noopener">1 million hours of weakly labelled audio and 4 million hours of pseudo-labelled audio</a>,
      Its own model card claims a "10% to 20% reduction of errors" over the
      version before it, across a wide range of languages.</p>

      <p>Where both fail is the same place, and it is the worst possible place
      for a student: <strong>proper nouns and technical vocabulary</strong>. A
      lecturer's name, a theory named after somebody, a chemical, a case
      citation, a Danish word inside an English sentence. The general words come
      out fine and the exact term you were going to search for does not.</p>

      <p>The practical answer is not a better model. Treat the transcript as a
      <strong>searchable index into the recording</strong> rather than as a
      document of record. That is what the timestamps are for, and it is why
      keeping the recording, or at least a shortcut to it, beside the transcript
      is worth the disk.</p>

      <h2 id="use">What a transcript is actually good for</h2>

      <ul>
        <li><strong>Finding the four minutes that mattered.</strong> Search the
        text, read the timestamp, jump there. This alone is worth the exercise
        and it is not possible with video.</li>
        <li><strong>Revision that is not rewatching.</strong> Reading a
        ninety-minute lecture takes about fifteen minutes.</li>
        <li><strong>AI study tools.</strong> A local video file is the one thing
        they will not take - see
        <a href="canvas-files-into-notebooklm.html">getting your Canvas files
        into NotebookLM</a>, where the transcript is the whole point of this
        exercise.</li>
        <li><strong>Quoting accurately.</strong> With the caveat above: check the
        exact words against the audio before a quotation goes into anything
        assessed.</li>
        <li><strong>Keeping the lecture at all.</strong> Text is the format most
        likely to still open in ten years, on any machine, with no player and no
        login.</li>
      </ul>

      <h2 id="allowed">The permission question</h2>

      <p>Getting a transcript out of Panopto is subject to the same rules as
      getting the video, and those rules genuinely differ between institutions.
      <a href="download-panopto-lecture-recordings.html">How to download Panopto
      lecture recordings</a> covers it properly; the short version is that a
      personal study copy is widely allowed, redistribution is prohibited
      essentially everywhere, and asking is a two-click favour rather than an
      imposition.</p>

      <p>Transcribing audio you are entitled to have does not change that
      calculation in either direction. If you may keep the recording, you may
      keep a transcript of it. If you may not, a transcript is not a loophole.
      And if your lectures turn out not to be in Panopto at all, start with
      <a href="download-lecture-videos-from-canvas.html">how to download lecture
      videos from Canvas</a>, which covers all five systems.</p>

      <div class="cta-box">
        <h3>A whole semester of lectures, as text you can search</h3>
        <p>Tick as many courses as you like. Canvas Downloader finds the
        <strong>Panopto lecture recordings</strong> in each one and saves them as
        a searchable transcript and a timestamped subtitle file, alongside the
        video or audio if you want it, and alongside the slides and readings from
        the same courses.</p>
        <p>The transcription runs <strong>on your own computer</strong> with the
        models in the table above - nothing is uploaded, there is no account and
        no per-minute charge, and after the first model download it works with no
        network at all. Free and open source, Windows and macOS.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P7_FAQ = [
    ("Does Panopto give you a transcript automatically?",
     'Usually, now. Panopto machine-transcribes recordings to produce closed '
     'captions, and institutions are documenting a change to having that on by '
     'default for new content. Brown University\'s IT knowledge base dates it to '
     'on or before 11 May 2026, driven by Section 504 and WCAG 2.1 Level AA '
     'accessibility requirements. Tenants are configured independently, so check '
     'yours. Older recordings are not covered either way.'),
    ("How do I download the transcript from a Panopto lecture?",
     'Open the recording in the Panopto player, open the Captions or Transcript '
     'panel, and look for a download option there or in the player\'s menu. '
     'Panopto documents this as downloading captions from the viewer. What you '
     'get is a subtitle file, which is plain text with timestamps and opens in '
     'any text editor.'),
    ("Can I get the transcript if downloading the video is blocked?",
     'Often, yes. Captions are usually a separate permission from the recording, '
     'and a lecturer who has switched downloads off has frequently left captions '
     'alone, because turning accessibility features off is harder to justify. It '
     'is worth checking before concluding a lecture is locked.'),
    ("How long does it take to transcribe a lecture on my own laptop?",
     'It depends entirely on the model, and the range is about tenfold. Measured '
     'on a 10-core laptop CPU with no GPU: roughly 2 minutes per hour of lecture '
     'on the smallest model, about 10 minutes on a mid-sized one, and about 24 '
     'minutes on a large one. That is one machine on one clip rather than a '
     'benchmark, but the ordering holds.'),
    ("Should I use Large v3 Turbo for transcription?",
     'On a GPU, yes. On a CPU, no, and the reason is structural. Turbo is fast '
     'because its decoder has four layers instead of thirty-two. Its encoder is '
     'unchanged from the full model, and on a CPU the encoder is what dominates '
     'the time, so almost none of the speed-up arrives. On a laptop it lands in '
     'the group that is too slow to be practical.'),
    ("Is machine transcription accurate enough to revise from?",
     'For following the argument, yes. Panopto states its automatic captions are '
     'typically 90 to 95% accurate depending on audio quality, and the open '
     'models are in a similar band. The errors are not spread evenly, though: '
     'proper nouns and technical terms are where both fail, which is exactly '
     'what you were going to search for. Treat a transcript as a searchable '
     'index into the recording rather than as a document of record.'),
    ("Does transcribing a lecture upload it anywhere?",
     'It does not have to. Open speech-recognition models run on your own '
     'computer, so the audio never leaves it, and after the model is downloaded '
     'once the process needs no network at all. Paid online services do upload, '
     'which for lecture recordings is worth thinking about, since they usually '
     'contain other students.'),
    ("What is the difference between a .txt transcript and a .srt subtitle file?",
     'Only timestamps. A .srt carries a time for every line, so the text stays '
     'anchored to the recording and you can search the transcript, find the '
     'timestamp and jump to that minute. A .txt is tidier to read. Keep both if '
     'you can - the timestamps are what make a transcript a navigation tool '
     'rather than just a wall of words.'),
]

# ============================================================ PAGE 8 =========
# Grounded 2026-08-27. Cluster D of marketing/BLOG_PLAN.md - the app's clearest
# differentiator, with no page at all until now, and a cluster where every query
# resolves to "Canvas cannot".
#
# THE RESEARCH FOUND A BUILT-IN ROUTE THE PLAN DID NOT KNOW ABOUT, and it is
# the backbone of the page: students CAN export a course as offline HTML
# (Instructure KB 661316). Leading with it is the same call as article 2 leading
# with Panopto's own transcript - it is free, needs no software, and is the
# correct advice for anyone whose institution has it switched on.
#
# Instructure then documents its limits in their own words, and those limits are
# EXACTLY this cluster:
#  * "Discussions and quizzes only include the description."
#  * "All discussion replies (graded or ungraded) are considered submissions and
#    must be viewed online."
#  * "Content items locked by modules or by date are not included in offline
#    content."
#  * "Offline downloads include all content from the course at the time of the
#    download. You will need to download the course each time you want to view
#    updated course content."
#  * "Offline content cannot be downloaded once a course is concluded."  <- the
#    single most actionable sentence on this site: the only built-in route to
#    this material stops working at precisely the moment people go looking.
#  * And its own User Guidelines: "you may not reproduce or communicate any of
#    the content in the course, including exported files, without your
#    institution's prior written permission." Quoted rather than paraphrased.
#
# Other primary sources, all fetched 200 on 2026-08-27:
#  * Instructure KB 660734 - the full course export (.imscc) and what it holds.
#    INSTRUCTOR-ONLY, which is the asymmetry the page is built on.
#  * Instructure KB 661133 - allowing offline HTML export, i.e. proof it is an
#    administrator switch rather than a student feature.
#  * Instructure Community 618390 - the accepted answer, "As for Pages and
#    Assignments, I'm not sure of a quick way off the top of my head".
#  * Rice University Canvas guidance on "Let Students See Their Quiz Responses":
#    the Only Once After Each Attempt option means "Students will only be able
#    to view the results immediately after they have completed the quiz".
#
# HONESTY: the app fetches CLASSIC Quizzes (course.get_quizzes). New Quizzes is
# a separate LTI tool and is NOT covered. Stated plainly in the body, per the
# Phase 0b rule that limits belong where the claim is made and not in the box.

P8_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#notfiles">Why none of this is in the Files tab</a></li>
          <li><a href="#offline">The one built-in route, and its expiry date</a></li>
          <li><a href="#limits">What the offline export leaves out</a></li>
          <li><a href="#imscc">The export your lecturer can do and you cannot</a></li>
          <li><a href="#byhand">Saving each kind by hand</a></li>
          <li><a href="#quizzes">Quizzes are the urgent one</a></li>
          <li><a href="#worth">What is actually worth saving</a></li>
          <li><a href="#app">What this app does with it</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">Half of a Canvas course is not made of files. The quiz you
      revised from, the thread where the answer finally appeared, the Page with
      the reading list on it, the announcement that changed the exam format:
      none of that is in the Files tab. So none of it comes down when you zip
      that tab, and most guides to downloading Canvas never mention it.</p>

      <p>There is one built-in route to it. It has a hard deadline, and almost
      nobody knows about either.</p>

      <h2 id="notfiles">Why none of this is in the Files tab</h2>

      <p>A PDF your lecturer uploaded is a file. A Page they wrote is a set of
      rows in Canvas's database, rendered into a web page when you open it. Same
      for an announcement, a discussion thread, a quiz and an assignment brief.
      There is no document sitting on a disk anywhere for Canvas to hand you.</p>

      <p>That is why <a href="how-to-download-all-canvas-files.html">Download as
      Zip and every other file-based route</a> come back without it, and it is
      why the honest answer in Instructure's own community thread on downloading
      a whole course is
      <a class="src" href="https://community.instructure.com/en/discussion/618390/how-to-download-all-course-files-and-media-on-canvas" target="_blank" rel="noopener">"As for Pages and Assignments, I'm not sure of a quick way off the top of my head"</a>.</p>

      <h2 id="offline">The one built-in route, and its expiry date</h2>

      <p>Canvas has a feature called offline content, and students can use it.
      From the <strong>Modules</strong> page there may be an <strong>Export
      Course Content</strong> button that produces a zip of the whole course as
      browsable HTML - Pages, announcements, assignment details, embedded media,
      the lot, linked together and readable with no login.</p>

      <p>Most people have never seen it, for two reasons. It is
      <a class="src" href="https://community.instructure.com/en/kb/articles/661133-how-do-i-allow-course-content-to-be-exported-as-an-offline-html-file" target="_blank" rel="noopener">an administrator setting</a>
      that has to be switched on, so it is simply absent at many institutions.
      And it lives on the Modules page, which is not where anybody looks for a
      download.</p>

      <ol class="steps">
        <li>Open the course and click <strong>Modules</strong>.</li>
        <li>Look for <strong>Export Course Content</strong>, usually top right.
        If it is not there, your institution has not enabled it and this route is
        closed.</li>
        <li>Click it. The zip downloads directly if you stay on the page;
        otherwise Canvas emails you a link when it is ready.</li>
        <li>Unzip it and open the HTML file. It works offline, forever, with no
        Canvas account.</li>
      </ol>

      <div class="note warn">
        <p><strong>It stops working the moment the course ends.</strong>
        Instructure states it plainly:
        <a class="src" href="https://community.instructure.com/en/kb/articles/661316-how-do-i-view-course-content-offline-as-an-html-file-as-a-student" target="_blank" rel="noopener">"Offline content cannot be downloaded once a course is concluded."</a>
        So the only built-in route to this material closes at exactly the point
        people go looking for it. A course concludes on its own schedule, often
        while you still have an account and can still read everything on screen.
        That is one of the three separate endings covered in
        <a href="canvas-access-after-graduation.html">what happens to your Canvas
        access after graduation</a>. Use it during term, or not at all.</p>
      </div>

      <p>It is also a snapshot rather than a subscription: "you will need to
      download the course each time you want to view updated course content".
      One export in week 12 is not the same course as one in week 4.</p>

      <h2 id="limits">What the offline export leaves out</h2>

      <p>Worth knowing before you rely on it, and Instructure documents all of
      it in the same article:</p>

      <ul>
        <li><strong>"Discussions and quizzes only include the description."</strong>
        You get the prompt at the top of the discussion and the blurb at the top
        of the quiz. You do not get the thread, and you do not get the
        questions.</li>
        <li><strong>"All discussion replies (graded or ungraded) are considered
        submissions and must be viewed online."</strong> Which is the useful half
        of a discussion, gone by definition.</li>
        <li><strong>Anything locked</strong> - "content items locked by modules
        or by date are not included in offline content", so a module that unlocks
        later is simply absent.</li>
        <li><strong>Anything outside a module.</strong> The export is built from
        the Modules page, so a course that keeps material anywhere else exports
        that much less of itself.</li>
      </ul>

      <div class="note">
        <p><strong>Read Instructure's own user guidelines while you are there.</strong>
        The same article states: "When exporting course content, you may not
        reproduce or communicate any of the content in the course, including
        exported files, without your institution's prior written permission."
        That is about redistribution rather than about keeping a personal study
        copy, and it is the same line every route on this page sits behind.</p>
      </div>

      <h2 id="imscc">The export your lecturer can do and you cannot</h2>

      <p>Canvas has a second, much more complete export: a course export package,
      an <code>.imscc</code> file. Instructure's guide to
      <a class="src" href="https://community.instructure.com/en/kb/articles/660734-how-do-i-export-a-canvas-course" target="_blank" rel="noopener">exporting a Canvas course</a>
      lists what goes in it, and the list is the whole course: settings,
      syllabus, modules, assignments, quizzes, <strong>question banks</strong>,
      discussions, pages, announcements, rubrics, files, calendar events.</p>

      <p><strong>It requires a teacher role.</strong> That single fact explains
      most of the confusion around this subject: the good export exists, it is
      thoroughly documented, and every guide you find describing it was written
      for somebody with a different set of buttons than you have.</p>

      <p>It is not a waste of time to ask, though. A lecturer can run one in
      about a minute, and for a course you are about to lose it is a reasonable
      request - especially alongside asking for the recordings, which is the
      other thing worth asking about at the same time.</p>

      <h2 id="byhand">Saving each kind by hand</h2>

      <p>With no offline export, this is the fallback, and the mechanism is the
      same everywhere: <strong>print the page to PDF</strong>
      (<code>Ctrl</code>+<code>P</code> or <code>Cmd</code>+<code>P</code>, then
      Save as PDF). It is crude, it works everywhere, and it captures what you
      can see.</p>

      <ul>
        <li><strong>Pages.</strong> Open each one and print it. Check the Pages
        list in the course navigation rather than working from Modules - courses
        routinely have Pages that no module links to.</li>
        <li><strong>Announcements.</strong> The list view shows only previews, so
        open each one. Expand any replies first; they will not print
        collapsed.</li>
        <li><strong>Discussions.</strong> Expand the whole thread before
        printing, including "show more replies". A long thread prints badly and
        is still better than losing it.</li>
        <li><strong>Assignment briefs.</strong> Print the assignment page. Note
        that the brief and <a href="save-canvas-assignment-feedback.html">the
        feedback you were given</a> are separate problems with separate
        answers.</li>
        <li><strong>Quizzes.</strong> See below - this one has a timer on it.</li>
      </ul>

      <p>Budget realistically. A course with 30 Pages, 20 announcements and a
      dozen discussions is an afternoon, and you have several courses.</p>

      <h2 id="quizzes">Quizzes are the urgent one</h2>

      <p>Everything else on this page stays visible for as long as you can open
      the course. Quiz questions and your answers may not, and the reason is a
      setting your lecturer chose before you ever took it.</p>

      <p>Canvas offers <em>Let Students See Their Quiz Responses</em> with an
      option called <strong>Only Once After Each Attempt</strong>. Rice
      University's Canvas guidance describes what that does:
      <a class="src" href="https://canvasinfo.blogs.rice.edu/let-students-see-their-quiz-responses/" target="_blank" rel="noopener">"Students will only be able to view the results immediately after they have completed the quiz"</a>.
      Once. Ever.</p>

      <p>The option can also be switched off entirely, and results can carry
      show and hide dates so they disappear on a schedule. So the practical rule
      is blunt: <strong>if a quiz's questions and your answers are on screen in
      front of you, that may be the only time they ever will be.</strong> Print
      it to PDF before you close the tab.</p>

      <p>This matters more than it sounds for revision. A past quiz is the
      closest thing most courses give you to a specimen exam paper, and the
      version with your own wrong answers marked on it is worth considerably more
      than a clean copy.</p>

      <h2 id="worth">What is actually worth saving</h2>

      <p>Not all of it, and deciding is most of the work. In rough order:</p>

      <ol class="steps">
        <li><strong>Quizzes with your answers</strong>, for the reason above and
        because they may vanish first.</li>
        <li><strong>Pages that hold reading lists, formula sheets or
        instructions.</strong> These are the ones people come back to years
        later.</li>
        <li><strong>Discussion threads where a lecturer answered a question.</strong>
        Often the only place a real ambiguity in the course was ever
        resolved.</li>
        <li><strong>Assignment briefs</strong>, if you might reuse the work or
        need to prove what was asked.</li>
        <li><strong>Announcements</strong>, last. Most are administrative and
        expire on their own; a handful changed a deadline or an exam format and
        those are worth having.</li>
      </ol>

      <h2 id="app">What this app does with it</h2>

      <p>Canvas Downloader reads the Canvas API directly rather than the Files
      tab, so it can fetch the things that are not files and write them out as
      readable documents beside the slides: <strong>assignments, announcements,
      discussions with their replies, quizzes with their questions, the syllabus,
      rubrics, and the feedback on your own submissions</strong>. It does that
      for every course you select in one run, and it can put each kind in its own
      folder or leave everything inline.</p>

      <p>Two limits worth stating. It fetches <strong>Classic Quizzes</strong>;
      <em>New Quizzes</em> is a separate Instructure product delivered as an
      external tool, and it is not covered. It can also only ever save what
      your account is allowed to see. If a quiz's results are hidden from you by
      the setting above, they are hidden from any tool acting as you, which is
      exactly as it should be.</p>

      <div class="cta-box">
        <h3>The half of the course that is not a file</h3>
        <p>Tick as many courses as you like. Canvas Downloader saves the
        <strong>quizzes with their questions</strong> and the
        <strong>discussion threads with the replies</strong>, along with the
        announcements, the Pages, the assignment briefs and the syllabus. All of
        it as ordinary documents on your own disk, beside every file from the
        same courses.</p>
        <p>No Modules page, no administrator setting, and no deadline when the
        course concludes. Free and open source, Windows and macOS.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P8_FAQ = [
    ("Can I download Canvas Pages, discussions and announcements?",
     'Not through the Files tab, because none of them are files - they are '
     'database records Canvas renders into web pages. If your institution has '
     'enabled offline content there is an Export Course Content button on the '
     'Modules page that produces the course as browsable HTML. Otherwise the '
     'built-in answer is printing each page to PDF one at a time.'),
    ("What is Export Course Content on the Modules page?",
     'Canvas\'s offline content feature. It packages the course as HTML you can '
     'read with no login, and students can use it. The catch is that it is an '
     'administrator setting, so it is simply absent at many institutions. '
     'Instructure also states that offline content cannot be downloaded once a '
     'course is concluded.'),
    ("Does the offline HTML export include quiz questions and discussion replies?",
     'No. Instructure\'s own documentation says "Discussions and quizzes only '
     'include the description", and that all discussion replies, graded or '
     'ungraded, count as submissions and must be viewed online. So you get the '
     'quiz blurb and the discussion prompt, and not the questions or the '
     'thread.'),
    ("Why can students not export a Canvas course the way instructors can?",
     'The complete export - the .imscc course export package containing '
     'settings, syllabus, modules, assignments, quizzes, question banks, '
     'discussions, pages, announcements, rubrics and files - requires a teacher '
     'role. It exists and is well documented, which is why so many guides '
     'describe a button students do not have. Asking a lecturer to run one takes '
     'them about a minute.'),
    ("Can I still see my quiz answers after the course ends?",
     'Often not, and sometimes not even before it ends. Canvas has an option '
     'called Only Once After Each Attempt, under which students can view the '
     'results immediately after finishing and never again, and quiz results can '
     'also be switched off entirely or given hide dates. If a quiz and your '
     'answers are on screen, treat that as the only time and save it then.'),
    ("How do I save a Canvas discussion with all the replies?",
     'Expand the whole thread first, including any "show more replies" links, '
     'then print the page to PDF. The offline HTML export will not do it - '
     'replies count as submissions and are online-only - so it is either printing '
     'or a tool that reads the discussions API.'),
    ("Is it against the rules to save course content?",
     'Keeping a personal study copy of material you have legitimate access to is '
     'widely accepted; redistributing it is not. Instructure\'s own guidance on '
     'the offline export says you may not reproduce or communicate course '
     'content, including exported files, without your institution\'s prior '
     'written permission. Read that as a rule about sharing rather than about '
     'saving, and check your own institution\'s policy.'),
    ("Does this include New Quizzes?",
     'The offline HTML export gives only the description for any quiz, new or '
     'classic. Canvas Downloader fetches Classic Quizzes with their questions; '
     'New Quizzes is a separate Instructure product delivered as an external '
     'tool and is not covered, so for those the reliable route is still printing '
     'the results page while you can see it.'),
]

# ============================================================ PAGE 9 =========
# Grounded 2026-08-27. Cluster E of marketing/BLOG_PLAN.md - highest-intent
# traffic on the map, and the natural home for the trust story.
#
# WRITTEN AGAINST MEASURED TARGETS, not just to a word count. scratchpad's
# ai_tells.py showed the three previous articles drifting into the documented
# Claude signature: long multi-clause sentences held together by a pair of " - "
# dashes. Targets here: dash per 1k words under 4, sentences of 35+ words under
# 6%, short sentences over 16%, no banned lexicon, no "not X but Y", no
# six-item lists. Measured after writing, not assumed.
#
# Primary sources, all fetched 200 on 2026-08-27:
#  * Instructure KB 662901: "Using the Canvas API allows the access token holder
#    to access the same Canvas resources that you can access." That single
#    sentence is the whole scope answer and the spine of this page. Also:
#    "Access tokens should be treated with the same level of security as your
#    account password", and the awkward one - "It is a violation of Canvas API
#    policy for a user to generate an access token to insert into an
#    application. Applications must use approved authentication methods
#    instead."
#  * Instructure Community 660299, the token-security announcement: purpose
#    field required (8 Oct 2025); student tokens capped at 120 days (8 Oct
#    2025); admins can block students from generating tokens at all (10 Sep
#    2025); and the update at the foot of it - "As of July 30, 2026 Instructor
#    tokens have a mandatory expiration date set to no more than 90 days after
#    creation. Student token expiration is 30 days."
#
#    THE ANNOUNCED NUMBERS ARE NOT WHAT EVERY ACCOUNT SEES, and the page says so
#    rather than repeating the headline. A real student account checked in
#    August 2026 was offered 90 days, not 30, having previously been offered
#    120. The mechanism is in the same post and it is about ROLES, not
#    institutions: the short cap binds "users with only student roles", and a
#    longer life "can be achieved by giving the user any role other than student
#    (even with all permissions locked down)". Universities hand out extra roles
#    constantly - a TA enrolment, a designer role on one module, an induction
#    course you were added to as something else - so the settings page is the
#    only authority on your own number. Three site pages were corrected the same
#    way after they had briefly been given a hard "30 days".
#    The stated motive is worth quoting: "we have seen an uptick in students
#    setting up AI integrations to automatically review and complete assignments
#    on their behalf."
#  * Canvas API OAuth docs: "developer keys are issued by the admin of the
#    institution", and keys are "scoped to the institution they are issued
#    from". This is why the policy note above cannot simply be complied with by
#    an independent tool, and the page says so plainly rather than skating past.
#
# THE POLICY NOTE IS ADDRESSED HEAD ON, IN ITS OWN SECTION. Burying it would be
# the worst available choice on a page about trust, and a reader who finds it
# elsewhere afterwards has been given a reason to distrust everything else here.
#
# FIRST-HAND, VERIFIED IN THIS REPO 2026-08-27: the app performs ZERO HTTP
# writes against Canvas. A grep for post/put/patch/delete across core/, sync/,
# ui/, shared/, engine/ and app.py returns nothing outside the Panopto LTI
# handshake. Stated as a checkable claim, with the invitation to check it.
#
# STALE COPY THIS RESEARCH CAUGHT, fixed the same day: docs/guide.html told
# users to "leave the expiry blank" (Canvas now requires one), and
# docs/win-setup.html promised "you never do this again" (tokens now expire).
# Canvas's own KB video still demonstrates the blank-expiry flow, which is
# almost certainly where the site's wording came from originally.

P9_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#what">What a token actually is</a></li>
          <li><a href="#cannot">What it cannot do</a></li>
          <li><a href="#expiry">Why yours now expires, and why your number differs</a></li>
          <li><a href="#policy">The policy line, and why it is awkward</a></li>
          <li><a href="#blocked">If your university has switched them off</a></li>
          <li><a href="#safe">Keeping one safe</a></li>
          <li><a href="#app">What this app does with yours</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">Sooner or later a Canvas tool asks for an access token, and
      the question underneath is always the same one: how much am I handing
      over?</p>

      <p>Instructure answers it in a single sentence, and it is worth reading
      twice.</p>

      <h2 id="what">What a token actually is</h2>

      <p>A token is a long string of characters that identifies you to Canvas
      without a password. Software sends it with each request. Canvas checks it
      and answers as though you had asked in a browser.</p>

      <p>From Instructure's own documentation:
      <a class="src" href="https://community.instructure.com/en/kb/articles/662901-how-do-i-manage-api-access-tokens-in-my-user-account" target="_blank" rel="noopener">"Using the Canvas API allows the access token holder to access the same Canvas resources that you can access."</a></p>

      <p>The same resources. Nothing extra. A token gives nobody a teacher
      view and reaches no course you are not enrolled on. It is your own access,
      handed to you in a form a program can use, and that is all it is.</p>

      <p>You already rely on this without thinking about it. The Canvas mobile
      app holds one. So does every calendar feed, every plagiarism checker your
      university has wired in, every integration on the Approved Integrations
      list in your own settings. Go and look at that list; you will probably
      find several you never knowingly approved.</p>

      <h2 id="cannot">What it cannot do</h2>

      <p>Worth being specific, because the vague fear is usually worse than the
      real limits.</p>

      <ul>
        <li><strong>It cannot exceed your own access.</strong> If you can't see a
        course, neither can anything holding your token.</li>
        <li><strong>It is not your password.</strong> Nobody can log in as you
        with it, change your password, or see it. Canvas shows a token once, at
        creation, and never again.</li>
        <li><strong>It doesn't hide anything.</strong> Your administrators can
        list every token on your account, see what each one was for, and delete
        any of them.</li>
        <li><strong>It expires.</strong> More on that below, because the
        deadline got a lot shorter recently.</li>
      </ul>

      <p>What a token <em>can</em> do is everything you can do, which includes
      submitting work and posting to discussions. That is the real risk, and it
      is a risk about the software you paste it into rather than about tokens as
      an idea.</p>

      <h2 id="expiry">Why yours now expires, and why your number differs</h2>

      <p>Canvas tokens used to last forever. Most guides still say to leave the
      expiry field blank, and Instructure's own help video still demonstrates
      it. That advice is out of date, and it went out of date in stages.</p>

      <p>Instructure
      <a class="src" href="https://community.instructure.com/en/discussion/660299/strengthening-security-in-canvas-updates-to-user-access-token-management" target="_blank" rel="noopener">walked through the changes</a>
      in its own product blog:</p>

      <ul>
        <li><strong>September 2025.</strong> Administrators can stop students, or
        all non-admins, from generating tokens at all.</li>
        <li><strong>October 2025.</strong> Every token needs a stated purpose.
        Users with only student roles get a maximum life of 120 days.</li>
        <li><strong>July 2026.</strong> Those maximums drop. Instructor tokens
        expire within 90 days, and the student figure Instructure gives is
        30.</li>
      </ul>

      <p><strong>Do not take those numbers as your numbers.</strong> A real
      student account checked in August 2026 was offered <strong>90 days</strong>,
      not 30, having previously been offered 120. The announcement and the
      settings page disagreed, and the settings page is the one that counts.</p>

      <p>The mechanism is in the same post, and it is about roles rather than
      institutions. The short cap applies to "users with only student roles", and
      Instructure notes that a longer life "can be achieved by giving the user
      any role other than student (even with all permissions locked down)".
      Universities hand out extra roles constantly. A TA enrolment, a designer
      role on one module, a library or induction course you were added to as
      something other than a student: any of those can be why your page offers
      more time than the headline says.</p>

      <p>So the honest version is that the direction is one way and shortening,
      the exact figure is whatever your own page offers you, and a tool that
      reads Canvas on your behalf will need a fresh token every month or
      quarter. That is Canvas working as designed, not the tool failing.</p>

      <div class="note">
        <p><strong>The reason is stated openly, and it isn't really about
        downloading.</strong> Instructure's post says: "we have seen an uptick in
        students setting up AI integrations to automatically review and complete
        assignments on their behalf". The tightening is aimed at homework bots.
        Everything else that reads Canvas through a token pays for it, which is
        annoying and also fairly reasonable.</p>
      </div>

      <h2 id="policy">The policy line, and why it is awkward</h2>

      <p>The same Instructure page that explains tokens carries this: "It is a
      violation of Canvas API policy for a user to generate an access token to
      insert into an application. Applications must use approved authentication
      methods instead."</p>

      <p>Read plainly, that covers what every Canvas download tool asks you to
      do, this one included. It deserves a straight answer rather than a
      footnote.</p>

      <p>The approved method is OAuth, and OAuth needs a developer key. Canvas's
      API documentation is clear about where those come from:
      <a class="src" href="https://canvas.instructure.com/doc/api/file.oauth.html" target="_blank" rel="noopener">"developer keys are issued by the admin of the institution"</a>,
      and each key is scoped to the institution that issued it.</p>

      <p>Which means an independent tool cannot simply comply. There is no
      central registry to apply to. A tool serving students at four thousand
      universities would need four thousand separate keys, each one requested
      from an administrator who has no particular reason to answer. Meanwhile
      Canvas puts a <strong>+ New Access Token</strong> button in every student's
      settings page and always has.</p>

      <p>That gap is why user tokens are how essentially every independent Canvas
      tool works, from research scripts to browser extensions. That is the
      situation rather than an excuse for it, and three things follow:</p>

      <ul>
        <li><strong>If your institution offers an approved route, use it.</strong>
        Some publish an official export or an integration. That beats a token
        every time.</li>
        <li><strong>If your institution has switched student tokens off, take
        that as the answer.</strong> It is a deliberate decision by people
        responsible for your data.</li>
        <li><strong>If the button is there, understand what you are pasting it
        into.</strong> Which is the rest of this page.</li>
      </ul>

      <h2 id="blocked">If your university has switched them off</h2>

      <p>Some have. A student in Instructure's own community thread on
      downloading a course put it plainly:
      <a class="src" href="https://community.instructure.com/en/discussion/618390/how-to-download-all-course-files-and-media-on-canvas" target="_blank" rel="noopener">"Previously, I used access tokens to run an application for downloading the files, but my school has recently removed that feature."</a></p>

      <p>If the <strong>+ New Access Token</strong> button is missing from
      Account then Settings, that is what has happened, and no API-based tool can
      work around it. Two routes survive. The ones built into Canvas -
      <a href="how-to-download-all-canvas-files.html">Download as Zip and the
      other built-in methods</a> for files, and
      <a href="save-canvas-pages-quizzes-discussions.html">the offline HTML
      export</a> for the parts that are not files. And <strong>browser
      extensions</strong>, which ride the Canvas session your browser already
      has and never touch a token: see
      <a href="canvas-download-tools-compared.html">how the download tools
      compare</a>.</p>

      <h2 id="safe">Keeping one safe</h2>

      <p>Instructure's guidance is one line: treat a token
      <a class="src" href="https://community.instructure.com/en/kb/articles/662901-how-do-i-manage-api-access-tokens-in-my-user-account" target="_blank" rel="noopener">"with the same level of security as your account password"</a>.
      In practice that comes down to four habits.</p>

      <ol class="steps">
        <li><strong>Give it a purpose you'll recognise.</strong> Canvas now
        requires one. In six months it is the only way you will know which token
        belongs to what.</li>
        <li><strong>Never paste it into a chat, an email or a screenshot.</strong>
        This is how tokens actually leak. Not clever attacks, just a screenshot
        of a settings page.</li>
        <li><strong>Don't reuse one across tools.</strong> Separate tokens mean
        you can revoke one without breaking the others.</li>
        <li><strong>Delete it when you're done.</strong> Account, Settings,
        Approved Integrations, bin icon. It takes a second and it works
        immediately.</li>
      </ol>

      <p>That last one is the part people forget. A token you deleted cannot be
      misused by anything, including by software you have stopped trusting. If
      you ever have a doubt, delete first and ask afterwards; the cost is
      generating a new one.</p>

      <h2 id="app">What this app does with yours</h2>

      <p>Being concrete, since a page about trust that stays vague is not worth
      much.</p>

      <ul>
        <li><strong>It reads. It never writes.</strong> There is no code path in
        this app that submits, posts, edits or deletes anything in Canvas. The
        source is public, and a search for the write methods across the whole
        codebase returns nothing.</li>
        <li><strong>The token stays on your computer</strong>, in Windows
        Credential Manager or the macOS Keychain, which is the same place your
        other saved logins live. It is not sent anywhere except to your own
        Canvas.</li>
        <li><strong>There is no server.</strong> The app runs locally, talks to
        your institution's Canvas, and writes files to a folder you pick.
        Nothing routes through anybody else, because there is nobody else.</li>
        <li><strong>You can check all of that</strong>, which is the point of it
        being open source rather than a claim about our character.</li>
      </ul>

      <p>Canvas's expiry applies here like anywhere else. The app remembers the
      token so you are not retyping it, and when Canvas expires it the app says
      so and sends you to the right page.</p>

      <div class="cta-box">
        <h3>Your own access, pointed at your own disk</h3>
        <p>Canvas Downloader uses your token to do one thing: read the courses
        you are already enrolled on and write them to a folder you choose. Every
        course in one run, with the slides, the readings, the
        <strong>Panopto lecture recordings</strong>, the quizzes, the discussions
        and the feedback you were given.</p>
        <p>Free and open source, Windows and macOS. It reads and never writes,
        there is no account and no server, and the token never leaves your
        machine.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P9_FAQ = [
    ("What can someone do with my Canvas access token?",
     'Exactly what you can do, and nothing else. Instructure puts it as "the '
     'same Canvas resources that you can access", so a token cannot reach '
     'courses you are not on or give anyone a teacher view. It can do the '
     'things you can do, though, including submitting work, which is why it is '
     'worth treating like a password.'),
    ("Is an access token the same as my Canvas password?",
     'No. It cannot be used to log in as you, it will not let anyone change '
     'your password, and Canvas shows it exactly once when you create it. '
     'Instructure still says to guard it as carefully as a password, because '
     'anything holding it can act as you inside Canvas.'),
    ("Why does my Canvas token keep expiring?",
     'Because Canvas now requires an expiry date. Users with only student roles '
     'were capped at 120 days in October 2025, and Instructure\'s July 2026 '
     'update gives 90 days for instructor tokens and 30 for student ones. Your '
     'own page may offer something different - a real student account checked '
     'in August 2026 was offered 90 - because the short cap applies only to '
     'accounts holding nothing but student roles, and an extra role anywhere '
     'lifts it. Whatever the number, expect to make a new token periodically.'),
    ("Why did Canvas restrict access tokens?",
     'Instructure said so directly: it had seen "an uptick in students setting '
     'up AI integrations to automatically review and complete assignments on '
     'their behalf". The restrictions are aimed at homework automation. Tools '
     'that only read your own material pay the same price.'),
    ("There is no New Access Token button in my Canvas settings",
     'Your institution has switched off token generation for students, which '
     'administrators have been able to do since September 2025. Nothing works '
     'around it. What is left is the routes built into Canvas: Download as Zip '
     'for a course\'s Files tab, and the offline HTML export from the Modules '
     'page if your institution allows that one.'),
    ("Is it against Canvas policy to paste a token into an app?",
     'Instructure\'s documentation says applications should use approved '
     'authentication instead, meaning OAuth. The difficulty is that OAuth needs '
     'a developer key, and Canvas\'s API docs say those "are issued by the admin '
     'of the institution" and are scoped to it - so an independent tool would '
     'need one from every university separately. That is why user tokens are '
     'how nearly every independent Canvas tool works. If your institution '
     'offers an approved route, use that instead.'),
    ("How do I delete a Canvas access token?",
     'Account, then Settings, then find it under Approved Integrations and '
     'click the bin icon. It stops working immediately. If you suspect a token '
     'has been exposed, delete it first and work out what happened afterwards - '
     'making a new one takes under a minute.'),
    ("Can my university see that I made a token?",
     'Yes. Since October 2025 administrators can view every user-generated '
     'token on an account, read the purpose you set for it, and delete any of '
     'them. Tokens are not a way to do anything quietly, and it is better to '
     'know that than to assume otherwise.'),
]

# =========================================================== PAGE 10 =========
# Grounded 2026-08-27. Article 5 of marketing/BLOG_PLAN.md Phase 2, and the one
# STRATEGY.md already required: "Say all of this on the site, fairly ...
# including the cases where an extension or a script is the better answer."
#
# THE CONFLICT OF INTEREST IS DISCLOSED IN THE FIRST PARAGRAPH. A comparison
# page written by one of the competitors is worth nothing unless it says so
# before the reader works it out, and it is worth a great deal if it then
# behaves accordingly. Three of the five recommendations in "which to pick"
# point somewhere other than this app.
#
# RESEARCH CORRECTED THE COMPETITOR TABLE IN STRATEGY.md, which was verified
# 2026-08-20 and is now partly wrong. It says extensions "Work per page not per
# account; no 'all courses'; no memory between runs". jasp-nerd's extension does
# all three: it selects multiple courses from the dashboard, and it has an
# "Incremental mode [that] skips files you've already downloaded on previous
# runs". Two of the three things STRATEGY.md calls "the three things no
# competitor combines" are therefore matched by a single free extension. Said
# plainly here, and flagged for STRATEGY.md.
#
# What survives as genuinely ours, checked against their own documentation:
#  * Panopto. jasp-nerd states it outright: "Content hosted by third-party LTI
#    tools (Turnitin, Panopto, external videos) lives outside Canvas and can't
#    be downloaded."
#  * Conversion - Office to PDF, video to audio, local transcription.
#  * Edit protection on re-sync (the _NewVersion diversion).
#  * Quiz questions. davekats' script "cannot capture quiz data".
#
# What is genuinely theirs, and the page leads with it:
#  * NO TOKEN. jasp-nerd uses session cookies: "there's nothing to configure."
#    Against Canvas's 2025-2026 token expiry crackdown that advantage is
#    growing, not shrinking, and article 4 documents exactly why.
#
# SCALE, checked via the GitHub API on 2026-08-27, and reported even though we
# lose: davekats 265 stars, jasp-nerd 38, kas 14 (last pushed December 2023),
# jamubc 5, this project 2. Stars are a poor proxy for a desktop app shipped
# through an installer and the Microsoft Store, and saying so while still
# printing the number is the only version of that argument worth making.
# "Last updated" is the signal a reader should actually use, so the page says
# that instead of leading with popularity.

P10_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#bias">Who wrote this</a></li>
          <li><a href="#shapes">Three shapes, and what each is built to be</a></li>
          <li><a href="#job">Which job are you actually doing</a></li>
          <li><a href="#extensions">Browser extensions</a></li>
          <li><a href="#scripts">Scripts and command-line tools</a></li>
          <li><a href="#apps">What a resident app does that neither can</a></li>
          <li><a href="#losses">Where my own app loses</a></li>
          <li><a href="#table">Side by side</a></li>
          <li><a href="#pick">Which one you should actually use</a></li>
          <li><a href="#judge">How to judge any of them</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">There are three ways to get a Canvas course onto your
      computer without doing it by hand: a browser extension, a script, or a
      desktop app. Which one suits you depends less on their feature lists than
      on how long you need the thing to keep working.</p>

      <h2 id="bias">Who wrote this</h2>

      <p>I built one of the options. That is a real conflict of interest and you
      should read the rest of this page knowing it.</p>

      <p>What I can offer instead of neutrality is specifics. Every claim below
      about another tool comes from that tool's own documentation, with a link,
      and where a competitor is better I have said which one and why. Three of
      the five recommendations further down do not point at my app.</p>

      <h2 id="shapes">Three shapes, and what each is built to be</h2>

      <p>The shape decides more than any feature list does, because it decides
      how long the tool is around.</p>

      <ul>
        <li><strong>A browser extension is a button.</strong> It exists while
        the popup is open and then it is gone again. Nothing to install past
        the add-on, nothing to configure, nothing running while you are looking
        at something else. That is the format doing exactly what the format is
        for.</li>
        <li><strong>A script is something you run.</strong> It does what you
        told it to, from a terminal, and it stops when it finishes. Its
        interface is a command line, and that is an audience choice rather than
        an oversight.</li>
        <li><strong>A desktop app is installed.</strong> It has a window you
        open, it keeps a record of what it did last time, and it can do work
        while you are in a lecture.</li>
      </ul>

      <p>What all three have in common is the verb. They fetch. Point them at a
      course, get a copy, and the differences are how much they can reach and
      how much setup they cost you first. Canvas's own <strong>Download as
      Zip</strong> button does the same job with less reach and no setup at
      all.</p>

      <h2 id="job">Which job are you actually doing</h2>

      <p>There are two versions of this task and from the outside they look
      identical.</p>

      <p><strong>Taking a snapshot.</strong> Your access ends next month, or the
      semester is over and you want the material somewhere safe. You run
      something once, you get a folder, you are done. Every tool on this page
      does this. Pick on setup cost and the extension wins.</p>

      <p><strong>Keeping a folder current.</strong> You are two weeks into a
      semester. Slides go up on Mondays and Thursdays, sometimes a corrected
      version of one you already have. You have annotated four of them. You want
      the folder on your laptop to be right in March without you having to think
      about it. That is a different question, and the answer turns on what the
      tool remembers and when it runs.</p>

      <p>Most comparisons only test the first job. It is the easier one, and it
      is the one where these tools are hardest to tell apart.</p>

      <h2 id="extensions">Browser extensions</h2>

      <p>Several exist. The most capable I have found is
      <a class="src" href="https://github.com/jasp-nerd/canvas-course-downloader" target="_blank" rel="noopener">jasp-nerd's Canvas Course Downloader</a>,
      which is free, open source, and on the Chrome Web Store. It is a genuinely
      good piece of work and it is worth trying before anything else.</p>

      <p><strong>The advantage that matters most: no access token.</strong> It
      uses the Canvas session you already have. In its own words, "there's
      nothing to configure". That gap has widened over the past year, because
      Canvas has been steadily shortening how long a token lives. See
      <a href="canvas-access-token-explained.html">what a Canvas access token is
      and what it cannot do</a> for the timeline. An extension sidesteps all of
      it.</p>

      <p>It also does more than extensions used to. It downloads files, pages,
      assignments, announcements, discussions, modules, syllabus and grades. You
      can select several courses at once. It has an incremental mode that
      "skips files you've already downloaded on previous runs", so it does
      remember the useful half.</p>

      <p>Its stated limits are worth quoting, because they are the honest
      boundary of the whole category:</p>

      <ul>
        <li><strong>No lecture recordings.</strong> "Content hosted by
        third-party LTI tools (Turnitin, Panopto, external videos) lives outside
        Canvas and can't be downloaded." That is true of every extension, and it
        follows from where those files live rather than from a gap somebody
        forgot to fill.</li>
        <li><strong>Pages and assignments arrive as HTML summaries</strong>,
        rather than exact copies.</li>
        <li><strong>No file conversion.</strong> A PowerPoint stays a
        PowerPoint.</li>
      </ul>

      <p>The rest is the shape. A popup cannot run on Thursday morning while you
      are asleep, cannot show you what changed and then wait, and has nowhere to
      put a record of a file you annotated. None of that is a criticism of the
      code. It is what a popup is.</p>

      <p>One thing to check yourself: permissions. This one is scoped narrowly
      to Canvas domains, which is the right way to do it, and it is open source
      so you can verify that. Not all of them are either. An extension asking to
      read every page you visit is asking for a lot, and the Chrome Web Store
      listing tells you what it wants before you install.</p>

      <h2 id="scripts">Scripts and command-line tools</h2>

      <p>A handful of GitHub projects do this well. The most established is
      <a class="src" href="https://github.com/davekats/canvas-student-data-export" target="_blank" rel="noopener">davekats/canvas-student-data-export</a>,
      at 265 stars when I checked in August 2026, which exports assignments and
      their submissions, announcements, discussions, pages, files and modules
      across all your courses. Most of these projects build on
      <a class="src" href="https://github.com/ucfopen/canvasapi" target="_blank" rel="noopener">ucfopen/canvasapi</a>,
      the University of Central Florida's Python wrapper, which is also what this
      app uses underneath.</p>

      <p>Scripts win on flexibility. If you want the output shaped a particular
      way, or you want it on a cron job, or you want to read exactly what it does
      before you run it, nothing else comes close. For a computing student this
      is plainly the right answer.</p>

      <p>They are also written by developers for developers, and it shows in
      what they ask of you.</p>

      <ul>
        <li><strong>Setup.</strong> Python 3.8 or newer, a dependency install, a
        credentials file, and an access token. davekats' HTML snapshot feature
        additionally wants Node 16 and a browser cookies file.</li>
        <li><strong>Maintenance is yours.</strong> When Canvas changes something
        or a dependency breaks, you are the one reading the traceback.</li>
        <li><strong>Coverage varies.</strong> davekats' own notes say it cannot
        capture quiz data. Others are narrower still.</li>
      </ul>

      <p>If a terminal is not somewhere you are comfortable, the honest answer
      is that this category was not built with you in mind, and there is no
      shame on either side of that.</p>

      <div class="note warn">
        <p><strong>Check the last commit date before you trust a script.</strong>
        Of the repositories I looked at, one popular one had not been touched
        since <strong>December 2023</strong>. Canvas has changed its token rules
        twice since then. An abandoned tool does not announce itself. It fails
        one day with an error you have to diagnose yourself.</p>
      </div>

      <h2 id="apps">What a resident app does that neither can</h2>

      <p>This is the category my own project is in, so check the claims rather
      than taking the framing. Every one of these is a screen you can look at
      after installing it, and the next section is the other side of the
      ledger.</p>

      <p>An app is installed, so it can keep state, run on a schedule, and talk
      to software already on your machine. Those three capabilities are where
      everything below comes from.</p>

      <h3>It shows you what changed before it touches anything</h3>

      <p><strong>Analyze, Review &amp; Sync</strong> compares the folder on your
      disk against the course on Canvas, and then it stops. What you get is a
      review screen, sorted: <strong>New Files</strong>, <strong>Updates
      Available</strong>, a separate list for updates to files
      <strong>you have edited yourself</strong>, <strong>Deleted on
      Canvas</strong>, and <strong>Deleted Locally</strong>. Every row has a
      checkbox. Nothing downloads until you press the button.</p>

      <p>Smart Select ticks or unticks a whole filetype across every course at
      once, so "all the PDFs, none of the 400 MB recordings" is two clicks.</p>

      <p>If you only look at one thing on this page, look at that screen. The
      other tools fetch first and tell you afterwards.</p>

      <h3>Quick Sync, for the other ninety percent of the time</h3>

      <p>Most weeks you do not want a review screen. <strong>Quick Sync</strong>
      takes the new files and the safe updates and leaves everything else where
      it is. It skips anything you have edited, anything you deleted on purpose,
      and anything you told it to ignore. It takes about as long as making
      coffee.</p>

      <h3>Today's files</h3>

      <p>Add the courses you are actually taking to a daily list and the app
      fetches their new material on its own. The <strong>Today</strong> page
      then shows what arrived today across all of them, in one list, with the
      course each file came from.</p>

      <p>On a normal Tuesday you open it, see three new slide decks from two
      courses, and close it again. No course pages, no clicking through modules,
      no wondering whether you missed something. This is the feature I would
      have wanted as a student, and a popup or a terminal command cannot be
      it.</p>

      <h3>The files arrive usable</h3>

      <p>Most students meet this problem within a week of trying to study with
      an AI tool. NotebookLM accepts PDFs, plain text and Markdown. It does not
      accept <code>.pptx</code>, <code>.doc</code>, or the HTML that Canvas
      exports its Pages as. Claude is the same. So the folder you just
      downloaded has to be converted before it is any use, one file at a
      time.</p>

      <p>Canvas Downloader converts on the way down. PowerPoint and Word become
      PDF, Canvas Pages become Markdown, code files become plain text, lecture
      video becomes audio if you ask for it. What lands in the folder can be
      dragged straight into a notebook. There is a full breakdown of what each
      AI tool will and will not take in
      <a href="canvas-files-into-notebooklm.html">getting Canvas files into
      NotebookLM</a>.</p>

      <p>No other tool on this page does this, and I doubt that is an oversight.
      Converting a PowerPoint needs software installed on your machine, and a
      browser extension cannot reach any of it.</p>

      <h3>It keeps the copy you wrote on</h3>

      <p>You annotate a lecture PDF on Tuesday. On Friday the lecturer
      re-uploads it with a corrected slide. To any of these tools that is the
      same file with a newer timestamp, so it gets overwritten and your notes
      are gone.</p>

      <p>This one checks whether you changed the file, keeps yours, and puts the
      new version beside it with <code>_NewVersion</code> in the name. It sounds
      like a small thing until it happens in week nine.</p>

      <h3>Panopto lecture recordings</h3>

      <p>As video, as audio, or as a transcript produced on your own machine
      with no upload anywhere. Panopto sits outside Canvas, so this is the one
      gap the extensions are explicit about not being able to cross. Quiz
      questions come down too, and not only the quiz titles.</p>

      <h2 id="losses">Where my own app loses</h2>

      <p>This part is longer than the marketing would like, and it should be.</p>

      <p><strong>It is the newest and least proven thing here.</strong> davekats'
      script has 265 GitHub stars. Mine has 2. That gap is real, and part of
      what it measures is real too: that project has been around for years, and
      far more people have read its code than have read mine.</p>

      <p>It also counts a different population. A star is a developer bookmarking
      a repository. Nobody stars an app they installed from the Microsoft Store,
      because most people who install one have never opened GitHub in their
      lives. Against those 2 stars, this app has been installed over 900 times.
      The two numbers count different people, and those two groups are exactly
      the audiences the two shapes were built for. I would rather show you both
      than pick the flattering one.</p>

      <p><strong>It needs an access token</strong>, which an extension does not,
      and Canvas keeps making tokens shorter-lived. The install is <strong>a few
      hundred megabytes</strong> against an extension's few hundred kilobytes.
      And it <strong>ships unsigned</strong>, so Windows and macOS both warn you
      the first time you open it, and clicking through that is on you.</p>

      <p>If any of that is a problem for you, one of the tools above is
      genuinely the better answer, and I would rather say so here than have you
      find out after installing.</p>

      <h2 id="table">Side by side</h2>

      <p>Checked August 2026 against each project's own documentation.</p>

      <div class="tbl-wrap" tabindex="0" role="region"
        aria-label="Comparison of Canvas download tool categories">
        <table class="cmp">
          <thead>
            <tr>
              <th>What you want</th>
              <th>Extension</th>
              <th>Script</th>
              <th>This app</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>No access token needed</td>
              <td class="yes">Yes</td><td class="no">No</td><td class="no">No</td></tr>
            <tr><td>Nothing to install but a browser add-on</td>
              <td class="yes">Yes</td><td class="no">No</td><td class="no">No</td></tr>
            <tr><td>No terminal, no code</td>
              <td class="yes">Yes</td><td class="no">No</td><td class="yes">Yes</td></tr>
            <tr><td>Several courses in one run</td>
              <td class="yes">Yes</td><td class="part">Varies</td><td class="yes">Yes</td></tr>
            <tr><td>Pages, assignments, announcements</td>
              <td class="yes">Yes</td><td class="part">Varies</td><td class="yes">Yes</td></tr>
            <tr><td>Quiz questions</td>
              <td class="part">Varies</td><td class="no">Rarely</td><td class="yes">Yes</td></tr>
            <tr><td>Skips what it already has</td>
              <td class="part">Some</td><td class="part">Varies</td><td class="yes">Yes</td></tr>
            <tr><td>Shows you what changed before downloading</td>
              <td class="no">No</td><td class="no">No</td><td class="yes">Yes</td></tr>
            <tr><td>Fetches new material on its own each day</td>
              <td class="no">No</td><td class="part">If you script it</td><td class="yes">Yes</td></tr>
            <tr><td>Keeps your edited copies safe</td>
              <td class="no">No</td><td class="no">No</td><td class="yes">Yes</td></tr>
            <tr><td>Converts as it downloads, ready for AI tools</td>
              <td class="no">No</td><td class="no">No</td><td class="yes">Yes</td></tr>
            <tr><td>Panopto lecture recordings</td>
              <td class="no">No</td><td class="no">No</td><td class="yes">Yes</td></tr>
          </tbody>
        </table>
      </div>

      <h2 id="pick">Which one you should actually use</h2>

      <p><strong>You want one course, today, with no fuss.</strong> Canvas's own
      <strong>Download as Zip</strong>. It needs no software at all and it is in
      front of you already. It is also better than its reputation:
      <a href="what-canvas-download-as-zip-misses.html">measured across 33 real
      courses</a> it missed 0.8% of files wherever the Files tab worked. See
      <a href="how-to-download-all-canvas-files.html">the five built-in
      methods</a> before installing anything.</p>

      <p><strong>Your institution has switched off student access tokens.</strong>
      An extension is your only option, because every API tool is closed to you.
      This happens more often than you would think and it is worth checking
      first.</p>

      <p><strong>You want a tidy archive of several courses and you would rather
      not install a desktop app.</strong> A browser extension. It will cover most
      of what you want, it costs you nothing, and there is no token to renew
      every few months.</p>

      <p><strong>You can write code and you want it your way.</strong> A script,
      built on canvasapi. You will spend an evening on it and get exactly what
      you asked for.</p>

      <p><strong>You are going to be doing this all semester, or all
      degree.</strong> That is the case my app was built for, and it is the one
      the other two shapes were not built for. A folder that updates itself, a
      review screen for the weeks you want to look before it acts, files that
      are usable the moment they land, and your annotated copies left alone.
      Lecture recordings and transcripts on top if you need them.</p>

      <h2 id="judge">How to judge any of them</h2>

      <p>Start with the question this page has been circling: are you taking a
      snapshot, or keeping a folder? Then four more, in the order that
      matters.</p>

      <ol class="steps">
        <li><strong>When was it last updated?</strong> Canvas changes. A tool
        untouched for a year is a tool that will break without warning.</li>
        <li><strong>Where does your token or session go?</strong> The answer
        should be "nowhere". If a tool sends your credentials to somebody's
        server so it can do the work for you, that is a different proposition
        entirely, whatever the feature list says.</li>
        <li><strong>Can you read the source?</strong> Every tool on this page is
        open source. There are closed ones, and I would not use one for
        this.</li>
        <li><strong>What does it ask for?</strong> An extension scoped to Canvas
        domains is reasonable. One that wants every page you visit is not.</li>
      </ol>

      <p>Whatever you choose, do it before you need it. Access ends on schedules
      nobody tells you about, which is the subject of
      <a href="canvas-access-after-graduation.html">what happens to your Canvas
      access after graduation</a>.</p>

      <div class="cta-box">
        <h3>One folder, current, all semester</h3>
        <p>Canvas Downloader is built to sit on your machine for a degree rather
        than for one download. It shows you what changed before it touches
        anything, fetches the new material on its own each day, converts
        PowerPoint and Canvas Pages into files you can drag straight into
        NotebookLM or Claude, and leaves the copies you have annotated alone.
        Panopto lecture recordings come down in the same run, as video, as
        audio, or as a transcript made on your own computer.</p>
        <p>Free and open source, Windows and macOS. If a one-off copy is all you
        need, an extension will do that faster.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P10_FAQ = [
    ("What is the best way to download all files from Canvas?",
     'It depends on how much you need and how long you need it to keep working. '
     'Canvas\'s own Download as Zip is the fastest route to a single course and '
     'needs nothing installed. Past that, a browser extension will cover most of '
     'several courses without an access token. Only a desktop app keeps a folder '
     'current on its own, converts files as they arrive, or reaches lecture '
     'recordings, because a browser cannot get outside Canvas and a script has '
     'nothing running between the times you run it.'),
    ("What is the difference between downloading a Canvas course and syncing it?",
     'A download is a snapshot. You run it, you get a folder, and the folder is '
     'wrong again the next time your lecturer uploads something. A sync compares '
     'what is on your disk against what is on Canvas and fetches only the '
     'difference, which means it can also tell you what changed, skip files you '
     'have edited, and run on a schedule. Most tools in this category download. '
     'Syncing needs somewhere to keep a record between runs, which is why it '
     'tends to be a desktop app that does it.'),
    ("Do Canvas downloader extensions need an API token?",
     'No, and it is their main advantage. They use the Canvas session your '
     'browser already has, so there is nothing to generate and nothing to renew. '
     'Since Canvas now forces access tokens to expire, that advantage has grown '
     'rather than shrunk.'),
    ("Can a browser extension download Panopto lecture recordings?",
     'No. Panopto is a separate system that Canvas links out to, so the '
     'recordings are not Canvas files. jasp-nerd\'s extension says so directly: '
     'content hosted by third-party tools like Panopto "lives outside Canvas and '
     'can\'t be downloaded". A tool has to talk to Panopto itself.'),
    ("Do I need to be technical to use one of these?",
     'For an extension or a desktop app, no. Install it, sign in, click. The '
     'command-line tools are a different matter: they want Python, a dependency '
     'install, a credentials file and a terminal, and when something breaks the '
     'fixing is yours. They are written by developers for developers, which is a '
     'legitimate audience to write for and may simply not be you.'),
    ("Are Canvas downloader browser extensions safe?",
     'The good ones are open source and scoped to Canvas domains, which you can '
     'check on the Chrome Web Store listing before installing. Be more careful '
     'with an extension that requests access to every site you visit, or one '
     'whose source you cannot read. The permission list is the thing to read, '
     'not the review score.'),
    ("Will these tools overwrite files I have annotated?",
     'Most of them will, and it is worth knowing before it costs you a semester '
     'of notes. From the outside your annotated PDF is the same file with an '
     'older timestamp than the one now on Canvas, so a tool that fetches updates '
     'will replace it. Canvas Downloader checks whether you changed the file and '
     'saves the new version beside yours instead. If you use anything else, keep '
     'your annotated copies in a separate folder the tool never writes to.'),
    ("How do I know if a Canvas download tool is abandoned?",
     'Look at the date of the last commit on GitHub, or the last update date on '
     'the Chrome Web Store. One popular script I checked had not been touched '
     'since December 2023, and Canvas has changed its access token rules twice '
     'since. Abandoned tools do not warn you. They stop working one day.'),
    ("Is Canvas Downloader better than the alternatives?",
     'For one download it is not obviously better than a free extension, and it '
     'asks more of you to set up. It is built for the other job: keeping a '
     'course folder right across a semester without you managing it, with a '
     'review screen before anything is written, files converted so they work in '
     'AI study tools, lecture recordings and transcripts, and your edited copies '
     'protected. I do not know of another tool that covers that combination. I '
     'built it, so weigh this answer accordingly.'),
    ("Can I use more than one of these?",
     'Yes, and it is often sensible. An extension for a quick grab of one messy '
     'module, something API-based for the material you keep all semester. They '
     'read the same Canvas and write ordinary files, so nothing conflicts as '
     'long as you point them at different folders.'),
]

P11_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#staircase">Three deadlines, not one</a></li>
          <li><a href="#trap">The official backup tool switches off with the course</a></li>
          <li><a href="#priority">What to save, in priority order</a></li>
          <li><a href="#hour">If you have an hour</a></li>
          <li><a href="#properly">If you have longer</a></li>
          <li><a href="#verify">How to check the backup is complete</a></li>
          <li><a href="#after">If you have already lost access</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">Most people picture one deadline. There are at least
      three, they belong to different systems, and they close in roughly the
      reverse of the order you would want.</p>

      <h2 id="staircase">Three deadlines, not one</h2>

      <p>Graduation is the date everyone has in mind. It is rarely the one that
      costs anything, because by then the material you most wanted has usually
      been gone for weeks.</p>

      <h3>Door one: the lecture recordings</h3>

      <p>This is normally the first to close, and it catches people out because
      Canvas itself still works. Panopto is a separate system with its own
      rules, and those rules tend to be tied to the teaching term rather than to
      your enrolment.</p>

      <p>Stanford tells staff that viewers
      <a class="src" href="https://cgoe.stanford.edu/panopto-help/panopto-usage-guidelines" target="_blank" rel="noopener">"will no longer have access to video recordings under the Panopto Course Videos tool, typically the Sunday after grades are due"</a>.
      The same university gives graduating students 120 days of Canvas access.
      Days against months, at one institution, for two halves of the same
      course.</p>

      <p>Harvard is blunter. Its retention policy states that
      <a class="src" href="https://www.huit.harvard.edu/panopto-course-content-retention-policy" target="_blank" rel="noopener">"for courses that are concluded, students will no longer see any Panopto videos, whether they are in an archived state or active"</a>.
      The same policy archives recordings uploaded more than two years ago and
      deletes archived recordings uploaded more than four years ago, in a sweep
      run every January and June.</p>

      <p>So the largest files, the slowest to download and the ones nobody else
      has a copy of, are the ones with the shortest clock on them.</p>

      <h3>Door two: the course concludes</h3>

      <p>A concluded course goes read-only. You can open it, read it, and look
      at your grades. You cannot export it, which is the next section and the
      part worth knowing before anything else.</p>

      <p>This one can also happen while you are still very much a student.
      Conclusion is tied to the course, not to you, so a first-year module can
      close behind you while you are three years from graduating.</p>

      <h3>Door three: your enrolment or your account</h3>

      <p>The last one, and the only one most people plan for. When it closes,
      everything goes at once, including any access token you had generated for
      a downloading tool.</p>

      <h2 id="trap">The official backup tool switches off with the course</h2>

      <p>Canvas does have a student-usable export, and hardly anyone knows about
      it. There are two routes.</p>

      <ul>
        <li><strong>Offline HTML.</strong> On a course's Modules page there may
        be an <strong>Export Course Content</strong> button. It packages the
        course as browsable HTML you can open with no login: Pages,
        announcements, assignment details, embedded media.</li>
        <li><strong>ePub.</strong> Account, then Settings, then
        <strong>Download Course Content</strong>, then Generate ePub. A
        <strong>Download Associated Files</strong> link gives you a zip of
        everything the ePub cannot hold, which in practice means media and
        Office documents.</li>
      </ul>

      <p>Both share a limitation Instructure
      <a class="src" href="https://community.instructure.com/en/kb/articles/661316-how-do-i-view-course-content-offline-as-an-html-file-as-a-student" target="_blank" rel="noopener">states plainly</a>:
      offline content cannot be downloaded once a course is concluded.</p>

      <p>Now read that against door two. The course concludes, you go looking
      for something, you find the export button, and it will not run. The tool
      built to back the course up has a shorter life than the course.</p>

      <p>There are two further ways it may not be available at all. It is
      <a class="src" href="https://community.instructure.com/en/kb/articles/661133-how-do-i-allow-course-content-to-be-exported-as-an-offline-html-file" target="_blank" rel="noopener">an administrator setting</a>,
      so at a great many institutions the button has never existed. And
      Instructure's
      <a class="src" href="https://community.instructure.com/t5/Canvas-Basics-Guide/How-do-I-view-course-content-offline-as-an-ePub-file/ta-p/615317" target="_blank" rel="noopener">ePub guide</a>
      notes that you can have the Download Course Content button and still find
      no ePub available for a particular course, because it is enabled per
      course as well.</p>

      <div class="note warn">
        <p><strong>Check today whether you have the button at all.</strong> Open
        any course you are currently taking, go to Modules, and look for Export
        Course Content. It takes five seconds and it tells you whether your
        backup plan exists. Finding out in your final week is finding out too
        late.</p>
      </div>

      <p>One more limit worth knowing before you rely on it: the ePub is for
      reading offline, and it does not include your submissions. Neither route
      brings down the feedback you were given.</p>

      <h2 id="priority">What to save, in priority order</h2>

      <p>Rank each thing by how hard it would be to replace and how soon its
      door closes. That produces an order most people find backwards, because
      the obvious button is the one at the bottom.</p>

      <ol class="steps">
        <li><strong>Lecture recordings.</strong> First door to close, largest
        files, slowest to download, and the only copy of your lecturer talking
        through the slide that finally made sense. Start these before anything
        else and let them run while you do the rest. See
        <a href="download-panopto-lecture-recordings.html">downloading Panopto
        recordings</a>.</li>
        <li><strong>Quiz questions and your answers.</strong> Frequently
        configured to show you the correct answers exactly once, so these can be
        unrecoverable while your access is still perfectly good.
        <a href="save-canvas-pages-quizzes-discussions.html">How to save
        quizzes, Pages and discussions</a> covers the timing.</li>
        <li><strong>Feedback, rubrics and grader comments.</strong> In no
        export, in no zip, and the thing graduates most often say they wish they
        had. <a href="save-canvas-assignment-feedback.html">Saving your Canvas
        feedback</a>.</li>
        <li><strong>Pages, announcements and discussions.</strong> Export Course
        Content, while it still runs. Check the discussion threads in the
        output, because replies are the usual casualty.</li>
        <li><strong>Your own submitted work.</strong> Account, then Settings,
        then Download Submissions. Lower down only because it hangs off your
        account rather than off any course, so door two does not touch it.</li>
        <li><strong>Files.</strong> Genuinely last. They are the most
        replaceable thing on the list, a classmate probably has them, and they
        are the one category every tool and every guide already handles.
        <a href="what-canvas-download-as-zip-misses.html">Measured across 33
        courses</a>, files were also the smallest gap by a wide margin.</li>
      </ol>

      <h2 id="hour">If you have an hour</h2>

      <p>The order matters more than the tooling here. Start the slow thing
      first.</p>

      <ol class="steps">
        <li>Begin downloading the lecture recordings and leave them
        running.</li>
        <li>While those run: Account, Settings, Download Submissions. One
        button, everything you ever handed in.</li>
        <li>Open each quiz whose results you can still see and print the page to
        PDF. Ctrl and P on Windows, Cmd and P on a Mac, then Save as PDF.</li>
        <li>For each course, Modules, Export Course Content, and download the
        zip when it finishes building.</li>
        <li>Files last. Open the course, click Files, select all, Download as
        Zip.</li>
      </ol>

      <p>Step three is the one people skip and regret. A quiz results page is a
      web page like any other, and a PDF of it survives everything.</p>

      <h2 id="properly">If you have longer</h2>

      <p>An hour gets you the material. A week gets you something you can
      actually find things in two years from now, which is a different
      goal.</p>

      <p>Give each course its own folder and name it the way you will search for
      it later, which usually means the course code rather than the title.
      Canvas names things for Canvas, so a folder full of
      <code>lecture_4_v2_FINAL.pptx</code> is a folder you will not read
      again.</p>

      <p>Convert as you go, or at least before you close the laptop. A
      <code>.pptx</code> is fine while you own PowerPoint and awkward the moment
      you do not, and none of the AI study tools will take one. There is a
      breakdown of what each accepts in
      <a href="canvas-files-into-notebooklm.html">getting Canvas files into
      NotebookLM</a>.</p>

      <p>Then find out what your own deadline actually is, rather than working
      from a number you read on the internet.
      <a href="canvas-access-after-graduation.html">What happens to Canvas
      access after graduation</a> has the published policies from four
      universities and they range from 120 days to five years, which tells you
      only that you have to ask your own.</p>

      <h2 id="verify">How to check the backup is complete</h2>

      <p>Almost nobody does this, and a backup you have not opened is a
      hypothesis. Four checks, none of which take long.</p>

      <ol class="steps">
        <li><strong>Open three files at random.</strong> A zip that downloaded
        is not the same as a zip that opens. Pick one big, one small, one
        old.</li>
        <li><strong>Play a lecture recording to the end.</strong> Skip to the
        last minute rather than the first. A truncated video is the most common
        silent failure there is, and the file size looks entirely reasonable
        until you try.</li>
        <li><strong>Open the offline export and click into a discussion.</strong>
        Replies often stay online-only, so the thread you remember may be a
        heading with nothing under it.</li>
        <li><strong>Sort the folder by size and look at the bottom.</strong>
        Zero-byte files are downloads that failed politely.</li>
      </ol>

      <div class="note good">
        <p><strong>Do this while you still have access.</strong> The entire
        point of verifying is that a gap is fixable, and it stops being fixable
        the moment the door closes. Checking a backup after you have lost the
        original is just finding out.</p>
      </div>

      <h2 id="after">If you have already lost access</h2>

      <p>Less is gone than you probably think, though what remains takes asking
      for.</p>

      <p><strong>Ask the department.</strong> Course coordinators and module
      leaders usually still have the slides and will often just send them.
      This works far more often than people expect, and it costs one polite
      email.</p>

      <p><strong>Ask a classmate.</strong> Somebody on your course kept
      everything. Files are the most replaceable category precisely because they
      were distributed to everyone.</p>

      <p><strong>Ask for your own data.</strong> Your submitted work, your
      grades and the feedback written on them are personal data about you, and
      in the EU and UK you have a right to request it from the university. That
      route reaches your side of the course. It does not reach the lecture
      slides or the recordings, which belong to the institution.</p>

      <p>What is usually gone for good is the lecture recordings, which is the
      argument for the order at the top of this page.</p>

      <div class="cta-box">
        <h3>The whole list, in one run</h3>
        <p>Canvas Downloader was built for exactly this afternoon. Pick the
        courses, and it brings down the files, the Pages, the announcements, the
        quizzes with their questions, the feedback you were given, and the
        Panopto lecture recordings, as video, as audio, or as a searchable
        transcript made on your own machine. It converts as it goes, so what
        lands in the folder still opens in five years without Canvas.</p>
        <p>Free and open source, Windows and macOS. If you only need one
        course's Files tab, Canvas's own Download as Zip is faster.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P11_FAQ = [
    ("How long do I have to download my Canvas courses before I lose access?",
     'Your university decides, and the published range is wide: 120 days at '
     'Stanford, a year at Washington University in St. Louis, five years of '
     'course retention at Penn. The more useful point is that access does not '
     'end all at once. Lecture recordings usually go first, often within days '
     'of grades being released, and a course can be concluded and locked while '
     'you are still enrolled elsewhere in the institution.'),
    ("Can I still download a Canvas course after it has ended?",
     'Partly. A concluded course is read-only, so you can usually still open it '
     'and download files by hand. What you cannot do is use Canvas\'s own '
     'offline export, because Instructure states that offline content cannot be '
     'downloaded once a course is concluded. That is the trap: the built-in '
     'backup tool stops working at the moment most people go looking for it.'),
    ("What should I back up from Canvas first?",
     'Lecture recordings, without much competition. They close first, they are '
     'the largest files, they take longest to download, and no classmate or '
     'lecturer is likely to have a copy to send you. Start them and let them '
     'run while you do everything else. Files should be last, because they are '
     'the easiest thing on the list to get back.'),
    ("Does Canvas delete my courses when I graduate?",
     'Usually your access is removed rather than the course being deleted, and '
     'the two feel identical from where you are standing. Some institutions '
     'also delete content on a schedule of their own. Harvard, for example, '
     'archives Panopto recordings uploaded more than two years ago and deletes '
     'archived recordings older than four years, in a sweep run each January '
     'and June.'),
    ("Will I lose lecture recordings before my Canvas access ends?",
     'Very often, yes. Panopto is a separate system and its access rules are '
     'usually tied to the teaching term rather than to your enrolment. Stanford '
     'tells staff that student access to Panopto course videos typically ends '
     'the Sunday after grades are due, at a university that gives graduating '
     'students 120 days in Canvas. Assume the recordings have the shortest '
     'clock.'),
    ("How do I export a whole Canvas course as a student?",
     'Two built-in routes, if your institution has enabled them. From a '
     'course\'s Modules page, an Export Course Content button produces the '
     'course as browsable offline HTML. From Account then Settings, Download '
     'Course Content generates an ePub plus a zip of associated files. Both '
     'need the course to still be active, both are administrator settings, and '
     'neither includes your submissions or your feedback.'),
    ("Does my Canvas access token still work after I graduate?",
     'No. A token is tied to your account, so it dies when the account does, '
     'and it will usually expire well before that on its own. Generating one '
     'is not a way to keep access after your enrolment ends, and no tool built '
     'on the Canvas API can outlive your login. See '
     '<a href="canvas-access-token-explained.html">what a Canvas access token '
     'is</a> for how the expiry works.'),
    ("Where do I find my university's Canvas URL?",
     'It is the address you already log in at, and it usually looks like '
     '&lt;school&gt;.instructure.com or canvas.&lt;school&gt;.edu. If you are '
     'not sure, there is a '
     '<a href="canvas-url-directory.html">directory of verified Canvas '
     'addresses</a> for several thousand institutions, and Instructure runs '
     'its own school search as the authoritative source.'),
    ("How do I know my Canvas backup actually worked?",
     'Open it. Play a lecture recording from the last minute rather than the '
     'first, because a truncated video looks like a healthy file until you try '
     'it. Click into a discussion in the offline export, since replies are '
     'often left online-only. Then sort the folder by size and look at the '
     'bottom for zero-byte files. Do all of this while you still have access, '
     'because that is what makes a gap fixable.'),
    ("Can I get my Canvas work back after losing access?",
     'Some of it. Course coordinators often still have the slides and will send '
     'them if you ask, and a classmate almost certainly kept the files. Your '
     'own submissions, grades and feedback are personal data about you, so in '
     'the EU and UK you can request them from the university. Lecture '
     'recordings are the category that is usually gone for good.'),
]

P12_BODY = """      <div class="toc">
        <p>On this page</p>
        <ol>
          <li><a href="#claim">The claim nobody has measured</a></li>
          <li><a href="#method">Method and sample</a></li>
          <li><a href="#result1">Result 1: often you cannot use it at all</a></li>
          <li><a href="#result2">Result 2: when it works, it is nearly complete</a></li>
          <li><a href="#result3">Result 3: the files were never the biggest gap</a></li>
          <li><a href="#data">The per-course numbers</a></li>
          <li><a href="#meaning">What to do with this</a></li>
          <li><a href="#repro">Check it yourself</a></li>
          <li><a href="#faq">Common questions</a></li>
        </ol>
      </div>

      <p class="lede">Every help desk warns that Download as Zip can miss files
      attached to modules. In 33 real courses that turned out to be the rare
      failure. The common one is that the button cannot be used at all.</p>

      <h2 id="claim">The claim nobody has measured</h2>

      <p>Search for how to download a Canvas course and you will meet the same
      sentence everywhere, on university IT pages, in forum answers, on the
      sites of tools that compete with mine. Canvas's
      <a class="src" href="https://community.instructure.com/en/kb/articles/662848-how-do-i-download-a-file-or-folder" target="_blank" rel="noopener">official route</a>
      is to select files and download them as a zip, and that zip covers the
      Files tab, and the Files tab can be missing things, because a lecturer can
      attach a file to a module without it appearing there.</p>

      <p>It is repeated as common knowledge and it is never quantified. Nobody
      says how often, or how many files, or whether it is worth acting on.</p>

      <p>Worth noting before any of the numbers: <strong>Instructure does not
      document this anywhere.</strong> Searching their own knowledge base and
      community for it returns the
      <a class="src" href="https://community.instructure.com/en/kb/articles/661313-how-do-i-view-modules-as-a-student" target="_blank" rel="noopener">modules guide</a>,
      the file-download guide above, and
      <a class="src" href="https://community.instructure.com/en/discussion/618390/how-to-download-all-course-files-and-media-on-canvas" target="_blank" rel="noopener">threads of people asking</a>,
      with no statement from the vendor either way. The claim is an oral
      tradition among help desks, which is part of why it has gone so long
      without anybody checking it.</p>

      <p>This project drives a real Canvas account through an audit harness, and
      part of what that harness records is a census of each course: every file
      the Files tab lists, every file a module links to, and the difference.
      Those censuses have been accumulating for a year, so the question is
      answerable. Below is the answer, including the part that undercuts the
      software I build.</p>

      <h2 id="method">Method and sample</h2>

      <p>Method first, because a number without one is decoration.</p>

      <p>For each course the harness asks Canvas directly for the Files tab
      listing and for every module and its items, then compares the two sets of
      file IDs. Nothing is inferred from what got downloaded. The comparison is
      between what Canvas says is in the Files tab and what Canvas says is
      attached to a module.</p>

      <div class="note warn">
        <p><strong>The sample is small and it is not random.</strong> It is 33
        courses, all of them one student's enrolment at a single European
        university, censused through 2026. That is what the numbers describe.
        Anyone quoting them, including me, should say "in 33 courses at one
        university" rather than "in Canvas", because the second one would be
        a claim this data cannot support.</p>
      </div>

      <p>Two things about the sample are worth stating because they change how
      you read every figure below.</p>

      <p><strong>22 of the 33 courses hold no material at all.</strong> They are
      programme shells and unused course sites, and their censuses completed
      normally in two or three seconds. They are excluded from every count about
      files, and reported here so you can see the exclusion rather than take my
      word for the denominator. Eleven courses have files. Everything below is
      about those eleven.</p>

      <p><strong>Nothing was cherry-picked.</strong> Every course the harness has
      ever censused is in the table further down, including the seven where the
      answer is zero and the finding is that nothing is wrong.</p>

      <h2 id="result1">Result 1: often you cannot use it at all</h2>

      <p><strong>Three of the eleven courses would not let a student open the
      Files tab.</strong> Canvas answered the request with a 403 and the message
      <em>"user not authorised to perform that action"</em>.</p>

      <p>Those three courses held <strong>246 files</strong> between them. Two of
      them held 121 and 124, and every one of those was sitting in the course,
      linked from a module, perfectly downloadable one click at a time. The zip
      route to them simply did not exist.</p>

      <p>This is a course setting rather than anything about the account, and
      that is checked rather than assumed: the same login succeeded on 29 of the
      same 33 courses within the same few minutes. The mechanism is ordinary.
      From Course Settings, on the
      <a class="src" href="https://community.instructure.com/en/kb/articles/660741-how-do-i-manage-course-navigation-links" target="_blank" rel="noopener">Navigation tab</a>,
      an instructor can drag Files into the disabled list. Plenty do, usually to
      keep students out of a folder of draft material, and the side effect is
      that the whole tab goes.</p>

      <p>So the standard advice, the one on nearly every university help page,
      is <em>open the course, click Files, select all, Download as Zip</em>. In
      27% of the courses here there is no Files link to click.</p>

      <h2 id="result2">Result 2: when it works, it is nearly complete</h2>

      <p>Now the part that goes against the tool I sell.</p>

      <p>In the eight courses where the Files tab worked, <strong>one</strong>
      had files that a module linked to and the Files tab did not list. That
      course had three such files, out of 143. Across all eight working courses
      the total is <strong>3 files out of 358, or 0.8%</strong>.</p>

      <p>The famous failure is real. It is also small, and it happens in a
      minority of courses. If your Files tab opens, you are getting almost
      everything that is a file, and a guide telling you otherwise is repeating
      folklore rather than reporting a measurement.</p>

      <p>I would rather publish that than not, because the alternative is
      quoting the 0.8% as though it justified installing something.</p>

      <h2 id="result3">Result 3: the files were never the biggest gap</h2>

      <p>Both results above are about files, and files are the part of a course
      that everyone thinks about. Across the same 33 courses the census also
      counted what is not a file:</p>

      <div class="tbl-wrap" tabindex="0" role="region"
        aria-label="Non-file content across 33 courses">
        <table class="cmp">
          <thead>
            <tr><th>Content type</th><th>Items</th><th>In a Files zip?</th></tr>
          </thead>
          <tbody>
            <tr><td>Announcements</td><td>84</td><td class="no">No</td></tr>
            <tr><td>Quizzes</td><td>32</td><td class="no">No</td></tr>
            <tr><td>Discussions</td><td>20</td><td class="no">No</td></tr>
            <tr><td>Assignments</td><td>20</td><td class="no">No</td></tr>
            <tr><td>Pages</td><td>17</td><td class="no">No</td></tr>
          </tbody>
        </table>
      </div>

      <p>That is <strong>173 items</strong>, none of which any zip of any Files
      tab has ever contained. One course alone held 22 quizzes and 16
      announcements. Another held 36 announcements and 15 assignments.</p>

      <p>Set that against the three files in result 2. The gap everyone argues
      about is 3 items. The gap nobody mentions is 173. There is more on what
      those categories are and how to get them in
      <a href="save-canvas-pages-quizzes-discussions.html">saving Canvas Pages,
      quizzes and discussions</a>.</p>

      <p>One smaller finding, since it surprised me. In the largest blocked
      course, 115 of its 124 files were reachable through modules and the
      remaining 9 were embedded in the text of assignments and announcements.
      Files can hide inside content, not only beside it.</p>

      <h2 id="data">The per-course numbers</h2>

      <p>The eleven courses that hold material. Course IDs are internal to one
      Canvas instance and identify nothing on their own. BLOCKED means Canvas
      refused the Files listing.</p>

      <div class="tbl-wrap" tabindex="0" role="region"
        aria-label="Per-course file counts across 11 Canvas courses">
        <table class="cmp">
          <thead>
            <tr>
              <th>Course</th><th>Files tab</th><th>In modules</th>
              <th>Module only</th><th>Total files</th><th>Quizzes</th>
              <th>Announcements</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>43056</td><td class="no">BLOCKED</td><td>0</td><td>0</td><td>1</td><td>0</td><td>4</td></tr>
            <tr><td>43657</td><td>30</td><td>28</td><td>0</td><td>30</td><td>1</td><td>13</td></tr>
            <tr><td>43658</td><td>2</td><td>0</td><td>0</td><td>2</td><td>0</td><td>0</td></tr>
            <tr><td>43660</td><td>140</td><td>97</td><td class="part">3</td><td>143</td><td>22</td><td>16</td></tr>
            <tr><td>43665</td><td class="no">BLOCKED</td><td>121</td><td>121</td><td>121</td><td>0</td><td>2</td></tr>
            <tr><td>44428</td><td>21</td><td>21</td><td>0</td><td>21</td><td>1</td><td>0</td></tr>
            <tr><td>45899</td><td class="no">BLOCKED</td><td>115</td><td>115</td><td>124</td><td>8</td><td>36</td></tr>
            <tr><td>46370</td><td>20</td><td>20</td><td>0</td><td>20</td><td>0</td><td>2</td></tr>
            <tr><td>46386</td><td>95</td><td>94</td><td>0</td><td>95</td><td>0</td><td>1</td></tr>
            <tr><td>46396</td><td>42</td><td>28</td><td>0</td><td>42</td><td>0</td><td>10</td></tr>
            <tr><td>48000</td><td>5</td><td>5</td><td>0</td><td>5</td><td>0</td><td>0</td></tr>
          </tbody>
        </table>
      </div>

      <p>Seven of the eleven are clean. That is the honest shape of it.</p>

      <h2 id="meaning">What to do with this</h2>

      <p>The practical reading is short.</p>

      <ol class="steps">
        <li><strong>Check whether you have a Files tab before you plan around
        it.</strong> Open the course and look at the left-hand navigation. If
        Files is absent, no amount of selecting all will help, and the material
        is still there behind the modules.</li>
        <li><strong>If Files opens, Download as Zip is a good answer for
        files.</strong> Nearly complete, nothing to install, already in front of
        you. The
        <a href="how-to-download-all-canvas-files.html">five built-in
        methods</a> covers the rest of what Canvas can do unaided.</li>
        <li><strong>Plan separately for everything that is not a file.</strong>
        That is where the volume is, and no zip has ever touched it.</li>
      </ol>

      <p>If you are about to lose access to a course, the order to do things in
      matters more than the tooling, and that is in
      <a href="back-up-canvas-course-before-losing-access.html">backing up a
      Canvas course before you lose access</a>.</p>

      <h2 id="repro">Check it yourself</h2>

      <p>The analysis is a script in this project's repository,
      <code>scripts/measure_export_gap.py</code>, and it prints every number on
      this page including the per-course table. It reads the census files the
      audit harness writes and does nothing cleverer than counting.</p>

      <p>If you run a Canvas course and want the same figure for it, the two API
      calls are <code>/api/v1/courses/&lt;id&gt;/files</code> and
      <code>/api/v1/courses/&lt;id&gt;/modules?include[]=items</code>. Compare
      the file IDs. That is the whole method, and I would rather hand it over
      than be the only source for a number.</p>

      <p>If you measure your own institution and get something different, that
      is a useful result and I would like to hear it. A sample of 33 courses at
      one university is a starting point rather than an answer.</p>

      <div class="cta-box">
        <h3>Built because of the 173, not the 3</h3>
        <p>Canvas Downloader reaches the categories no zip contains: Pages,
        announcements, discussions, assignments, and quizzes with their
        questions rather than just their titles. It works in courses where the
        Files tab is switched off, because it reads the modules. It also brings
        down Panopto lecture recordings, which live outside Canvas entirely.</p>
        <p>Free and open source, Windows and macOS. If your Files tab opens and
        files are all you need, use Download as Zip and keep your afternoon.</p>
        <div class="cta-row">
          <a href="releases.html" class="btn-nav">Download</a>
          <a href="index.html#features" class="btn-nav-ghost"><span>See it in action</span></a>
        </div>
      </div>
"""

P12_FAQ = [
    ("Does Canvas Download as Zip include everything in a course?",
     'No, and there are two separate reasons. It only ever covers the Files '
     'tab, so Pages, announcements, discussions, assignments and quizzes are '
     'never in it. And in a course where the instructor has disabled the Files '
     'link in course navigation, the button does not exist at all. In 33 real '
     'courses measured for this article, that was the case in 3 of the 11 '
     'courses that held any material.'),
    ("How many files does Download as Zip actually miss?",
     'In the eight courses measured here where the Files tab worked, 3 files '
     'out of 358, or 0.8%. Only one of those eight courses was affected. The '
     'widely repeated warning that a zip misses files attached to modules is '
     'real, but on this evidence it is small and uncommon. The far bigger gap '
     'is everything that is not a file.'),
    ("Why can I not see the Files tab in my Canvas course?",
     'An instructor has almost certainly disabled it. Course Settings has a '
     'Navigation tab where any item, Files included, can be dragged into a '
     'disabled list, usually to keep students out of draft material. The files '
     'are still in the course and still reachable through whatever modules or '
     'pages link to them. Only the tab is gone.'),
    ("Is this a survey of Canvas?",
     'No, and it should not be quoted as one. It is 33 courses from one '
     'student\'s enrolment at a single European university. It is first-hand '
     'and the method is published, which makes it checkable, but a sample of '
     'that size at one institution describes those courses rather than Canvas '
     'in general. Quote it as "in 33 courses at one university".'),
    ("What does Canvas Download as Zip actually contain?",
     'Whatever is listed in that one course\'s Files tab at the moment you '
     'press it, as a flat zip of the folder structure. It does not span '
     'courses, and it holds no Pages, no announcements, no discussion threads, '
     'no assignment briefs, no quizzes and no feedback, because none of those '
     'is a file. They are rows in Canvas\'s database rendered into web pages.'),
    ("How can I download a course when the Files tab is disabled?",
     'Go through the modules. Everything a module links to is downloadable one '
     'item at a time, which is tedious but works, and it is what any API-based '
     'tool does automatically. In the two blocked courses measured here, 121 '
     'and 115 files respectively were reachable that way with nothing missing.'),
    ("How do I measure this for my own course?",
     'Two Canvas API calls and a set difference: '
     '/api/v1/courses/&lt;id&gt;/files for the Files tab, and '
     '/api/v1/courses/&lt;id&gt;/modules?include[]=items for what the modules '
     'link to. Compare the file IDs. The script used for this article is '
     'scripts/measure_export_gap.py in the project repository.'),
    ("What is the biggest thing missing from a Canvas course download?",
     'On these numbers, the content that is not a file. Across 33 courses the '
     'census counted 84 announcements, 32 quizzes, 20 discussions, 20 '
     'assignments and 17 Pages, a total of 173 items, none of which appears in '
     'any zip of any Files tab. Against that, the file-level gap everybody '
     'writes about was 3 items.'),
]

# ============================================================================

PAGES = [
    dict(
        slug="how-to-download-all-canvas-files.html",
        answer="""        <p>Canvas has no single button for this. It can zip <strong>one
        course's Files tab at a time</strong> - open the course, click Files,
        press Ctrl or Cmd + A, then Download as Zip - and it can export
        <strong>every file you have submitted</strong>, from Account then
        Settings then Download Submissions.</p>
        <p>Neither one includes Pages, assignment briefs, announcements,
        discussions, quizzes or the feedback you were given, and neither covers
        more than one course at a time.
        <a href="what-canvas-download-as-zip-misses.html">Measured across 33 real
        courses</a>, that non-file content came to <strong>173 items</strong>,
        against a file-level gap of <strong>3</strong>. Getting everything from every course
        needs a browser extension, a script, or a desktop app that reads the
        Canvas API with an access token. All five routes are compared below.</p>
""",
        title="How to Download All Files From Canvas (5 Methods Compared)",
        description=("Every way to get your Canvas course files onto your computer, "
                     "compared: Download as Zip, submissions, browser extensions, "
                     "scripts and a desktop app."),
        h1="How to download all your files from Canvas",
        lede=("Canvas has no button that downloads everything. Here is every route "
              "that works, what each one really collects, and which to pick."),
        crumb="How to download all your files from Canvas",
        body=P1_BODY, faq=P1_FAQ, extra_nodes=[],
        published="2026-08-20", modified="2026-08-27",
    ),
    dict(
        slug="canvas-access-after-graduation.html",
        answer="""        <p>It depends entirely on your university, and the published range is
        wide: <strong>120 days</strong> at Stanford, <strong>365 days</strong>
        after the semester at Washington University, <strong>five years</strong>
        of course-site retention at Penn.</p>
        <p>Access also ends in three separate ways - the course is concluded,
        your enrolment ends, or your account is deactivated - and the first can
        happen while you are still a student. Assume you have less time than you
        think, and save your courses before your final term ends rather than
        after it.</p>
""",
        title="Canvas Access After Graduation: What to Save Before It Ends",
        description=("How long you keep Canvas after graduating, the three ways "
                     "access disappears, and a checklist for saving your courses, "
                     "feedback and recordings first."),
        h1="Canvas access after graduation",
        lede=("How long you keep it, the three different ways it disappears, and "
              "what to save first while you still can."),
        crumb="Canvas access after graduation",
        body=P2_BODY, faq=P2_FAQ, extra_nodes=[],
        published="2026-08-20", modified="2026-08-27",
    ),
    dict(
        slug="download-panopto-lecture-recordings.html",
        answer="""        <p>Panopto downloads are <strong>off by default</strong>. Only the
        person who created a recording, and administrators, can download it
        unless a lecturer switches downloading on, which they can do for a whole
        folder or for a single recording.</p>
        <p>If it is on, the download option is in the player's menu. If there is
        no download option, nobody has enabled it, and the right next step is to
        ask your lecturer rather than to look for a way around it. What your
        institution allows varies, and lecture recordings are the material
        universities restrict most often.</p>
""",
        title="How to Download Panopto Lecture Recordings",
        description=("Why Panopto downloads are off by default, how to get them "
                     "enabled, what your university allows, and how to keep a "
                     "lecture as audio or a transcript."),
        h1="How to download Panopto lecture recordings",
        lede=("Downloads are off by default, and the permission question comes "
              "first. How to check, how to ask, and what you can keep."),
        crumb="Download Panopto lecture recordings",
        body=P3_BODY, faq=P3_FAQ, extra_nodes=[],
        published="2026-08-20", modified="2026-08-27",
    ),
    dict(
        slug="save-canvas-assignment-feedback.html",
        answer="""        <p>Canvas has a one-click export of your submissions - Account,
        Settings, Download Submissions, Create Export - and it deliberately
        contains <strong>none of the feedback</strong>: no grades, no comments,
        no rubrics, and not the annotated version of your file. It also expires
        after 30 days.</p>
        <p>So the feedback has to be saved by hand. Annotations come from the
        Download button inside <strong>View Feedback</strong>, one assignment at
        a time; grades, rubrics and comment threads have to be saved from each
        submission's own page. Do it while you can still open the course.</p>
""",
        title="How to Save Your Canvas Assignment Feedback",
        description=("Canvas exports your submissions in one click but not the "
                     "feedback on them. How to save annotations, comments and "
                     "rubrics before access ends."),
        h1="How to save your Canvas assignment feedback",
        lede=("Canvas hands back every file you submitted. It hands back nothing "
              "your instructor wrote, and that is the half you cannot rebuild."),
        crumb="Save your Canvas assignment feedback",
        body=P4_BODY, faq=P4_FAQ, extra_nodes=[],
        published="2026-08-23", modified="2026-08-27",
    ),
    dict(
        slug="canvas-files-into-notebooklm.html",
        answer="""        <p>NotebookLM cannot reach Canvas. There is no integration and no
        login, so every source has to be a <strong>file on your computer
        first</strong>.</p>
        <p>It accepts PDF, <code>.docx</code>, <code>.pptx</code>,
        <code>.txt</code>, <code>.md</code>, CSV, images, audio, web URLs and
        public YouTube links, up to <strong>50 sources</strong> per notebook on
        the free tier. It does <strong>not</strong> accept a local video file,
        which is why lecture recordings have to become audio or a transcript
        before you can upload them. One notebook per course beats one notebook
        per degree, for grounding reasons covered below.</p>
""",
        title="How to Get Your Canvas Files Into NotebookLM",
        description=("What NotebookLM accepts, why it cannot reach Canvas, how to "
                     "choose sources that matter, and what to do with lecture "
                     "recordings."),
        h1="How to get your Canvas files into NotebookLM",
        lede=("NotebookLM cannot see your Canvas courses. Everything has to be a "
              "file on your computer first, and that is the part guides skip."),
        crumb="Canvas files into NotebookLM",
        body=P5_BODY, faq=P5_FAQ, extra_nodes=[],
        published="2026-08-23", modified="2026-08-27",
    ),
    dict(
        slug="download-lecture-videos-from-canvas.html",
        answer="""        <p>Canvas almost never stores the recording. It embeds a player
        belonging to one of <strong>five</strong> other systems: Canvas Studio,
        Panopto, Kaltura (often called My Media or Media Gallery), a plain video
        file in the Files tab, or an external link. Which one you have decides
        everything.</p>
        <p>In both Studio and Panopto, downloading is <strong>off by
        default</strong> and a lecturer switches it on. On Kaltura the download
        button belongs to the player, and the default player does not have one.
        A plain file in the Files tab downloads like any other file. So the first
        step is not a download tool. It is working out which of the five you are
        looking at, then checking the transcript, which is a separate permission
        and is often left open when the video is not.</p>
""",
        title="How to Download Lecture Videos From Canvas (All 5 Systems)",
        description=("Canvas embeds video from five different systems, each with "
                     "its own rules. How to tell which you have, and what works "
                     "for Studio, Panopto, Kaltura."),
        h1="How to download lecture videos from Canvas",
        lede=("Canvas does not store your lecture recordings. Five other systems "
              "do, they behave nothing alike, and telling them apart is the "
              "whole job."),
        crumb="How to download lecture videos from Canvas",
        body=P6_BODY, faq=P6_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
    dict(
        slug="panopto-lecture-transcript.html",
        answer="""        <p>Check Panopto first, because it has probably already made one.
        It machine-transcribes recordings to produce closed captions, and
        institutions are documenting a change to having that <strong>on by
        default</strong> for new content. Open the recording, open the Captions
        or Transcript panel, and look for a download option - what you get is a
        subtitle file, which is plain text with timestamps.</p>
        <p>Captions are usually a <strong>separate permission</strong> from the
        video, so they are often available when downloading is not. If there is
        no transcript - an older recording, the wrong language, or downloads
        switched off - you can make one yourself on your own computer with an
        offline speech-recognition model, with no upload and no account. Expect
        roughly 2 to 24 minutes per hour of lecture depending on the model; the
        measured table is below.</p>
""",
        title="How to Get a Transcript of a Panopto Lecture",
        description=("Panopto has probably already made one, and captions are "
                     "often allowed when downloads are not. How to get it, and "
                     "how to transcribe one yourself."),
        h1="How to get a transcript of a Panopto lecture",
        lede=("The most useful form of a lecture is the one nobody asks for. "
              "Where to find the transcript Panopto already made, and how to "
              "make your own when it has not."),
        crumb="How to get a transcript of a Panopto lecture",
        body=P7_BODY, faq=P7_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
    dict(
        slug="save-canvas-pages-quizzes-discussions.html",
        answer="""        <p>None of it is a file, so no file-based download reaches it. The
        one built-in route is Canvas's <strong>offline content</strong> feature:
        an <strong>Export Course Content</strong> button on the
        <strong>Modules</strong> page that packages the course as browsable
        HTML. Students can use it, but it is an administrator setting that is
        absent at many institutions - and Instructure states that offline
        content <strong>cannot be downloaded once a course is concluded</strong>,
        so it closes at exactly the moment people go looking. <a href="back-up-canvas-course-before-losing-access.html">Backing up a course before you lose access</a> is the procedure that follows from that.</p>
        <p>It also leaves out the two things most worth having: "Discussions and
        quizzes only include the description", and discussion replies must be
        viewed online. The complete <code>.imscc</code> course export needs a
        teacher role. Failing both, the fallback is printing each page to PDF -
        and quizzes first, because their results can be set to show
        <strong>only once</strong>.</p>
""",
        title="How to Save Canvas Quizzes, Pages and Discussions",
        description=("Pages, quizzes, discussions and announcements are not "
                     "files, so no download reaches them. The built-in export, "
                     "its deadline, and what it leaves out."),
        h1="How to save Canvas quizzes, Pages, discussions and announcements",
        lede=("Half a Canvas course is not made of files. There is one built-in "
              "route to the other half, it has a hard deadline, and almost "
              "nobody knows about either."),
        crumb="How to save Canvas quizzes, Pages and discussions",
        body=P8_BODY, faq=P8_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
    dict(
        slug="canvas-access-token-explained.html",
        answer="""        <p>A token is a long string that identifies you to Canvas without a
        password, so software can read Canvas on your behalf. Instructure states
        the scope in one sentence: it "allows the access token holder to access
        the <strong>same Canvas resources that you can access</strong>". Not
        more. It cannot reach courses you are not enrolled on and it is not a
        way to log in as you.</p>
        <p>Make one under <strong>Account</strong>, then
        <strong>Settings</strong>, then <strong>+ New Access Token</strong>.
        Canvas now requires a purpose and an expiry date, and caps how far ahead
        that can be, so a token is something you renew rather than set once.
        Delete it from the same page whenever you want; it stops working
        immediately.</p>
""",
        title="What a Canvas Access Token Is (And What It Cannot Do)",
        description=("What a Canvas access token grants, what it cannot reach, "
                     "why yours now expires, and what to check before pasting "
                     "one into any tool."),
        h1="What a Canvas access token is, and what it cannot do",
        lede=("It grants exactly what you already have, and nothing else. The "
              "useful detail is in what that includes, what it excludes, and "
              "why Canvas keeps shortening its life."),
        crumb="What a Canvas access token is",
        body=P9_BODY, faq=P9_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
    dict(
        slug="canvas-download-tools-compared.html",
        answer="""        <p>Three shapes, and the shape decides most of it. A <strong>browser
        extension</strong> rides your existing Canvas login, so there is no
        access token to generate or renew, and it runs only while you have the
        popup open. A <strong>script</strong> gives total control if you can
        write code and use a terminal. A <strong>desktop app</strong> is
        installed, so it can keep a record between runs, work on a schedule, and
        use software already on your machine.</p>
        <p>For one course today, Canvas's own Download as Zip beats all three.
        An extension covers several courses with no setup and no token. Only a
        desktop app keeps a folder current across a whole semester, converts
        files so AI study tools will take them, and reaches Panopto lecture
        recordings. Written by someone who built one of the options, which is
        disclosed on the page and reflected in the recommendations.</p>
""",
        title="Canvas Download Tools Compared: Extension, Script or App",
        description=("Browser extensions, Python scripts and desktop apps for "
                     "downloading Canvas, compared against each project's own "
                     "documentation, by one of them."),
        h1="Canvas download tools compared: extension, script or app",
        lede=("Three shapes, three trade-offs, and the choice turns on how long "
              "you need it to keep working. Written by someone who built one of "
              "them, which you should know first."),
        crumb="Canvas download tools compared",
        body=P10_BODY, faq=P10_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
    dict(
        slug="back-up-canvas-course-before-losing-access.html",
        answer="""        <p>Do it while the course is still running. Canvas's own offline
        export <strong>refuses to run once a course has been concluded</strong>,
        so the official backup route closes at the moment most people go looking
        for it. And access does not end all at once: lecture recordings usually
        go first, often within days of grades being published, while your Canvas
        login keeps working for months.</p>
        <p>Save in this order, which is not the order most people use. Lecture
        recordings first, because they close soonest and take longest. Then quiz
        questions and the feedback on your work, neither of which appears in any
        export. Then Pages, announcements and discussions, through Modules and
        Export Course Content. Files last, because files are the easiest thing
        to get back. Then open the backup and check it, while a gap is still
        fixable.</p>
""",
        title="How to Back Up a Canvas Course Before You Lose Access",
        description=("Canvas's own export stops working once a course concludes. "
                     "What to save first, in priority order, and how to check "
                     "the backup is complete."),
        h1="How to back up a Canvas course before you lose access",
        lede=("The deadline is not one date. It is three, they belong to "
              "different systems, and the official backup tool switches off at "
              "the second one."),
        crumb="Back up a Canvas course",
        body=P11_BODY, faq=P11_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
    dict(
        slug="what-canvas-download-as-zip-misses.html",
        answer="""        <p>Measured across <strong>33 real Canvas courses</strong> at one
        university, the widely repeated warning turns out to be the rare
        problem. In the eight courses where the Files tab worked, files attached
        to a module but absent from the Files tab came to <strong>3 out of 358,
        or 0.8%</strong>, and only one course was affected at all.</p>
        <p>The common failure is different. In <strong>3 of the 11</strong>
        courses that held any material, Canvas refused the Files listing
        outright with "user not authorised to perform that action", because an
        instructor had disabled the Files link in course navigation. Those
        courses held <strong>246 files</strong>. And across all 33 courses the
        census counted <strong>173 items that are not files at all</strong> -
        announcements, quizzes, discussions, assignments and Pages - none of
        which any zip has ever contained. Method and per-course figures
        below.</p>
""",
        title="What Canvas's Download as Zip Actually Misses (Measured)",
        description=("Measured across 33 real Canvas courses: how many files a "
                     "Files-tab zip misses, how often the tab is switched off "
                     "entirely, and what is never in it."),
        h1="What Canvas's Download as Zip actually misses",
        lede=("Everyone repeats that it can miss files attached to modules. "
              "Nobody has published a number. Here is one, from 33 real "
              "courses, including the part that undercuts my own software."),
        crumb="What Download as Zip misses",
        body=P12_BODY, faq=P12_FAQ, extra_nodes=[],
        published="2026-08-27", modified="2026-08-27",
    ),
]
