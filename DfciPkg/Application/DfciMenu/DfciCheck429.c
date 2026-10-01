/** @file
DfciCheck429.c

Device Firmware Configuration Interface - Stand Alone driver that can be loaded
at the UEFI Shell

Copyright (C) Microsoft Corporation. All rights reserved.
SPDX-License-Identifier: BSD-2-Clause-Patent

**/

#include <Uefi.h>

#include <Protocol/ShellParameters.h>

#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/HttpLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PrintLib.h>
#include <Library/ShellLib.h>
#include <Library/UefiApplicationEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>

#include "DfciPrivate.h"
#include "DfciRequest.h"

// *---------------------------------------------------------------------------------------*
// * Application Global Variables                                                          *
// *---------------------------------------------------------------------------------------*
DFCI_NETWORK_REQUEST  mDfciNetworkRequest = { 0 };

#define HTTP_HOST_NAME_PREFIX   "http://"
#define HTTPS_HOST_NAME_PREFIX  "https://"
#define HOST_NAME_SUFFIX        "/return_429"

/**
 * Read a certificate file into an allocated buffer.
 *
 * @param[in]  FileName    - Certificate file name
 * @param[out] Buffer      - Allocated certificate buffer
 * @param[out] BufferSize  - Certificate buffer size
 *
 * @retval EFI_SUCCESS            The certificate was read.
 * @retval EFI_INVALID_PARAMETER  A parameter or file size is invalid.
 * @retval EFI_OUT_OF_RESOURCES   The certificate buffer could not be allocated.
 */
STATIC
EFI_STATUS
ReadCertificateFile (
  IN  CONST CHAR16  *FileName,
  OUT UINT8         **Buffer,
  OUT UINTN         *BufferSize
  )
{
  SHELL_FILE_HANDLE  FileHandle;
  UINT64             FileSize;
  UINT64             ReadSize;
  EFI_STATUS         Status;

  if ((FileName == NULL) || (Buffer == NULL) || (BufferSize == NULL)) {
    return EFI_INVALID_PARAMETER;
  }

  *Buffer     = NULL;
  *BufferSize = 0;
  FileHandle  = NULL;

  Status = ShellOpenFileByName (
             FileName,
             &FileHandle,
             EFI_FILE_MODE_READ,
             0
             );
  if (EFI_ERROR (Status)) {
    AsciiPrint ("Failed to open certificate %s. Status=%r\n", FileName, Status);
    return Status;
  }

  Status = ShellGetFileSize (FileHandle, &FileSize);
  if (EFI_ERROR (Status)) {
    AsciiPrint ("Failed to get the size of certificate %s. Status=%r\n", FileName, Status);
    goto EXIT;
  }

  if ((FileSize == 0) || (FileSize > MAX_UINTN)) {
    AsciiPrint ("Certificate %s has an invalid size: %Lu\n", FileName, FileSize);
    Status = EFI_INVALID_PARAMETER;
    goto EXIT;
  }

  *Buffer = AllocatePool ((UINTN)FileSize);
  if (*Buffer == NULL) {
    Status = EFI_OUT_OF_RESOURCES;
    goto EXIT;
  }

  ReadSize = FileSize;
  Status   = ShellReadFile (FileHandle, &ReadSize, *Buffer);
  if (EFI_ERROR (Status) || (ReadSize != FileSize)) {
    AsciiPrint ("Failed to read certificate %s. Status=%r\n", FileName, Status);
    if (!EFI_ERROR (Status)) {
      Status = EFI_DEVICE_ERROR;
    }

    FreePool (*Buffer);
    *Buffer = NULL;
    goto EXIT;
  }

  *BufferSize = (UINTN)FileSize;

EXIT:
  ShellCloseFile (&FileHandle);
  return Status;
}

/**
*  This function is the main entry of the DfciCheck429 application.
*
* @param[in]   ImageHandle
* @param[in]   SystemTable
*
**/
EFI_STATUS
EFIAPI
DfciCheck429Entry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINTN                          host_name_len;
  CHAR8                          *host_name_url;
  CONST CHAR8                    *host_name_prefix;
  CONST CHAR16                   *host_name;
  CONST CHAR16                   *certificate_file;
  UINT8                          *CertificateBuffer;
  UINTN                          CertificateBufferSize;
  UINTN                          offset;
  EFI_SHELL_PARAMETERS_PROTOCOL  *Parameters;
  EFI_STATUS                     Status;
  EFI_STATUS                     RestoreStatus;
  BOOLEAN                        CertificateEnabled;

  ZeroMem (&mDfciNetworkRequest, sizeof (mDfciNetworkRequest));
  Parameters         = NULL;
  CertificateEnabled = FALSE;
  CertificateBuffer  = NULL;
  certificate_file   = NULL;

  Status = gBS->HandleProtocol (
                  ImageHandle,
                  &gEfiShellParametersProtocolGuid,
                  (VOID **)&Parameters
                  );

  if (EFI_ERROR (Status) || (Parameters == NULL)) {
    // This UEFI_DRIVER application must run under the UEFI Shell
    DEBUG ((DEBUG_ERROR, "%a - Shell Parameters protocol not available. %r\n", __FUNCTION__, Status));
    return 8;
  }

  if ((Parameters->Argc != 2) && (Parameters->Argc != 4)) {
    AsciiPrint ("Incorrect parameters:\n");
    AsciiPrint ("\n");
    AsciiPrint ("  DfciCheck429 [-c certificate-file] host-name-or-ip-address\n");
    AsciiPrint ("\n");
    AsciiPrint ("  Examples:\n");
    AsciiPrint ("    DfciCheck host.docker.internal.com\n");
    AsciiPrint ("    DfciCheck -c DFCI_HTTPS.cer 192.168.1.115\n");
    return EFI_INVALID_PARAMETER;
  }

  if (Parameters->Argc == 4) {
    if (StrCmp (Parameters->Argv[1], L"-c") != 0) {
      AsciiPrint ("Expected -c before the certificate file name.\n");
      return EFI_INVALID_PARAMETER;
    }

    certificate_file = Parameters->Argv[2];
    host_name        = Parameters->Argv[3];
    host_name_prefix = HTTPS_HOST_NAME_PREFIX;
  } else {
    host_name        = Parameters->Argv[1];
    host_name_prefix = HTTP_HOST_NAME_PREFIX;
  }

  host_name_len = StrLen (host_name);
  if (host_name_len < 1) {
    AsciiPrint ("Invalid or missing host-name-or-ip-address\n");
    return EFI_INVALID_PARAMETER;
  }

  AsciiPrint ("This test takes at least 40 seconds, and may take over a minute with network retires.\n");

  //
  // Build the CHAR8 URL from the CHAR16 parameter, prefix, suffix, and a '\0'.
  // Note that sizeof returns the size including the NULL, so we only need one of those NULL characters.
  host_name_len += AsciiStrLen (host_name_prefix) + sizeof (HOST_NAME_SUFFIX);
  host_name_url  = AllocatePool (host_name_len);
  if (host_name_url == NULL) {
    AsciiPrint ("TEST FAILED. Out of memory\n");
    return EFI_OUT_OF_RESOURCES;
  }

  Status = AsciiStrCpyS (host_name_url, host_name_len, host_name_prefix);
  if (EFI_ERROR (Status)) {
    AsciiPrint ("TEST FAILED. AsciiStrCpyS failed\n");
    goto EXIT;
  }

  offset = AsciiStrLen (host_name_prefix);
  Status = UnicodeStrToAsciiStrS (host_name, &host_name_url[offset], host_name_len - offset);
  if (EFI_ERROR (Status)) {
    AsciiPrint ("TEST FAILED. UnicodeStrToAsciiStrS failed\n");
    goto EXIT;
  }

  Status = AsciiStrCatS (host_name_url, host_name_len, HOST_NAME_SUFFIX);
  if (EFI_ERROR (Status)) {
    AsciiPrint ("TEST FAILED. AsciiStrCatS failed\n");
    goto EXIT;
  }

  AsciiPrint ("Processing url=%a\n", host_name_url);

  mDfciNetworkRequest.HttpRequest.Url = host_name_url;
  mDfciNetworkRequest.MainLogic       = Check429Logic;

  if (certificate_file != NULL) {
    Status = ReadCertificateFile (
               certificate_file,
               &CertificateBuffer,
               &CertificateBufferSize
               );
    if (EFI_ERROR (Status)) {
      AsciiPrint ("TEST FAILED. Unable to read HTTPS certificate.\n");
      goto EXIT;
    }

    mDfciNetworkRequest.HttpsCert     = CertificateBuffer;
    mDfciNetworkRequest.HttpsCertSize = CertificateBufferSize;

    Status = EnableDfciCertificate (&mDfciNetworkRequest);
    if (EFI_ERROR (Status)) {
      AsciiPrint ("TEST FAILED. Unable to configure HTTPS certificate. Status=%r\n", Status);
      goto EXIT;
    }

    CertificateEnabled = TRUE;
  }

  // Try every NIC in the system until one fills the first part of the request.
  Status = TryEachNICThenProcessRequest (&mDfciNetworkRequest);

  if (EFI_ERROR (Status)) {
    AsciiPrint ("TEST FAILED.  No NIC satisfied the request.\n");
  } else {
    DEBUG ((DEBUG_INFO, "Url   %a\n", mDfciNetworkRequest.HttpRequest.Url));
    DEBUG ((DEBUG_INFO, "HttpStatus = %d, Status-%r\n", mDfciNetworkRequest.HttpStatus.HttpStatus, Status));
    DEBUG ((DEBUG_INFO, "HttpStatus = %a\n", GetHttpErrorMsg (mDfciNetworkRequest.HttpStatus.HttpStatus)));

    if (mDfciNetworkRequest.HttpStatus.HttpStatus == HTTP_STATUS_429_TOO_MANY_REQUESTS) {
      AsciiPrint ("TEST PASSED. Network stack returned 429 as expected.\n");
      Status = EFI_SUCCESS;
    } else {
      if (mDfciNetworkRequest.HttpStatus.HttpStatus == HTTP_STATUS_UNSUPPORTED_STATUS) {
        AsciiPrint ("TEST FAILED.  Http status could not be retrieved.\n");
      } else {
        AsciiPrint ("TEST FAILED.  Unexpected status = %a\n", GetHttpErrorMsg (mDfciNetworkRequest.HttpStatus.HttpStatus));
      }

      Status = EFI_DEVICE_ERROR;
    }
  }

EXIT:
  if (CertificateEnabled) {
    RestoreStatus = RestoreDfciCertificates ();
    if (EFI_ERROR (RestoreStatus)) {
      AsciiPrint ("TEST FAILED. Unable to restore HTTPS certificates. Status=%r\n", RestoreStatus);
      Status = RestoreStatus;
    }
  }

  if (CertificateBuffer != NULL) {
    FreePool (CertificateBuffer);
  }

  if (host_name_url != NULL) {
    FreePool (host_name_url);
  }

  return Status;
}
