Set objShell = CreateObject("WScript.Shell")
strScriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
strPythonScript = strScriptPath & "\app.py"
objShell.Run "python """ & strPythonScript & """", 0, False
