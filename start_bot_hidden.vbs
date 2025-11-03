' Macrocomm Assistant — silent runner (root)
' Launches start_macrocomm_chatbot.cmd without showing a console window

Dim fso, sh, base, cmdPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

base    = fso.GetParentFolderName(WScript.ScriptFullName)
cmdPath = fso.BuildPath(base, "start_macrocomm_chatbot.cmd")

If Not fso.FileExists(cmdPath) Then
  MsgBox "Launcher not found:" & vbCrLf & cmdPath, 16, "Macrocomm Assistant"
  WScript.Quit 1
End If

' 0 = hidden, False = do not wait
sh.Run """" & cmdPath & """", 0, False

