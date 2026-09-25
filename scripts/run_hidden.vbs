' Runs a launcher in this folder with no console window: wscript run_hidden.vbs run_weekly.cmd
' Window style 0 = hidden; True = wait so Task Scheduler sees the real exit.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
cmdPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), WScript.Arguments(0))
shell.Run """" & cmdPath & """", 0, True
