!include "MUI2.nsh"

!ifndef PROJECT_ROOT
  !define PROJECT_ROOT "."
!endif

!define PRODUCT_NAME "FileDrop"
!ifndef RELEASE_TAG
  !define RELEASE_TAG "dev"
!endif

Name "${PRODUCT_NAME}"
OutFile "${PROJECT_ROOT}\\FileDrop-${RELEASE_TAG}-windows.exe"
InstallDir "$PROGRAMFILES\\FileDrop"
RequestExecutionLevel user

Page directory
Page instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  !ifexist "${PROJECT_ROOT}\\dist\\FileDrop\\FileDrop.exe"
    File /r "${PROJECT_ROOT}\\dist\\FileDrop\\*"
  !else
    !ifexist "${PROJECT_ROOT}\\dist\\FileDrop.exe"
      File "${PROJECT_ROOT}\\dist\\FileDrop.exe"
    !else
      !error "Build output not found in dist/"
    !endif
  !endif
  CreateShortCut "$DESKTOP\\FileDrop.lnk" "$INSTDIR\\FileDrop.exe"
SectionEnd
