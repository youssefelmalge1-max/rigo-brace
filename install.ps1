# Rigo Brace — one-click installer.
#
# Installs the Rigo Brace add-on + application template into your Blender 5.0
# user folders, generates the plain startup scene, and creates a "Rigo Brace"
# icon on your Desktop that opens straight into the clean tool.
#
# Run from the project root in PowerShell:
#     ./install.ps1
#
# Re-run any time after changing the add-on to update your install.

$ErrorActionPreference = "Stop"

# --- Settings --------------------------------------------------------------- #
$BlenderExe   = "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
$BlenderVer   = "5.0"
$ProjectRoot  = $PSScriptRoot
$AddonSrc     = Join-Path $ProjectRoot "rigo_brace"
$TemplateSrc  = Join-Path $ProjectRoot "rigo_brace_template"
$MakeStartup  = Join-Path $ProjectRoot "tools\build_startup_gui.py"

# --- Resolve Blender user config paths -------------------------------------- #
$ConfigBase   = Join-Path $env:APPDATA "Blender Foundation\Blender\$BlenderVer"
$ExtDir       = Join-Path $ConfigBase "extensions\user_default\rigo_brace"
$TemplateDir  = Join-Path $ConfigBase "scripts\startup\bl_app_templates_user\rigo_brace"
$LegacyAddonRoot = Join-Path $ConfigBase "scripts\addons"
$QuadAddonDir = Join-Path $LegacyAddonRoot "quad_remesher_1_4"
$QuadBridgeCandidates = @(
    "C:\Users\youss\OneDrive\Desktop\QuadRemesher_1.4.1_BlenderBridge_Win.zip",
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "QuadRemesher_1.4.1_BlenderBridge_Win.zip")
)
$QuadBridgeZip = $QuadBridgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$RunningBlender = Get-Process -Name "blender" -ErrorAction SilentlyContinue

Write-Host "Installing Rigo Brace for Blender $BlenderVer ..." -ForegroundColor Cyan

if (-not (Test-Path $BlenderExe)) {
    throw "Blender not found at '$BlenderExe'. Edit `$BlenderExe in install.ps1."
}

# --- 1. Install the add-on as a user extension ------------------------------ #
if (Test-Path $ExtDir) { Remove-Item $ExtDir -Recurse -Force }
New-Item -ItemType Directory -Path $ExtDir -Force | Out-Null
Copy-Item -Path (Join-Path $AddonSrc "*") -Destination $ExtDir -Recurse -Force
Write-Host "  - add-on installed -> $ExtDir" -ForegroundColor Green

# Quad Remesher's GPL bridge is installed beside Rigo. Its commercial engine
# remains Exoside-managed and is downloaded/licensed only when the user runs it.
if ($QuadBridgeZip) {
    $ResolvedQuadDir = [IO.Path]::GetFullPath($QuadAddonDir)
    $ResolvedConfig = [IO.Path]::GetFullPath($ConfigBase)
    if (-not $ResolvedQuadDir.StartsWith($ResolvedConfig, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to install Quad Remesher outside Blender's user config."
    }
    if (Test-Path -LiteralPath $QuadAddonDir) {
        Remove-Item -LiteralPath $QuadAddonDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $LegacyAddonRoot -Force | Out-Null
    Expand-Archive -LiteralPath $QuadBridgeZip -DestinationPath $LegacyAddonRoot -Force
    $EnableQuadBridge = "import bpy; bpy.ops.preferences.addon_enable(module='quad_remesher_1_4'); bpy.ops.wm.save_userpref()"
    & $BlenderExe --background --python-expr $EnableQuadBridge | Out-Null
    Write-Host "  - Exoside Quad Remesher bridge installed and enabled" -ForegroundColor Green
} else {
    Write-Warning "  - Quad Remesher bridge zip was not found; Blender QuadriFlow remains available."
}

# --- 2. Install the application template ------------------------------------- #
if (Test-Path $TemplateDir) { Remove-Item $TemplateDir -Recurse -Force }
New-Item -ItemType Directory -Path $TemplateDir -Force | Out-Null
Copy-Item -Path (Join-Path $TemplateSrc "*") -Destination $TemplateDir -Recurse -Force
Write-Host "  - template installed -> $TemplateDir" -ForegroundColor Green

# --- 3. Generate the startup scene (GUI bake: regions + single viewport) ----- #
$StartupOut = Join-Path $TemplateDir "startup.blend"
& $BlenderExe --factory-startup --python $MakeStartup -- $StartupOut | Out-Null
if (Test-Path $StartupOut) {
    Write-Host "  - startup scene generated -> $StartupOut" -ForegroundColor Green
} else {
    Write-Warning "  - startup.blend was not created; template will use Blender's default scene."
}

# --- 4. Create the Desktop icon --------------------------------------------- #
$Desktop  = [Environment]::GetFolderPath("Desktop")
$LinkPath = Join-Path $Desktop "Rigo Brace.lnk"
$WScript  = New-Object -ComObject WScript.Shell
$Shortcut = $WScript.CreateShortcut($LinkPath)
$Shortcut.TargetPath       = $BlenderExe
$Shortcut.Arguments        = "--app-template rigo_brace"
$Shortcut.WorkingDirectory = Split-Path $BlenderExe
$Shortcut.IconLocation     = "$BlenderExe,0"
$Shortcut.Description       = "Rigo Brace Designer"
$Shortcut.Save()
Write-Host "  - desktop icon created -> $LinkPath" -ForegroundColor Green

Write-Host ""
if ($RunningBlender) {
    Write-Warning "Blender was already running during installation. Close every Blender window and reopen Rigo Brace before testing this update."
}
Write-Host "Done. Double-click 'Rigo Brace' on your Desktop to launch." -ForegroundColor Cyan
