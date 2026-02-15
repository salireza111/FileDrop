!include "MUI2.nsh"

!define PRODUCT_NAME "FileDrop"
!ifndef RELEASE_TAG
  !define RELEASE_TAG "dev"
!endif

Name "${PRODUCT_NAME}"
OutFile "FileDrop-${RELEASE_TAG}-windows.exe"
InstallDir "$PROGRAMFILES\\FileDrop"
RequestExecutionLevel user

Page directory
Page instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  !ifexist "dist\\FileDrop\\*"
    File /r "dist\\FileDrop\\*"
  !else
    !ifexist "dist\\FileDrop.exe"
      File "dist\\FileDrop.exe"
    !else
      !error "Build output not found in dist/"
    !endif
  !endif
  CreateShortCut "$DESKTOP\\FileDrop.lnk" "$INSTDIR\\FileDrop.exe"
SectionEnd
