[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
$wpf = Join-Path $framework 'WPF'
$sdk = Join-Path $PSScriptRoot 'sdk'
$output = Join-Path $PSScriptRoot 'DoujieStudio.exe'
$arguments = @(
    '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/debug-',
    '/codepage:65001', "/out:$output", "/win32manifest:$PSScriptRoot\studio.manifest",
    "/reference:$wpf\PresentationCore.dll", "/reference:$wpf\PresentationFramework.dll",
    "/reference:$wpf\WindowsBase.dll", "/reference:$framework\System.Xaml.dll",
    "/reference:$sdk\Microsoft.Web.WebView2.Core.dll",
    "/reference:$sdk\Microsoft.Web.WebView2.Wpf.dll",
    "$PSScriptRoot\DoujieStudio.cs"
)
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "DoujieStudio build failed ($LASTEXITCODE)." }
