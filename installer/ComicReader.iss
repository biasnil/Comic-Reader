; Inno Setup script for Comic Reader's setup.exe.  Build with:  build.bat installer
; (or: ISCC /DAppVersion=1.0.0 installer\ComicReader.iss  after building both PyInstaller targets)
;
; Expects:  dist\ComicReader\             (ComicReader.spec)
;           dist\manga-translator\        (plugins\manga_translator\MangaTranslator.spec; optional)
; Produces: dist\ComicReader-Setup-<version>.exe
;
; Components: the reader (always) and the Manga Translator plugin (optional, unticked by default).
; Settings and the library in %USERPROFILE%\.comic_reader are never touched by install/uninstall.

#ifndef AppVersion
  #define AppVersion "dev"
#endif
#define AppName "Comic Reader"
#define AppExe "ComicReader.exe"

[Setup]
AppId={{C848B07F-68FE-4764-B64C-96BBE1A4DDFC}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Iven
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist
OutputBaseFilename=ComicReader-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
#if FileExists(AddBackslash(SourcePath) + "..\assets\icon.ico")
SetupIconFile=..\assets\icon.ico
#endif

[Types]
Name: "standard"; Description: "Comic Reader"
Name: "full"; Description: "Comic Reader + Manga Translator plugin"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "main"; Description: "Comic Reader"; Types: standard full custom; Flags: fixed
#if DirExists(AddBackslash(SourcePath) + "..\dist\manga-translator")
Name: "translator"; Description: "Manga Translator plugin (Japanese -> English page translation, about 200 MB more; its AI model downloads on first use)"; Types: full
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "associate"; Description: "Open comic files (.cbz .cbr .cb7 .cbt) with Comic Reader"; GroupDescription: "File types:"; Flags: unchecked

[Files]
Source: "..\dist\ComicReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
#if DirExists(AddBackslash(SourcePath) + "..\dist\manga-translator")
Source: "..\dist\manga-translator\*"; DestDir: "{app}\plugins\manga-translator"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: translator
#endif

#if DirExists(AddBackslash(SourcePath) + "..\dist\manga-translator")
[InstallDelete]
; unticking the plugin on a re-install removes it
Type: filesandordirs; Name: "{app}\plugins\manga-translator"; Components: not translator
#endif

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\ComicReader.Comic"; ValueType: string; ValueName: ""; ValueData: "Comic book"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\ComicReader.Comic\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\ComicReader.Comic\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.cbz\OpenWithProgids"; ValueType: string; ValueName: "ComicReader.Comic"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.cbr\OpenWithProgids"; ValueType: string; ValueName: "ComicReader.Comic"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.cb7\OpenWithProgids"; ValueType: string; ValueName: "ComicReader.Comic"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.cbt\OpenWithProgids"; ValueType: string; ValueName: "ComicReader.Comic"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
