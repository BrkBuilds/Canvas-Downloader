"""
Translation module for Canvas Downloader
Supports English (en) and Danish (da)
"""

TRANSLATIONS = {
    'en': {
        # Page title
        'app_title': 'Canvas LMS Course Material Downloader',
        'sidebar_title': '🎓 Canvas Tool',
        
        # Authentication
        'auth_header': 'Authentication',
        'enter_token': 'Enter Canvas API Token',
        'enter_url': 'Enter Canvas URL',
        'canvas_url': 'Canvas URL',
        'validate_save': 'Log In',
        'login_failed': 'Login failed. Please check that your Canvas URL and API Token are correct.',
        'logged_in_as': 'Logged in as: {name}',
        'invalid_token': 'Invalid Token: {error}',
        'connection_error': 'Connection Error: {error}',
        'logout_edit': 'Log Out / Edit Token',
        'how_to_token': 'How to get a Token?',
        'token_instructions': """
1. Go to **Account** -> **Settings** on Canvas.
2. Scroll to **Approved Integrations**.
3. Click **+ New Access Token**.
4. Copy the long string and paste it here.
""",
        'how_to_url': 'How to find your Canvas URL?',
        'url_instructions': """
**Crucial Step:** You must input the *actual* Canvas URL, not your university's login portal.

**How to find it:**
1. Log in to Canvas in your browser.
2. Look at the address bar **after** you have logged in.
3. It often looks like `https://schoolname.instructure.com` (even if you typed `canvas.school.edu` to get there).
4. Copy that URL and paste it here.
""",
        
        # Filters
        'enable_cbs_filters': 'Enable CBS Filters',
        'filter_criteria': 'Filter Criteria',
        'filter_type': 'Class Type',
        'filter_semester': 'Semester',
        'filter_year': 'Year',
        'no_courses_match_filters': 'No courses match the selected filters.',
        
        # Filter Options
        'type_lecture': 'Lecture',
        'type_exercise': 'Exercise',
        'type_other': 'Other',
        'sem_autumn': 'Autumn',
        'sem_spring': 'Spring',

        # Step 1: Select Courses
        'step1_header': 'Step 1: Select Courses',
        'show_favorites': 'Favorites Only',
        'show_all': 'All Courses',
        'show_label': 'Show:',
        'select_all': 'Select All',
        'clear_selection': 'Clear Selection',
        'no_courses': 'No courses found.',
        'continue_btn': 'Continue',
        'select_one_course': 'Please select at least one course.',
        
        # Step 2: Download Settings
        'step2_header': 'Step 2: Download Settings',
        'download_structure': 'Download Structure',
        'structure_question': 'Choose how files should be organized:',
        'with_subfolders': 'With subfolders (Matches Canvas Modules)',
        'mode_files': 'Files (Course Folders)',
        'flat_structure': 'Full (All files in one folder)',
        'destination': 'Destination',
        'select_folder': '📂 Select Folder',
        'path_label': 'Path',
        'back_btn': 'Back',
        'cancel': 'Cancel',
        'confirm_download': 'Confirm and Download',
        
        # Step 3: Progress
        'step3_header': 'Step 3: Downloading...',
        'cancel_download': 'Cancel Download',
        'download_cancelled': 'Download Cancelled!',
        'processing': 'Processing ({current}/{total}): {course}',
        'all_complete': 'All downloads complete!',
        'download_complete': 'Download Completed Successfully!',
        'downloaded_courses': 'Downloaded {total} course(s).',
        'download_location': 'You can find the downloaded files here: {path}',
        'download_was_cancelled': 'Download was cancelled.',
        'cancelled_after': 'Cancelled after {current} of {total} course(s).',
        'start_over': 'Start Over',

        'go_back': 'Go back',
        'go_to_front_page': 'Go to front page',
        'download_state_error': 'Download state not initialized. Please go back and try again.',

        'go_back_settings': 'Go Back to Settings',
        'fetching_folders': 'Fetching folder structure...',
        'fetching_files_list': 'Fetching file list...',
        'scanning_files': 'Scanning files... ({current}/{total} courses)',
        'downloading_progress_text': 'Downloading: File {current} out of {total}',
        'mb_progress_text': 'Downloading: {current:.1f} / {total:.1f} MB',
        'complete_text': 'Complete!',
        
        # Messages
        'please_authenticate': '👈 Please authenticate in the sidebar to continue.',
        
        # Backend / Logic Messages
        'insufficient_space': 'Insufficient disk space. Need at least 1GB free.',
        'download_cancelled_msg': 'Download cancelled.',
        'downloading_file': 'Downloading file: {filename}',
        'skipping_no_url': 'Skipping {filename}: No download URL available (Canvas may have restricted access or file is unavailable)',
        'download_failed_http': 'Failed to download {filename}: HTTP {status}',
        'download_failed_exc': 'Failed to download {filename}: {error_type}: {error}',
        'saving_page': 'Saving page: {title}',
        'save_page_failed': 'Failed to save page {title}: {error}',
        'creating_link': 'Creating link: {title}',
        'create_link_failed': 'Failed to create link {title}: {error}',
        'missing_content_id': 'Item {title} missing content_id',
        'missing_page_url': 'Item {title} missing page_url',
        'missing_external_url': 'Item {title} missing external_url',
        'error_processing_item': 'Error processing item {title} in module {module}: {error}',
        'error_processing_module': 'Error processing module {name}: {error}',
        'modules_unauthorized': 'Could not access Modules tab for this course (Unauthorized). The teacher may have hidden it.',
        'error_module_list': 'Error retrieving module list: {error}',
        'task_failed': 'Download task {i} failed: {error}',
        'error_processing_course': 'Error processing course {course}: {error}',
        'course_unauthorized': 'Access Denied: The application cannot access this course\'s content. It may be restricted or unpublished.',
        'rate_limit_error': 'Canvas API Rate Limit: The application is making too many requests. (Canvas API might limit downloads if too many requests are sent. Try again in a moment, or try downloading this course individually)',
        'modules_unauthorized_fallback': 'Modules tab is hidden/unauthorized. Attempting to download files directly...',
        
        # Filter
        'file_filter_label': 'File Types',
        'filter_all': 'All Files',
        'filter_study': 'Pdf & Powerpoint only',

        # Launcher
        'launcher_starting': 'Starting application...',
        'launcher_server_start': 'Launching server on...',
        'launcher_running': 'Application running, visit {url}',
        'launcher_close_instruction': 'Close this window to close this application',
        
        # Error Summary
        'errors_occurred': '⚠️ {count} error(s) occurred during download',
        'view_error_details': '📋 View Error Details',
        'no_url_header': '**🔒 Files Without Download URLs:**',
        'http_error_header': '**🌐 HTTP Errors:**',
        'other_error_header': '**⚠️ Other Errors:**',
        'no_url_explanation': """**Why this happens:**
1. Teacher restricted access (teacher-only or draft files)
2. Files deleted from Canvas but still listed in modules
3. Files hosted externally (OneDrive/Google Drive)
4. Canvas API issue or temporary glitch

💡 **Solution:** Try downloading these files manually from the Canvas website.""",
        'http_error_explanation': """**Why this happens:**
1. Network connection issues
2. Canvas server temporarily unavailable
3. File permissions changed during download

💡 **Solution:** Try downloading again or check your internet connection.""",
        'full_error_details': '📄 Full error details are saved in `download_errors.txt` in each course folder.',
        
        # Language
        'language': 'Language',
        'english': 'English',
        'danish': 'Dansk',
        
        # Sync Mode
        'sync_mode_label': 'Sync Mode',
        'enable_sync_mode': 'Enable Smart Sync',
        'sync_mode_help': 'Sync with an existing local folder instead of fresh download',
        'sync_mode_description': 'Smart Sync will analyze your local folder and only download new or updated files. Your existing files and notes will not be overwritten.',
        'analyzing_folder': 'Analyzing local folder...',
        'healing_manifest': 'Looking for moved/renamed files...',
        'fetching_canvas_files': 'Fetching file list from Canvas...',
        
        # Navigation
        'nav_download': 'Download Courses',
        'nav_sync': 'Sync Local Folders',
        'nav_section': 'Navigation',
        
        # Sync Folder Pairing
        'sync_step1_header': 'Select Folders to Sync',
        'sync_tutorial_title': '📖 How Smart Sync Works',
        'sync_tutorial_text': '''**Smart Sync keeps your local folders up-to-date without overwriting your work.**

1. **Add a Folder**: Select an existing course folder on your computer and pair it with the corresponding Canvas course.
2. **Analyze**: We compare your local files with Canvas.
3. **Review**: You'll see exactly what changed:
   - 🆕 **New Files**: Downloaded to your folder.
   - 🔄 **Updated Files**: Saved as a copy (e.g., `file_NewVersion.pdf`) so your notes aren't overwritten.
   - 📦 **Missing Files**: Re-download files you accidentally deleted, or ignore them forever.
   - 🗑️ **Deleted on Canvas**: Files removed by the teacher are preserved safely on your computer.

*Tip: Use **⚡ Quick Sync All** to skip the review and instantly download all new and updated files across all your courses!*''',
        'sync_add_folder': 'Add Folder to Sync',
        'sync_add_course_folder': 'Add Course folder to Sync',
        'sync_courses_to_sync': 'Canvas Courses to Sync',
        'sync_select_course': 'Select Canvas Course',
        'sync_no_pairs': 'No folders added yet. Click "Add Course folder" to get started.',
        'sync_mismatch_warning': '⚠️ Warning: The folder name doesn\'t seem to match the selected course. Are you sure this is the correct folder for this course?',
        'sync_remove_pair': 'Remove',
        'sync_open_folder_action': 'Open Folder',
        'sync_folder_label': 'Folder',
        'sync_change_folder': 'Change Folder',
        'sync_course_label': 'Select corresponding Canvas course',
        'sync_start_analysis': 'Analyze, Review & Sync',
        'sync_confirm_add': 'Confirm and Add',
        'sync_edit_pair': 'Edit',
        'sync_analyzing_course': 'Analyzing: {course}',
        'sync_error_no_course': 'Please select a course.',
        
        # Step 4: Sync Analysis
        'step4_header': 'Review Changes',
        'analysis_summary': 'Found {new} new {file_word}, {updates} {update_word} available, {missing} missing {file_word2}',
        'new_files': 'New Files',
        'new_files_desc': '📥 These files exist on Canvas but are **not yet downloaded** to your local folder. Select them to download.',
        'updated_files': 'Updates Available',
        'updated_files_desc': '🔄 These files have been **modified on Canvas** since you last synced. Selecting them will download the new version as a separate file (with "_NewVersion" suffix) so your existing copy is preserved.',
        'missing_files': 'Missing Files',
        'missing_files_desc': '🔍 These files were previously synced but **can no longer be found** in your local folder (deleted or moved). Select to re-download, or choose "Ignore" to stop being notified.',
        'uptodate_files': 'Up-to-date Files',
        'uptodate_files_desc': 'Files that match the Canvas version',
        'ignored_files': 'Ignored Files',
        'ignored_files_desc': 'Files you chose to ignore in previous syncs',
        'no_files_category': 'No files in this category',
        
        # Sync Actions
        'sync_selected': 'Sync (Download) Selected Files',
        'deselect_all': 'Clear Selection',
        'ignore_forever': 'Ignore this file forever',
        'ignore_selected': 'Ignore Selected',
        'sync_complete': 'Sync completed successfully!',
        'sync_complete_with_errors': 'Sync completed with some errors.',
        'sync_all_failed': 'Sync failed for all files.',
        'synced_files_count': 'Synced {count} {file_word}',
        'sync_folders_updated': 'Folders Updated',
        'nothing_to_sync': 'Nothing to sync - all files are up to date!',
        'file_size': '{size}',
        'new_version_suffix': '_NewVersion',

        # Sync Progress
        'sync_progress_header': 'Syncing...',
        'sync_progress_course': 'Syncing ({current}/{total}): {course}',
        'sync_progress_text': 'Syncing: File {current} of {total}',
        'sync_mb_progress': 'Syncing: {current:.1f} / {total:.1f} MB',
        'sync_cancel': 'Cancel Sync',
        'sync_cancelled': 'Sync was cancelled.',
        'sync_cancelled_after': 'Cancelled after {current} of {total} {file_word}.',
        'sync_downloading_file': 'Downloading: {filename}',
        'sync_complete_text': 'Complete!',
        'sync_errors_occurred': '⚠️ {count} {error_word} occurred during sync',
        'sync_error_file': 'Failed: {filename} — {error}',
        'view_error_details': 'View Error Details',
        'sync_completed_with_errors_title': 'Completed with errors',
        'sync_partial_title': 'Partial Sync: {count} {file_word} downloaded, {error_count} failed',
        'sync_partial_desc': '{size} downloaded. Please check the errors below.',

        # Sync — Descriptive Step Labels
        'sync_step_select_folders': '📁 Select Folders',
        'sync_step_review': '🔍 Review Changes',
        'sync_step_syncing': '⬇️ Syncing',

        # Sync — New Features
        'sync_adding_folder': 'Added Folder:',
        'sync_select_all': 'Select All',
        'sync_deselect_all': 'Deselect All',
        'sync_insufficient_space': 'Insufficient disk space on the target drive. Need at least 1 GB free to proceed safely.',
        'sync_confirm_title': 'Confirm Sync',
        'sync_confirm_summary': 'About to download {count} {file_word} ({size}). Continue?',
        'sync_confirm_yes': 'Yes, Start Sync',
        'sync_confirm_no': 'Go Back',
        'sync_last_synced': 'Last synced: {time}',
        'sync_never_synced': 'Never synced',
        'sync_quick_sync': '⚡Quick Sync All',
        'sync_quick_sync_help': 'Skip review and download all new & updated files immediately',
        'sync_open_folder': '📂 Open Folder',
        'sync_history_title': '📜 Sync History',
        'sync_history_empty': 'No sync history yet.',
        'sync_history_entry': '{time} — {count} {file_word} synced across {courses} {course_word}',
        'sync_replace_original': 'Replace original with latest version',
        'sync_replaced_success': 'Replaced original: {filename}',
        'sync_files_uptodate_count': '✅ {count} {file_word} already up-to-date',
        'sync_file_removed_from_canvas': 'File "{filename}" is no longer available on Canvas (may have been deleted by the teacher).',
        'sync_duplicate_pair': '⚠️ This folder is already paired with this course.',
        'sync_folder_not_found': '❌ Folder not found: {path}. It may have been deleted, renamed, or the drive is disconnected.',
        'sync_analyzing_spinner': 'Analyzing courses...',
        'sync_analysis_rate_limit': 'Waiting briefly to avoid API rate limits...',
        'sync_files_total_size': '{count} {file_word} — {size} total',

        # Sync — Step Wizard & New UI
        'sync_step_select_folders': '📁 Select',
        'sync_step_review': '🔍 Review',
        'sync_step_syncing': '⬇️ Sync',
        'sync_step_complete': '✅ Complete',
        'sync_search_courses': 'Search courses...',
        'sync_confirm_title': 'Confirm Sync',
        'sync_confirm_proceed': 'You are about to download {count} {file_word} ({size}) to {folders} {folder_word}. Continue?',
        'sync_confirm_yes': 'Yes, start sync',
        'sync_confirm_no': 'No, go back',
        'sync_per_course_btn': 'Sync This',
        'sync_quick_sync': 'Quick Sync All',
        'sync_quick_sync_desc': 'Re-sync all paired folders without review',
        'sync_analyzing_progress': 'Analyzing course {current} of {total}...',
        'sync_summary_card': 'Downloaded {new_count} new and {upd_count} updated {file_word} ({size})',
        'sync_no_changes_course': 'All files up-to-date',
        'sync_history_title': '📜 Sync History',
        'sync_history_entry': '{time} — {count} {file_word} synced from {courses} {course_word}',
        'sync_progress_text': '{current} / {total} files',
        'sync_complete_text': 'Complete!',
        'sync_complete_bar': 'Sync Complete',
        'sync_success_title': 'Sync Success! Synced {count} {file_word}',
        'sync_open_folder_btn': '📂 Open folder',
        'sync_see_synced_files': 'See {count} synced files',
        'sync_additional_settings': '⚙️ Additional Sync Settings',
        'sync_organize_toggle': '📂 Organize files into Canvas module folders',
        'sync_organize_help': 'Move existing files into subfolders matching the Canvas course module structure. Files are moved, never deleted. Your modifications (e.g. filled-out assignments) are preserved.',
        'sync_organizing_progress': 'Organizing files into module folders for {course}...',
        'sync_organized_count': '📂 Organized {count} {file_word} into module folders',
        'sync_course_prefix': 'Course: ',
        'sync_change_course': 'Change Course',
        'sync_select_course_btn': 'Select Course',

    },
    'da': {
        # Page title
        'app_title': 'Canvas LMS Kursusmateriale Downloader',
        'sidebar_title': '🎓 Canvas Værktøj',
        
        # Authentication
        'auth_header': 'Godkendelse',
        'enter_token': 'Indtast Canvas API Token',
        'enter_url': 'Indtast Canvas URL',
        'canvas_url': 'Canvas URL',
        'validate_save': 'Log Ind',
        'login_failed': 'Login fejlede. Tjek venligst at din Canvas URL og API Token er korrekte.',
        'logged_in_as': 'Logget ind som: {name}',
        'invalid_token': 'Ugyldig Token: {error}',
        'connection_error': 'Forbindelsesfejl: {error}',
        'logout_edit': 'Log Ud / Redigér Token',
        'how_to_token': 'Hvordan får man en Token?',
        'token_instructions': """
1. Gå til **Konto** -> **Indstillinger** på Canvas.
2. Rul ned til **Godkendte Integrationer**.
3. Klik **+ Ny Adgangstoken**.
4. Kopiér den lange streng og indsæt den her.
""",
        'how_to_url': 'Hvordan finder man Canvas URL?',
        'url_instructions': """
**Vigtigt:** Du skal indtaste den *faktiske* Canvas URL, ikke din skoles login-portal.

**Sådan finder du den:**
1. Log ind på Canvas i din browser.
2. Kig på adresselinjen **efter** du er logget ind.
3. Den ser ofte sådan ud: `https://skolenavn.instructure.com` (selvom du skrev `canvas.skole.dk` for at komme dertil).
4. Kopiér den URL og indsæt den her.
""",
        
        # Filters
        'enable_cbs_filters': 'Aktiver CBS Filtre',
        'filter_criteria': 'Filterkriterier',
        'filter_type': 'Undervisningstype',
        'filter_semester': 'Semester',
        'filter_year': 'År',
        'no_courses_match_filters': 'Ingen kurser matcher de valgte filtre.',
        
        # Filter Options
        'type_lecture': 'Forelæsning',
        'type_exercise': 'Øvelse',
        'type_other': 'Andet',
        'sem_autumn': 'Efterår',
        'sem_spring': 'Forår',

        # Step 1: Select Courses
        'step1_header': 'Trin 1: Vælg Kurser',
        'show_favorites': 'Kun Favoritter',
        'show_all': 'Alle Kurser',
        'show_label': 'Vis:',
        'select_all': 'Vælg Alle',
        'clear_selection': 'Ryd Valg',
        'no_courses': 'Ingen kurser fundet.',
        'continue_btn': 'Fortsæt',
        'select_one_course': 'Vælg venligst mindst ét kursus.',
        
        # Step 2: Download Settings
        'step2_header': 'Trin 2: Download Indstillinger',
        'download_structure': 'Download Struktur',
        'structure_question': 'Vælg hvordan filer skal organiseres:',
        'with_subfolders': 'Med undermapper (Matcher Canvas Moduler)',
        'mode_files': 'Filer (Kursusmapper)',
        'flat_structure': 'Flad (Alle filer i én mappe)',
        'destination': 'Destination',
        'select_folder': '📂 Vælg Mappe',
        'path_label': 'Sti',
        'back_btn': 'Tilbage',
        'cancel': 'Annuller',
        'confirm_download': 'Bekræft og Download',
        
        # Step 3: Progress
        'step3_header': 'Trin 3: Downloader...',
        'cancel_download': 'Annullér Download',
        'download_cancelled': 'Download Annulleret!',
        'processing': 'Behandler ({current}/{total}): {course}',
        'all_complete': 'Alle downloads fuldført!',
        'download_complete': 'Download Fuldført Med Succes!',
        'downloaded_courses': 'Downloadet {total} kursus(er).',
        'download_location': 'Du kan finde de downloadede filer her: {path}',
        'download_was_cancelled': 'Download blev annulleret.',
        'cancelled_after': 'Annulleret efter {current} af {total} kursus(er).',
        'start_over': 'Start Forfra',

        'go_back': 'Gå tilbage',
        'go_to_front_page': 'Gå til forsiden',
        'download_state_error': 'Download-tilstand ikke initialiseret. Gå venligst tilbage og prøv igen.',

        'go_back_settings': 'Gå Tilbage til Indstillinger',
        'fetching_folders': 'Henter mappestruktur...',
        'fetching_files_list': 'Henter filliste...',
        'scanning_files': 'Scanner filer... ({current}/{total} kurser)',
        'downloading_progress_text': 'Downloader: Fil {current} af {total}',
        'mb_progress_text': 'Downloader: {current:.1f} / {total:.1f} MB',
        'complete_text': 'Færdig!',
        
        # Messages
        'please_authenticate': '👈 Godkend venligst i sidebaren for at fortsætte.',
        
        # Backend / Logic Messages
        'insufficient_space': 'Utilstrækkelig diskplads. Der kræves mindst 1GB ledig plads.',
        'download_cancelled_msg': 'Download annulleret.',
        'downloading_file': 'Downloader fil: {filename}',
        'skipping_no_url': 'Springer {filename} over: Ingen download-URL tilgængelig (Canvas kan have begrænset adgang eller filen er utilgængelig)',
        'download_failed_http': 'Kunne ikke downloade {filename}: HTTP {status}',
        'download_failed_exc': 'Kunne ikke downloade {filename}: {error_type}: {error}',
        'saving_page': 'Gemmer side: {title}',
        'save_page_failed': 'Kunne ikke gemme side {title}: {error}',
        'creating_link': 'Opretter link: {title}',
        'create_link_failed': 'Kunne ikke oprette link {title}: {error}',
        'missing_content_id': 'Element {title} mangler content_id',
        'missing_page_url': 'Element {title} mangler page_url',
        'missing_external_url': 'Element {title} mangler external_url',
        'error_processing_item': 'Fejl ved behandling af element {title} i modul {module}: {error}',
        'error_processing_module': 'Fejl ved behandling af modul {name}: {error}',
        'modules_unauthorized': 'Kunne ikke få adgang til Moduler for dette kursus (Uautoriseret). Læreren kan have skjult det.',
        'error_module_list': 'Fejl ved hentning af modul-liste: {error}',
        'task_failed': 'Download-opgave {i} fejlede: {error}',
        'error_processing_course': 'Fejl ved behandling af kursus {course}: {error}',
        'course_unauthorized': 'Adgang Nægtet: Applikationen kan ikke tilgå dette kursus indhold. Det kan være begrænset eller ikke udgivet.',
        'rate_limit_error': 'Canvas API Hastighedsbegrænsning: Applikationen laver for mange forespørgsler. (Canvas API kan begrænse mængden af downloads hvis der bliver sendt for mange forespørgsler. Prøv igen om lidt tid, eller prøv at downloade kurset for sig selv)',
        'modules_unauthorized_fallback': 'Modul-fanen er skjult/uautoriseret. Forsøger at downloade filer direkte...',
        
        # Filter
        'file_filter_label': 'Filtyper',
        'filter_all': 'Alle Filer',
        'filter_study': 'Kun Pdf & Powerpoint',

        # Launcher
        'launcher_starting': 'Starter applikation...',
        'launcher_server_start': 'Starter server på...',
        'launcher_running': 'Applikation kører, besøg {url}',
        'launcher_close_instruction': 'Luk dette vindue for at lukke applikationen',
        
        # Error Summary
        'errors_occurred': '⚠️ {count} fejl opstod under download',
        'view_error_details': '📋 Se Fejldetaljer',
        'no_url_header': '**🔒 Filer Uden Download-URL:**',
        'http_error_header': '**🌐 HTTP Fejl:**',
        'other_error_header': '**⚠️ Andre Fejl:**',
        'no_url_explanation': """**Hvorfor sker dette:**
1. Læreren har begrænset adgang (lærer-kun eller kladde-filer)
2. Filer slettet fra Canvas men stadig vist i moduler
3. Filer hostet eksternt (OneDrive/Google Drive)
4. Canvas API fejl eller midlertidig fejl

💡 **Løsning:** Prøv at downloade disse filer manuelt fra Canvas hjemmesiden.""",
        'http_error_explanation': """**Hvorfor sker dette:**
1. Netværksforbindelsesproblemer
2. Canvas server midlertidigt utilgængelig
3. Filrettigheder ændret under download

💡 **Løsning:** Prøv at downloade igen eller tjek din internetforbindelse.""",
        'full_error_details': '📄 Fulde fejldetaljer er gemt i `download_errors.txt` i hver kursusmappe.',
        
        # Language
        'language': 'Sprog',
        'english': 'English',
        'danish': 'Dansk',
        
        # Sync Mode
        'sync_mode_label': 'Synkroniseringstilstand',
        'enable_sync_mode': 'Aktivér Smart Synkronisering',
        'sync_mode_help': 'Synkroniser med en eksisterende lokal mappe i stedet for ny download',
        'sync_mode_description': 'Smart Synkronisering analyserer din lokale mappe og downloader kun nye eller opdaterede filer. Dine eksisterende filer og noter bliver ikke overskrevet.',
        'analyzing_folder': 'Analyserer lokal mappe...',
        'healing_manifest': 'Leder efter flyttede/omdøbte filer...',
        'fetching_canvas_files': 'Henter filliste fra Canvas...',
        
        # Navigation
        'nav_download': 'Download Kurser',
        'nav_sync': 'Synkroniser Lokale Mapper',
        'nav_section': 'Navigation',
        
        # Sync Folder Pairing
        'sync_step1_header': 'Vælg Mapper at Synkronisere',
        'sync_tutorial_title': '📖 Sådan Fungerer Smart Sync',
        'sync_tutorial_text': '''**Smart Sync holder dine lokale mapper opdaterede uden at overskrive dit arbejde.**

1. **Tilføj en Mappe**: Vælg en eksisterende kursusmappe på din computer og par den med det tilsvarende Canvas-kursus.
2. **Analysér**: Vi sammenligner dine lokale filer med Canvas.
3. **Gennemgå**: Du vil se præcis, hvad der er ændret:
   - 🆕 **Nye Filer**: Downloades til din mappe.
   - 🔄 **Opdaterede Filer**: Gemmes som en kopi (f.eks. `fil_NewVersion.pdf`), så dine noter ikke overskrives.
   - 📦 **Manglende Filer**: Gen-download filer du ved et uheld har slettet, eller ignorer dem fremover.
   - 🗑️ **Slettet på Canvas**: Filer fjernet af læreren bevares sikkert på din computer.

*Tip: Brug **⚡ Hurtig Synk Alle** for at springe gennemgangen over og øjeblikkeligt downloade alle nye og opdaterede filer på tværs af alle dine kurser!*''',
        'sync_add_folder': 'Tilføj Mappe til Synkronisering',
        'sync_add_course_folder': 'Tilføj Kursusmappe til Synkronisering',
        'sync_courses_to_sync': 'Canvas Kurser at Synkronisere',
        'sync_select_course': 'Vælg Canvas Kursus',
        'sync_no_pairs': 'Ingen mapper tilføjet endnu. Klik "Tilføj Kursusmappe" for at komme i gang.',
        'sync_mismatch_warning': '⚠️ Advarsel: Mappenavnet ser ikke ud til at matche det valgte kursus. Er du sikker på, at dette er den korrekte mappe til dette kursus?',
        'sync_remove_pair': 'Fjern',
        'sync_open_folder_action': 'Åbn Mappe',
        'sync_folder_label': 'Mappe',
        'sync_course_label': 'Vælg det tilhørende Canvas kursus',
        'sync_start_analysis': 'Analysér, Gennemgå & Synk',
        'sync_confirm_add': 'Bekræft og Tilføj',
        'sync_edit_pair': 'Rediger',
        'sync_analyzing_course': 'Analyserer: {course}',
        
        # Step 4: Sync Analysis
        'step4_header': 'Gennemse Ændringer',
        'analysis_summary': 'Fandt {new} ny {file_word}, {updates} {update_word} tilgængelig, {missing} manglende {file_word2}',
        'new_files': 'Nye Filer',
        'new_files_desc': '📥 Disse filer findes på Canvas, men er **endnu ikke downloadet** til din lokale mappe. Vælg dem for at downloade.',
        'updated_files': 'Opdateringer Tilgængelige',
        'updated_files_desc': '🔄 Disse filer er blevet **ændret på Canvas** siden din sidste synkronisering. Hvis du vælger dem, downloades den nye version som en separat fil (med "_NewVersion" suffiks), så din eksisterende kopi bevares.',
        'missing_files': 'Manglende Filer',
        'missing_files_desc': '🔍 Disse filer blev tidligere synkroniseret, men **kan ikke længere findes** i din lokale mappe (slettet eller flyttet). Vælg for at gen-downloade, eller vælg "Ignorer" for at stoppe påmindelser.',
        'uptodate_files': 'Opdaterede Filer',
        'uptodate_files_desc': 'Filer der matcher Canvas-versionen',
        'ignored_files': 'Ignorerede Filer',
        'ignored_files_desc': 'Filer du valgte at ignorere i tidligere synkroniseringer',
        'no_files_category': 'Ingen filer i denne kategori',
        
        # Sync Actions
        'sync_selected': 'Synkroniser (Download) Valgte Filer',
        'deselect_all': 'Fravælg Alle',
        'ignore_forever': 'Ignorer denne fil fremover',
        'ignore_selected': 'Ignorer Valgte',
        'sync_complete': 'Synkronisering fuldført!',
        'sync_complete_with_errors': 'Synkronisering gennemført med fejl.',
        'sync_all_failed': 'Synkronisering mislykkedes for alle filer.',
        'synced_files_count': 'Synkroniserede {count} {file_word}',
        'sync_folders_updated': 'Opdaterede Mapper',
        'nothing_to_sync': 'Intet at synkronisere - alle filer er opdaterede!',
        'file_size': '{size}',
        'new_version_suffix': '_NewVersion',

        # Sync Progress
        'sync_progress_header': 'Synkroniserer...',
        'sync_progress_course': 'Synkroniserer ({current}/{total}): {course}',
        'sync_progress_text': 'Synkroniserer: Fil {current} af {total}',
        'sync_mb_progress': 'Synkroniserer: {current:.1f} / {total:.1f} MB',
        'sync_cancel': 'Annullér Synkronisering',
        'sync_cancelled': 'Synkronisering blev annulleret.',
        'sync_cancelled_after': 'Annulleret efter {current} af {total} {file_word}.',
        'sync_downloading_file': 'Downloader: {filename}',
        'sync_complete_text': 'Færdig!',
        'sync_errors_occurred': '⚠️ {count} {error_word} opstod under synkronisering',
        'sync_error_file': 'Fejl: {filename} — {error}',
        'view_error_details': 'Se Fejldetaljer',
        'sync_completed_with_errors_title': 'Fuldført med fejl',
        'sync_partial_title': 'Delvis Synk: {count} {file_word} hentet, {error_count} fejlede',
        'sync_partial_desc': '{size} hentet. Tjek venligst fejlene herunder.',

        # Sync — Descriptive Step Labels
        'sync_step_select_folders': '📁 Vælg Mapper',
        'sync_step_review': '🔍 Gennemse Ændringer',
        'sync_step_syncing': '⬇️ Synkroniserer',

        # Sync — New Features
        'sync_adding_folder': 'Tilføjet Mappe:',
        'sync_select_all': 'Vælg Alle',
        'sync_deselect_all': 'Fravælg Alle',
        'sync_insufficient_space': 'Utilstrækkelig diskplads på destinationsdrevet. Der kræves mindst 1 GB ledig plads for at fortsætte sikkert.',
        'sync_confirm_title': 'Bekræft Synkronisering',
        'sync_confirm_summary': 'Klar til at downloade {count} {file_word} ({size}). Fortsæt?',
        'sync_confirm_yes': 'Ja, Start Synkronisering',
        'sync_confirm_no': 'Gå Tilbage',
        'sync_last_synced': 'Sidst synkroniseret: {time}',
        'sync_never_synced': 'Aldrig synkroniseret',
        'sync_quick_sync': '⚡Hurtig Synkronisering',
        'sync_quick_sync_help': 'Spring gennemgang over og download alle nye og opdaterede filer med det samme',
        'sync_open_folder': '📂 Åbn Mappe',
        'sync_history_title': '📜 Synkroniseringshistorik',
        'sync_history_empty': 'Ingen synkroniseringshistorik endnu.',
        'sync_history_entry': '{time} — {count} {file_word} synkroniseret på tværs af {courses} {course_word}',
        'sync_replace_original': 'Erstat original med seneste version',
        'sync_replaced_success': 'Erstattede original: {filename}',
        'sync_files_uptodate_count': '✅ {count} {file_word} er allerede opdaterede',
        'sync_file_removed_from_canvas': 'Filen "{filename}" er ikke længere tilgængelig på Canvas (kan være slettet af underviseren).',
        'sync_duplicate_pair': '⚠️ Denne mappe er allerede parret med dette kursus.',
        'sync_folder_not_found': '❌ Mappe ikke fundet: {path}. Den kan være slettet, omdøbt, eller drevet er frakoblet.',
        'sync_analyzing_spinner': 'Analyserer kurser...',
        'sync_analysis_rate_limit': 'Venter kort for at undgå API-hastighedsbegrænsninger...',
        'sync_files_total_size': '{count} {file_word} — {size} i alt',

        # Sync — Step Wizard & Ny UI
        'sync_step_select_folders': '📁 Vælg',
        'sync_step_review': '🔍 Gennemgå',
        'sync_step_syncing': '⬇️ Synk',
        'sync_step_complete': '✅ Færdig',
        'sync_search_courses': 'Søg kurser...',
        'sync_confirm_title': 'Bekræft Synkronisering',
        'sync_confirm_proceed': 'Du er ved at downloade {count} {file_word} ({size}) til {folders} {folder_word}. Fortsæt?',
        'sync_confirm_yes': 'Ja, start synkronisering',
        'sync_confirm_no': 'Nej, gå tilbage',
        'sync_per_course_btn': 'Synk Denne',
        'sync_quick_sync': 'Hurtig Synk Alle',
        'sync_quick_sync_desc': 'Synkroniser alle tilknyttede mapper uden gennemgang',
        'sync_analyzing_progress': 'Analyserer kursus {current} af {total}...',
        'sync_summary_card': 'Downloadede {new_count} nye og {upd_count} opdaterede {file_word} ({size})',
        'sync_no_changes_course': 'Alle filer er opdaterede',
        'sync_history_title': '📜 Synkroniseringshistorik',
        'sync_history_entry': '{time} — {count} {file_word} synkroniseret fra {courses} {course_word}',
        'sync_progress_text': '{current} / {total} filer',
        'sync_complete_text': 'Færdig!',
        'sync_complete_bar': 'Synkronisering Fuldført',
        'sync_success_title': 'Synkronisering Gennemført! Synkroniserede {count} {file_word}',
        'sync_open_folder_btn': '📂 Åbn mappe',
        'sync_see_synced_files': 'Se {count} synkroniserede filer',
        'sync_additional_settings': '⚙️ Yderligere synkroniseringsindstillinger',
        'sync_organize_toggle': '📂 Organiser filer i Canvas-modulmapper',
        'sync_organize_help': 'Flyt eksisterende filer til undermapper der matcher Canvas kursusmodulstrukturen. Filer flyttes, slettes aldrig. Dine ændringer (f.eks. udfyldte opgaver) bevares.',
        'sync_organizing_progress': 'Organiserer filer i modulmapper for {course}...',
        'sync_organized_count': '📂 Organiserede {count} {file_word} i modulmapper',
        'sync_course_prefix': 'Kursus: ',
        'sync_change_course': 'Skift Kursus',
        'sync_select_course_btn': 'Vælg Kursus',

    }
}

def get_text(key, lang='en', **kwargs):
    """
    Get translated text for the given key and language.
    
    Args:
        key: Translation key
        lang: Language code ('en' or 'da')
        **kwargs: Format parameters for string formatting
    
    Returns:
        Translated string with formatting applied
    """
    text = TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text
