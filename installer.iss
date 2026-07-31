; PDF 편집기 설치 프로그램 (Inno Setup)
; 사용법: ISCC.exe /DAppVer=<버전> installer.iss
; 실행 중인 파일을 직접 덮어쓰지 않는 실행기+버전폴더 구조를 그대로
; 따르도록, 설치 위치는 항상 %LOCALAPPDATA%\PDF편집기 로 고정한다
; (관리자 권한 불필요 — 앱 내부 자동 업데이트가 이 경로를 그대로 사용).
#ifndef AppVer
  #define AppVer "0.0"
#endif

[Setup]
AppId={{6C6E5F2B-6E39-4C7C-9C6E-4F1B2E7B6A3D}
AppName=PDF 편집기
AppVersion={#AppVer}
AppPublisher=Disziplin1
DefaultDirName={localappdata}\PDF편집기
DisableDirPage=yes
DefaultGroupName=PDF 편집기
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=PDF_Editor_Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\PDF 편집기.exe
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Files]
Source: "dist\PDF 편집기.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\current.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\PDF 편집기\*"; DestDir: "{app}\versions\{#AppVer}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PDF 편집기"; Filename: "{app}\PDF 편집기.exe"
Name: "{autodesktop}\PDF 편집기"; Filename: "{app}\PDF 편집기.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PDF 편집기.exe"; Description: "설치 후 바로 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 앱 내부 자동 업데이트가 설치 이후 versions\ 안에 새 버전 폴더를
; 추가하므로, 제거 시 인스톨러가 기억하는 파일뿐 아니라 폴더 전체를 지운다.
Type: filesandordirs; Name: "{app}"
