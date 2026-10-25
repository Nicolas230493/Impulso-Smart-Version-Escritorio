; Script de Inno Setup para Impulso Smart POS
#define MyAppName "Impulso Smart POS"
#define MyAppExeName "ImpulsoSmart.exe"
#define MyIconName "logo.ico"

[Setup]
AppId={{D3B3E3E3-3E3E-4E4E-BEBE-E3E3E3E3E3E3}
AppName={#MyAppName}
AppVersion=1.0
AppPublisher=Impulso Digital Sgo
DefaultDirName=C:\ImpulsoSmart
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Tarea 1: Carpeta de salida fuera del directorio de sincronización para evitar bloqueos
OutputDir=Output_Installer
OutputBaseFilename=ImpulsoSmart_v1_Setup
; Tarea 1: Asegurar que el icono sea el correcto
SetupIconFile="{#SourcePath}\{#MyIconName}"
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "spanish"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tarea 2: Robustez con ignoreversion en todos los archivos del sistema
Source: "dist\ImpulsoSmart\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Base de datos: No sobrescribir (Regla de Oro), pero usamos ignoreversion para el contenedor si fuera necesario
Source: "db.sqlite3"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall ignoreversion; Check: FileExistsSource
; Icono para la aplicación
Source: "{#MyIconName}"; DestDir: "{app}"; Flags: ignoreversion

[Code]
function FileExistsSource: Boolean;
begin
  Result := FileExists(ExpandConstant('{src}\db.sqlite3'));
end;

[Icons]
; Tarea 2: Asegurar que los accesos directos apunten al icono correctamente
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyIconName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyIconName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; Tarea 3: Validación de Recursos mediante Pre-procesador
#ifexist MyIconName
  #pragma message "Validación: logo.ico detectado correctamente."
#else
  #pragma warning "ADVERTENCIA: No se detectó logo.ico. La compilación fallará si el archivo no está en: " + SourcePath
#endif
