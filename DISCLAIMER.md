# Disclaimer & Acceptable Use

Canvas Downloader is a free, open-source tool that saves a local copy of course
material you already have access to. It is provided for lawful, personal use.

**You are responsible for how you use it.** The author is not responsible for
what you download, what you do with it afterwards, or whether your use complies
with your institution's rules, your local copyright law, or any third party's
terms of service.

---

## How the app accesses your content

Canvas Downloader acts as **you**, using **your** credentials:

* It connects to your university's Canvas with an API access token that you
  create and paste in yourself.
* For Panopto recordings it performs the same LTI 1.3 sign-in handshake your
  browser performs when you click a Panopto link inside Canvas, then requests
  the recording from the same endpoint the Panopto player uses.
* Everything runs on your own machine. There is no server, no account, and
  nothing is uploaded anywhere.

It can therefore only reach material that **your own account is already
permitted to open**. If Canvas or Panopto refuses a request, the app reports the
refusal and moves on. It does not attempt to work around it.

## What the app does not do

* It does **not** break, strip, or work around digital rights management,
  encryption, or copy protection. It contains no decryption of any kind.
* It does **not** guess, share, bypass, or escalate credentials or permissions.
* It does **not** reach anything you could not open yourself in a browser.
* It does **not** upload, publish, or share your downloads.

## Panopto lecture recordings

**Please read this section before enabling lecture downloads.**

Panopto's video player has a download button that your institution or your
instructor can switch on or off, per folder or per recording. Many institutions
leave it off site-wide without a deliberate decision ever being made about any
particular lecture.

**Canvas Downloader does not read that setting.** It saves the same video stream
the player already sends to your browser, whether or not the download button is
shown to you.

That means:

* Saving a recording may be contrary to your institution's IT rules or to
  Panopto's terms of service, even though your account is permitted to watch it.
* A lecturer may have deliberately chosen not to make a recording downloadable.
  Please respect that where the choice has clearly been made.
* Recordings are the intellectual property of the lecturer and/or the
  institution. They often contain third-party material that is licensed only for
  use inside a closed teaching context.

**Never republish, upload, share, or redistribute a lecture recording.** Not to
classmates, not to file-sharing services, not to a public AI service, not
anywhere. Redistribution is the act most likely to cause real harm to your
lecturer and real consequences for you, and it is entirely your own act.

If you are unsure whether you may save a particular recording, ask the lecturer
or your institution's IT support. Downloads are for **your own personal study**.

## Why this feature exists

* **Accessibility.** Transcripts and subtitles are generated on-device, for
  students who are deaf or hard of hearing, students with auditory processing
  differences, and students studying in a language that is not their first.
* **Studying offline.** Commutes, travel, and unreliable or metered connections.
* **Revision.** Reviewing your own courses at your own pace, in your own tools.
* **Continuity.** Course material regularly disappears when a term ends or a
  course is unpublished.

## Your responsibilities

By using this software you accept that you are solely responsible for:

* complying with your institution's IT regulations and academic rules;
* complying with any applicable terms of service;
* complying with the copyright law of your country;
* how you store and use what you download, and above all whether you share it.

## No warranty, no liability

This software is provided "as is", without warranty of any kind. See
[LICENSE](LICENSE). To the fullest extent permitted by law, the author accepts no
liability for any claim, damage, loss, disciplinary action, or other consequence
arising from your use of this software.

**Nothing in this document is legal advice.**

## For institutions, rights holders, and Panopto

If you represent an institution, a rights holder, or Panopto and you have a
concern about this project, please
[open an issue](https://github.com/BrkBuilds/Canvas-Downloader/issues)
or email **brkbuilds1@gmail.com** before taking any other step. Concerns raised
in good faith will be addressed in good faith, and promptly.
