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
        'flat_structure': 'Full (All files in one folder)',
        'destination': 'Destination',
        'select_folder': '📂 Select Folder',
        'path_label': 'Path',
        'back_btn': 'Back',
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
        'flat_structure': 'Flad (Alle filer i én mappe)',
        'destination': 'Destination',
        'select_folder': '📂 Vælg Mappe',
        'path_label': 'Sti',
        'back_btn': 'Tilbage',
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
