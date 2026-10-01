echo === DFCI QEMU recovery test ===

if not exist owner-applied.txt then
  echo === Applying owner enrollment ===
  DfciApply.efi -v -i OwnerEnroll_Provision_apply.bin -p OwnerPermissions_Permission_apply.bin -s OwnerSettings_Settings_apply.bin
  echo done > owner-applied.txt
  reset -c
endif

if not exist user-applied.txt then
  echo === Applying user enrollment ===
  DfciApply.efi -v -i UserEnroll_Provision_apply.bin -p UserPermissions_Permission_apply.bin -s UserSettings_Settings_apply.bin
  echo done > user-applied.txt
  reset -c
endif

if not exist bootstrap-complete.txt then
  echo === Running DFCI bootstrap recovery ===
  DfciSARecovery.efi
  echo done > bootstrap-complete.txt
  reset -c
endif

if not exist recovery-complete.txt then
  echo === Running DFCI settings recovery ===
  DfciSARecovery.efi
  echo done > recovery-complete.txt
  reset -c
endif

echo === DFCI QEMU recovery test complete ===
