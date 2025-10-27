' Runs the batch file without showing any console windows.
Dim sh, batPath
Set sh = CreateObject("Wscript.Shell")

' >>>>> EDIT IF YOUR PATH DIFFERS <<<<<
batPath = "C:\Users\Malusi\OneDrive - MACROCOMM\Desktop\macrocomm-ai-chatbot\startup\start_bot.bat"

' 0 = hidden window, False = do not wait
sh.Run "cmd /c """ & batPath & """", 0, False
