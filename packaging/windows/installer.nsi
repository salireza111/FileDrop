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
  File /r "packaging\\windows\\stage\\*"
  CreateShortCut "$DESKTOP\\FileDrop.lnk" "$INSTDIR\\FileDrop.exe"
SectionEnd
