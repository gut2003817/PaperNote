; Included from package.json (build.nsis.include).
; User data lives in $INSTDIR\data (see electron/data-dir.cjs). The default
; uninstaller does RMDir /r $INSTDIR on every update and uninstall, which would
; wipe the paper library, so remove everything except the data folder.
; ASCII only: makensis reads this file with the system code page.

!macro customRemoveFiles
  SetOutPath $TEMP
  FindFirst $R0 $R1 "$INSTDIR\*.*"
  er_remove_loop:
    StrCmp $R1 "" er_remove_done
    StrCmp $R1 "." er_remove_next
    StrCmp $R1 ".." er_remove_next
    StrCmp $R1 "data" er_remove_next
    StrCmp $R1 "data.migrating" er_remove_next
    IfFileExists "$INSTDIR\$R1\*.*" 0 er_remove_file
      RMDir /r "$INSTDIR\$R1"
      Goto er_remove_next
    er_remove_file:
      Delete "$INSTDIR\$R1"
  er_remove_next:
    FindNext $R0 $R1
    Goto er_remove_loop
  er_remove_done:
  FindClose $R0
  ; Only removes the folder when it is empty (no data kept).
  RMDir $INSTDIR
!macroend
