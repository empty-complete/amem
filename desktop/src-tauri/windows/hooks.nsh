; Хуки установщика NSIS (bundle.windows.nsis.installerHooks в tauri.conf.json).
;
; Перед удалением — остановить фон, иначе процессы службы и PostgreSQL держали бы файлы комплекта:
; 1. `amemo.exe --quit` передаёт команду работающему приложению (single-instance) и ждёт, пока оно остановит службу
;    и PostgreSQL; когда приложение не запущено, команда просто завершается;
; 2. если приложение уже закрыли без этого (снятая задача), PostgreSQL останавливает `bin\amemo.exe pg stop`, а
;    оставшиеся процессы Python комплекта завершаются.
!macro NSIS_HOOK_PREUNINSTALL
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --quit'
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\bin\amemo.exe"
    nsExec::Exec '"$INSTDIR\bin\amemo.exe" pg stop'
    Pop $0
  ${EndIf}
  nsExec::Exec `powershell -NoProfile -NonInteractive -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object Path -like '$INSTDIR\runtime\*' | Stop-Process -Force"`
  Pop $0
!macroend
