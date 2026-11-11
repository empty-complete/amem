; Хуки установщика NSIS (bundle.windows.nsis.installerHooks в tauri.conf.json; шаблон — tauri-bundler, installer.nsi).
;
; Удаление (спецификация приложения для Windows, п. 13). Обновление (updater, флаг /UPDATE) удалитель не запускает, а
; если запускает (переустановка) с /UPDATE — $UpdateMode = 1, и ничего из amemo не убирается.
; 1. Остановить фон, иначе процессы службы и PostgreSQL держали бы файлы комплекта: `amemo.exe --quit` передаёт
;    команду работающему приложению (single-instance) и ждёт, пока оно остановит службу и PostgreSQL; приложение не
;    запущено — команда просто завершается. Если его закрыли без этого (снятая задача), PostgreSQL останавливает
;    `bin\amemo.exe pg stop`, а оставшиеся процессы Python комплекта завершаются.
; 2. Убрать подключения агентов (`amemo uninstall claude-code`, `codex`) — пока запускатель и комплект на месте.
;    Плагин в аккаунте claude.ai убирает человек (Customize → Plugins).
; 3. После удаления файлов приложения — комплект, загрузки, журналы и state.json. Ключ автозапуска HKCU\…\Run удаляет
;    сам шаблон. Папка данных (база, хранилище копий, бэкапы) и amemo.toml остаются: их удаляет человек.
!macro NSIS_HOOK_PREUNINSTALL
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --quit'
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\bin\amemo.exe"
    nsExec::Exec '"$INSTDIR\bin\amemo.exe" pg stop'
    Pop $0
    ${If} $UpdateMode <> 1
      nsExec::Exec '"$INSTDIR\bin\amemo.exe" uninstall claude-code'
      Pop $0
      nsExec::Exec '"$INSTDIR\bin\amemo.exe" uninstall codex'
      Pop $0
    ${EndIf}
  ${EndIf}
  nsExec::Exec `powershell -NoProfile -NonInteractive -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object Path -like '$INSTDIR\runtime\*' | Stop-Process -Force"`
  Pop $0
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
    RMDir /r "$INSTDIR\runtime"
    RMDir /r "$INSTDIR\downloads"
    RMDir /r "$INSTDIR\logs"
    Delete "$INSTDIR\state.json"
    RMDir "$INSTDIR"
  ${EndIf}
!macroend
