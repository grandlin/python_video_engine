# Claude CLI for PowerShell
# Usage: .\claude.ps1 "your prompt here"

param(
    [Parameter(Mandatory=$true, Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$Prompt
)

$pythonPath = "C:\Users\Grand_lin\AppData\Local\Programs\Python\Python313\python.exe"
$scriptPath = "D:\Cursor\Grand\python_video_engine\claude_simple.py"

$promptText = $Prompt -join " "

& $pythonPath $scriptPath $promptText
