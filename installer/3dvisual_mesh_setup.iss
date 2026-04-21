#define AppName "3DVisual Mesh"
#define AppVersion "0.1.0"
#define AppReleaseLabel "3DVisual Mesh (BETA) (Version 0.1.0)"
#define AppDirName "3DVisual Mesh"
#define SourceDir "..\\dist\\3DVisual Mesh Share (BETA) (Version 0.1.0)"

[Setup]
AppId={{3DVisualMesh-0F5D3C7F-87D2-4A55-9F94-AE2D851E2B46}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Yanis
DefaultDirName={localappdata}\Programs\{#AppDirName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\assets\3dvisual_mesh_icon.ico
OutputDir=..\\dist
OutputBaseFilename=3DVisualMeshSetup_0.1.0
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=..\\assets\\3dvisual_mesh_icon.ico
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\\{#AppName}"; Filename: "{app}\\Start 3DVisual Mesh (BETA) (Version 0.1.0).bat"; WorkingDir: "{app}"; IconFilename: "{app}\\assets\\3dvisual_mesh_icon.ico"
Name: "{autodesktop}\\{#AppName}"; Filename: "{app}\\Start 3DVisual Mesh (BETA) (Version 0.1.0).bat"; WorkingDir: "{app}"; IconFilename: "{app}\\assets\\3dvisual_mesh_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\\Start 3DVisual Mesh (BETA) (Version 0.1.0).bat"; Description: "Start 3DVisual Mesh now"; Flags: postinstall skipifsilent
