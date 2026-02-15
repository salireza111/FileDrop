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
  File /r "${PROJECT_ROOT}\\dist\\FileDrop\\*"
  CreateShortCut "$DESKTOP\\FileDrop.lnk" "$INSTDIR\\FileDrop.exe"
SectionEnd
